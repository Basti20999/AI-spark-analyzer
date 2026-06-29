"""Deterministic analysis of a parsed spark profile.

This is the non-AI half: it computes the metrics that actually localize a lag
spike — self-time hot methods, per-plugin attribution, the single heaviest
call path, and which time-windows had the worst MSPT — and renders a compact,
token-budgeted summary for the AI layer to reason over.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator

from .models import Profile, StackNode, ThreadProfile, WindowStats


def iter_nodes(node: StackNode) -> Iterator[StackNode]:
    """Iteratively yield a node and all of its descendants."""
    stack = [node]
    while stack:
        n = stack.pop()
        yield n
        stack.extend(n.children)


def primary_thread(profile: Profile, name_filter: str | None = None) -> ThreadProfile | None:
    """Pick the thread to focus on.

    Defaults to the busiest "Server thread" (the Minecraft tick loop, where
    lag spikes live), or the busiest thread overall if none matches.
    """
    threads = profile.threads
    if not threads:
        return None
    if name_filter:
        matches = [t for t in threads if name_filter.lower() in t.name.lower()]
        if matches:
            return max(matches, key=lambda t: t.total_time)
    server = [t for t in threads if "server thread" in t.name.lower()]
    candidates = server or threads
    return max(candidates, key=lambda t: t.total_time)


def method_self_times(thread: ThreadProfile) -> dict[str, float]:
    """Sum self-time per unique method label across the whole thread."""
    agg: dict[str, float] = {}
    for root in thread.roots:
        for n in iter_nodes(root):
            agg[n.label] = agg.get(n.label, 0.0) + n.self_time
    return agg


def plugin_attribution(thread: ThreadProfile) -> list[tuple[str, float]]:
    """Sum self-time per attributed plugin/mod, descending."""
    agg: dict[str, float] = {}
    for root in thread.roots:
        for n in iter_nodes(root):
            if n.source:
                agg[n.source] = agg.get(n.source, 0.0) + n.self_time
    return sorted(agg.items(), key=lambda kv: kv[1], reverse=True)


def hottest_path(thread: ThreadProfile) -> list[StackNode]:
    """The single heaviest root-to-leaf path (follow the fattest child)."""
    if not thread.roots:
        return []
    node = max(thread.roots, key=lambda r: r.total_time)
    path = [node]
    while node.children:
        node = max(node.children, key=lambda c: c.total_time)
        path.append(node)
    return path


def lag_windows(profile: Profile, n: int = 5) -> list[WindowStats]:
    return sorted(profile.window_stats, key=lambda w: w.mspt_max, reverse=True)[:n]


def render_tree(
    node: StackNode,
    thread_total: float,
    *,
    min_pct: float = 1.0,
    max_depth: int = 14,
    depth: int = 0,
    lines: list[str] | None = None,
) -> list[str]:
    """Render a pruned call tree, dropping branches below ``min_pct``."""
    if lines is None:
        lines = []
    pct = (node.total_time / thread_total * 100) if thread_total else 0.0
    if depth > 0 and pct < min_pct:
        return lines
    indent = "  " * depth
    src = f"  «{node.source}»" if node.source else ""
    lines.append(
        f"{indent}{node.label} — {pct:.1f}% "
        f"(total {node.total_time:.0f}, self {node.self_time:.0f}){src}"
    )
    if depth < max_depth:
        for child in sorted(node.children, key=lambda c: c.total_time, reverse=True):
            render_tree(
                child,
                thread_total,
                min_pct=min_pct,
                max_depth=max_depth,
                depth=depth + 1,
                lines=lines,
            )
    return lines


@dataclass
class AnalysisResult:
    source_type: str
    primary_thread: str | None
    thread_total: float
    threads: list[tuple[str, float]] = field(default_factory=list)
    top_methods: list[tuple[str, float]] = field(default_factory=list)
    plugins: list[tuple[str, float]] = field(default_factory=list)
    hot_path: list[tuple[str, float, str | None]] = field(default_factory=list)
    lag_windows: list[WindowStats] = field(default_factory=list)
    tree_text: str = ""
    platform: dict = field(default_factory=dict)
    metadata_summary: dict = field(default_factory=dict)


def _metadata_summary(metadata: dict) -> dict:
    from .parser import _get

    pm = _get(metadata, "platformMetadata", "platform_metadata", default={}) or {}
    return {
        "platform": _get(pm, "name", default=None),
        "platform_version": _get(pm, "version", default=None),
        "minecraft_version": _get(pm, "minecraftVersion", "minecraft_version", default=None),
        "sampler_mode": _get(metadata, "samplerMode", "sampler_mode", default=None),
        "ticks": _get(metadata, "numberOfTicks", "number_of_ticks", default=None),
        "interval_us": _get(metadata, "interval", default=None),
        "comment": _get(metadata, "comment", default=None),
    }


def analyze(
    profile: Profile,
    *,
    top_n: int = 15,
    min_pct: float = 1.0,
    max_depth: int = 14,
    thread_filter: str | None = None,
) -> AnalysisResult:
    """Run the full deterministic analysis over a profile."""
    thread = primary_thread(profile, thread_filter)
    thread_total = thread.total_time if thread else 0.0

    top_methods: list[tuple[str, float]] = []
    plugins: list[tuple[str, float]] = []
    hot_path: list[tuple[str, float, str | None]] = []
    tree_text = ""

    if thread:
        top_methods = sorted(
            method_self_times(thread).items(), key=lambda kv: kv[1], reverse=True
        )[:top_n]
        plugins = plugin_attribution(thread)[:top_n]
        for node in hottest_path(thread):
            pct = (node.total_time / thread_total * 100) if thread_total else 0.0
            hot_path.append((node.label, pct, node.source))
        tree_lines: list[str] = []
        for root in sorted(thread.roots, key=lambda r: r.total_time, reverse=True):
            render_tree(root, thread_total, min_pct=min_pct, max_depth=max_depth, lines=tree_lines)
        tree_text = "\n".join(tree_lines)

    return AnalysisResult(
        source_type=profile.source_type,
        primary_thread=thread.name if thread else None,
        thread_total=thread_total,
        threads=sorted(
            ((t.name, t.total_time) for t in profile.threads),
            key=lambda kv: kv[1],
            reverse=True,
        ),
        top_methods=top_methods,
        plugins=plugins,
        hot_path=hot_path,
        lag_windows=lag_windows(profile),
        tree_text=tree_text,
        platform=profile.platform,
        metadata_summary=_metadata_summary(profile.metadata),
    )


def summarize_for_ai(result: AnalysisResult, *, tree_char_budget: int = 8000) -> str:
    """Build a compact, token-bounded text summary for the model."""
    out: list[str] = []

    meta = result.metadata_summary
    out.append("## Report metadata")
    for label, key in (
        ("Platform", "platform"),
        ("Platform version", "platform_version"),
        ("Minecraft version", "minecraft_version"),
        ("Profiler mode", "sampler_mode"),
        ("Ticks profiled", "ticks"),
        ("Sample interval (us)", "interval_us"),
        ("Comment", "comment"),
    ):
        val = meta.get(key)
        if val not in (None, ""):
            out.append(f"- {label}: {val}")
    out.append(f"- Profile type: {result.source_type}")

    if result.platform:
        out.append("\n## Health (server-wide)")
        tps = result.platform.get("tps") or {}
        if tps:
            out.append(
                f"- TPS: 1m={tps.get('last1m')} 5m={tps.get('last5m')} "
                f"15m={tps.get('last15m')} (target {tps.get('target')})"
            )
        mspt = result.platform.get("mspt") or {}
        if mspt:
            last1m = mspt.get("last1m") or {}
            out.append(
                f"- MSPT (1m): mean={last1m.get('mean')} median={last1m.get('median')} "
                f"max={last1m.get('max')} p95={last1m.get('percentile95')}"
            )

    if result.lag_windows:
        out.append("\n## Worst lag windows (by max MSPT)")
        out.append("window | ticks | tps | mspt_median | mspt_max")
        for w in result.lag_windows:
            out.append(
                f"{w.window} | {w.ticks} | {w.tps:.1f} | "
                f"{w.mspt_median:.0f} | {w.mspt_max:.0f}"
            )

    if result.threads:
        out.append("\n## Threads (by total sampled time)")
        for name, total in result.threads[:8]:
            out.append(f"- {name}: {total:.0f}")

    out.append(f"\n## Focus thread: {result.primary_thread} (total {result.thread_total:.0f})")

    if result.plugins:
        out.append("\n## Time attributed to plugins/mods (self-time)")
        for name, self_t in result.plugins:
            pct = (self_t / result.thread_total * 100) if result.thread_total else 0
            out.append(f"- {name}: {self_t:.0f} ({pct:.1f}%)")

    if result.top_methods:
        out.append("\n## Hottest methods (by self-time)")
        for label, self_t in result.top_methods:
            pct = (self_t / result.thread_total * 100) if result.thread_total else 0
            out.append(f"- {label}: {self_t:.0f} ({pct:.1f}%)")

    if result.hot_path:
        out.append("\n## Heaviest call path (root -> leaf)")
        for label, pct, source in result.hot_path:
            tag = f" «{source}»" if source else ""
            out.append(f"  {label} — {pct:.1f}%{tag}")

    if result.tree_text:
        tree = result.tree_text
        if len(tree) > tree_char_budget:
            tree = tree[:tree_char_budget] + "\n  ... (tree truncated)"
        out.append("\n## Pruned call tree of focus thread")
        out.append(tree)

    return "\n".join(out)


def analysis_to_dict(result: AnalysisResult) -> dict:
    """JSON-serializable view of the analysis."""
    return {
        "source_type": result.source_type,
        "primary_thread": result.primary_thread,
        "thread_total": result.thread_total,
        "threads": [{"name": n, "total": t} for n, t in result.threads],
        "top_methods": [{"method": m, "self_time": s} for m, s in result.top_methods],
        "plugins": [{"source": p, "self_time": s} for p, s in result.plugins],
        "hot_path": [
            {"method": m, "pct": p, "source": s} for m, p, s in result.hot_path
        ],
        "lag_windows": [
            {
                "window": w.window,
                "ticks": w.ticks,
                "tps": w.tps,
                "mspt_median": w.mspt_median,
                "mspt_max": w.mspt_max,
            }
            for w in result.lag_windows
        ],
        "platform": result.platform,
        "metadata": result.metadata_summary,
    }
