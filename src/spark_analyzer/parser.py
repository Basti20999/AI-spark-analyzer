"""Parse spark's JSON export into the :mod:`spark_analyzer.models` model.

spark transfers data as protobuf. The official JSON endpoint
(``https://spark.lucko.me/<code>?raw=1&full=true``) decodes that protobuf to
JSON for us, so this module only has to walk JSON.

Two wrinkles it handles:

* **Key casing** — protobuf→JSON uses camelCase (``classSources``), but some
  tools emit snake_case (``class_sources``). Every lookup tries both.
* **Tree shape** — a thread's frames are stored as a *flat pool*
  (``ThreadNode.children``) with index references (``children_refs``). Older
  exports nest frames directly. Both forms are supported.
"""

from __future__ import annotations

from .models import Profile, StackNode, ThreadProfile, WindowStats


def _get(d: dict, *keys, default=None):
    """Return the first present key (tries camelCase and snake_case)."""
    for k in keys:
        if isinstance(d, dict) and k in d and d[k] is not None:
            return d[k]
    return default


def _resolve_source(
    class_name: str,
    method_name: str,
    class_sources: dict,
    method_sources: dict,
) -> str | None:
    """Attribute a frame to a plugin/mod using spark's source maps."""
    if method_sources:
        key = f"{class_name}.{method_name}"
        if key in method_sources:
            return method_sources[key]
    return class_sources.get(class_name)


def _make_node(raw: dict, class_sources: dict, method_sources: dict) -> StackNode:
    class_name = _get(raw, "className", "class_name", default="") or ""
    method_name = _get(raw, "methodName", "method_name", default="") or ""
    line_number = _get(raw, "lineNumber", "line_number", default=0) or 0
    method_desc = _get(raw, "methodDesc", "method_desc", default="") or ""
    times = _get(raw, "times", default=[]) or []
    return StackNode(
        class_name=class_name,
        method_name=method_name,
        line_number=int(line_number),
        method_desc=method_desc,
        times=[float(t) for t in times],
        source=_resolve_source(class_name, method_name, class_sources, method_sources),
    )


def _node_from_pool(
    pool: list,
    idx: int,
    class_sources: dict,
    method_sources: dict,
    cache: dict[int, StackNode],
) -> StackNode:
    """Build a node from the flat pool, resolving children by index."""
    cached = cache.get(idx)
    if cached is not None:
        return cached
    raw = pool[idx]
    node = _make_node(raw, class_sources, method_sources)
    cache[idx] = node  # set before recursing to guard against cycles
    refs = _get(raw, "childrenRefs", "children_refs", default=[]) or []
    node.children = [
        _node_from_pool(pool, c, class_sources, method_sources, cache)
        for c in refs
        if 0 <= c < len(pool)
    ]
    return node


def _node_nested(raw: dict, class_sources: dict, method_sources: dict) -> StackNode:
    """Build a node from the legacy nested format (``children`` are frames)."""
    node = _make_node(raw, class_sources, method_sources)
    kids = raw.get("children") or []
    node.children = [_node_nested(c, class_sources, method_sources) for c in kids]
    return node


def _parse_thread(thread: dict, class_sources: dict, method_sources: dict) -> ThreadProfile:
    name = thread.get("name", "?")
    pool = thread.get("children") or []
    refs = _get(thread, "childrenRefs", "children_refs")
    if refs:
        # Flat format: `children` is the node pool, `refs` are the root indices.
        cache: dict[int, StackNode] = {}
        roots = [
            _node_from_pool(pool, i, class_sources, method_sources, cache)
            for i in refs
            if 0 <= i < len(pool)
        ]
    else:
        # Nested format: `children` are the roots directly.
        roots = [_node_nested(c, class_sources, method_sources) for c in pool]
    return ThreadProfile(name=name, roots=roots)


def _parse_windows(data: dict) -> list[WindowStats]:
    stats_map = _get(data, "timeWindowStatistics", "time_window_statistics", default={}) or {}
    out: list[WindowStats] = []
    for key, s in stats_map.items():
        try:
            window = int(key)
        except (TypeError, ValueError):
            window = 0
        out.append(
            WindowStats(
                window=window,
                ticks=int(_get(s, "ticks", default=0) or 0),
                tps=float(_get(s, "tps", default=0) or 0),
                mspt_median=float(_get(s, "msptMedian", "mspt_median", default=0) or 0),
                mspt_max=float(_get(s, "msptMax", "mspt_max", default=0) or 0),
                cpu_process=float(_get(s, "cpuProcess", "cpu_process", default=0) or 0),
                cpu_system=float(_get(s, "cpuSystem", "cpu_system", default=0) or 0),
                players=int(_get(s, "players", default=0) or 0),
                entities=int(_get(s, "entities", default=0) or 0),
                chunks=int(_get(s, "chunks", default=0) or 0),
                duration=int(_get(s, "duration", default=0) or 0),
            )
        )
    out.sort(key=lambda w: w.window)
    return out


def _parse_platform(metadata: dict) -> dict:
    ps = _get(metadata, "platformStatistics", "platform_statistics", default={}) or {}
    if not ps:
        return {}
    result: dict = {}
    tps = ps.get("tps") or {}
    if tps:
        result["tps"] = {
            "last1m": tps.get("last1m"),
            "last5m": tps.get("last5m"),
            "last15m": tps.get("last15m"),
            "target": _get(tps, "gameTargetTps", "game_target_tps"),
        }
    if ps.get("mspt"):
        result["mspt"] = ps["mspt"]
    if ps.get("memory"):
        result["memory"] = ps["memory"]
    if ps.get("gc"):
        result["gc"] = ps["gc"]
    if ps.get("ping"):
        result["ping"] = ps["ping"]
    result["uptime"] = ps.get("uptime")
    result["player_count"] = _get(ps, "playerCount", "player_count")
    return result


def parse_profile(data: dict) -> Profile:
    """Parse a decoded spark report (dict) into a :class:`Profile`."""
    if not isinstance(data, dict):
        raise ValueError("spark data must be a JSON object")

    metadata = data.get("metadata", {}) or {}
    class_sources = _get(data, "classSources", "class_sources", default={}) or {}
    method_sources = _get(data, "methodSources", "method_sources", default={}) or {}
    threads_raw = data.get("threads") or []

    threads = [_parse_thread(t, class_sources, method_sources) for t in threads_raw]
    window_stats = _parse_windows(data)
    platform = _parse_platform(metadata)

    if threads_raw:
        source_type = "sampler"
    elif platform:
        source_type = "health"
    else:
        source_type = "unknown"

    return Profile(
        threads=threads,
        metadata=metadata,
        window_stats=window_stats,
        platform=platform,
        source_type=source_type,
        raw=data,
    )
