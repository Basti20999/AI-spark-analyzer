"""Render a human-readable Markdown report from the analysis (+ AI diagnosis)."""

from __future__ import annotations

from .analysis import AnalysisResult


def _pct(value: float, total: float) -> str:
    return f"{(value / total * 100):.1f}%" if total else "n/a"


def render(result: AnalysisResult, ai_text: str | None = None) -> str:
    lines: list[str] = ["# AI Spark Analyzer report", ""]

    meta = result.metadata_summary
    lines.append("## Overview")
    for label, key in (
        ("Platform", "platform"),
        ("Platform version", "platform_version"),
        ("Minecraft version", "minecraft_version"),
        ("Profiler mode", "sampler_mode"),
        ("Ticks profiled", "ticks"),
    ):
        val = meta.get(key)
        if val not in (None, ""):
            lines.append(f"- **{label}:** {val}")
    lines.append(f"- **Profile type:** {result.source_type}")
    if result.primary_thread:
        lines.append(f"- **Focus thread:** {result.primary_thread}")

    if result.platform.get("tps") or result.platform.get("mspt"):
        lines += ["", "## Server health"]
        tps = result.platform.get("tps") or {}
        if tps:
            lines.append(
                f"- **TPS:** 1m `{tps.get('last1m')}` · 5m `{tps.get('last5m')}` "
                f"· 15m `{tps.get('last15m')}` (target `{tps.get('target')}`)"
            )
        mspt = (result.platform.get("mspt") or {}).get("last1m") or {}
        if mspt:
            lines.append(
                f"- **MSPT (1m):** mean `{mspt.get('mean')}` · "
                f"median `{mspt.get('median')}` · max `{mspt.get('max')}` "
                f"· p95 `{mspt.get('percentile95')}`"
            )

    if result.lag_windows:
        lines += ["", "## Worst lag windows", "", "| window | ticks | TPS | MSPT median | MSPT max |", "| --- | --- | --- | --- | --- |"]
        for w in result.lag_windows:
            lines.append(
                f"| {w.window} | {w.ticks} | {w.tps:.1f} | "
                f"{w.mspt_median:.0f} | {w.mspt_max:.0f} |"
            )

    if result.plugins:
        lines += ["", "## Time by plugin / mod (self-time)", "", "| source | self-time | share |", "| --- | --- | --- |"]
        for name, self_t in result.plugins:
            lines.append(f"| {name} | {self_t:.0f} | {_pct(self_t, result.thread_total)} |")

    if result.top_methods:
        lines += ["", "## Hottest methods (self-time)", "", "| method | self-time | share |", "| --- | --- | --- |"]
        for label, self_t in result.top_methods:
            lines.append(f"| `{label}` | {self_t:.0f} | {_pct(self_t, result.thread_total)} |")

    if result.hot_path:
        lines += ["", "## Heaviest call path", "", "```"]
        for depth, (label, pct, source) in enumerate(result.hot_path):
            tag = f"  «{source}»" if source else ""
            lines.append(f"{'  ' * depth}{label} — {pct:.1f}%{tag}")
        lines.append("```")

    if result.tree_text:
        lines += ["", "## Pruned call tree", "", "```", result.tree_text, "```"]

    if ai_text:
        lines += ["", "---", "", "## AI diagnosis", "", ai_text]
    else:
        lines += [
            "",
            "---",
            "",
            "_AI diagnosis skipped. Set `ANTHROPIC_API_KEY` and re-run without "
            "`--no-ai` for an expert root-cause analysis._",
        ]

    return "\n".join(lines) + "\n"
