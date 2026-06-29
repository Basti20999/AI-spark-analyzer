"""Claude integration: turn the analysis summary into an expert diagnosis.

Uses the official Anthropic SDK with Claude Opus 4.8 and adaptive thinking.
The call streams (so large profiles don't hit request timeouts) and degrades
gracefully on older SDKs that don't accept ``thinking`` / ``output_config``.
"""

from __future__ import annotations

import os

DEFAULT_MODEL = "claude-opus-4-8"

SYSTEM_PROMPT = """\
You are an expert Minecraft server performance engineer who diagnoses lag \
spikes from spark profiler reports (spark by lucko).

Background you can rely on:
- spark's sampling profiler records, per thread, a call tree where each frame \
has a TOTAL time (frame + everything it called) and a SELF time (the frame \
alone). Self-time is where CPU is actually being spent.
- The "Server thread" is the Minecraft main tick loop. A tick should finish in \
under 50ms (20 TPS). Lag spikes are individual ticks that blow past that.
- Reports captured with `--only-ticks-over <ms>` contain ONLY samples from \
slow ticks, so whatever dominates is, by construction, the spike cause.
- Common spike causes: synchronous chunk generation/loading on the main \
thread, blocking I/O on the main thread (database queries, web/HTTP calls, \
file reads), heavy entity/tile-entity/redstone/hopper processing, expensive \
plugin event handlers run every tick, pathfinding, world saves, and GC pauses \
(visible as JVM/GC frames rather than plugin code).
- spark attributes frames to the plugin/mod that owns the class; that \
attribution is shown to you as «PluginName».

You are given a deterministic analysis (hot self-time methods, per-plugin \
attribution, the heaviest call path, worst lag windows, and a pruned call \
tree). Ground every claim in that data — cite the method names and \
percentages you were given. Do not invent frames, plugins, or numbers. When \
the evidence is ambiguous, say so and explain what additional capture (e.g. a \
longer profile, `--only-ticks-over`, or a heap dump) would disambiguate.

Respond in Markdown with exactly these sections:

### Verdict
One line: severity (low / moderate / severe) and the single most likely cause.

### Root cause analysis
2–5 short paragraphs explaining what the hot path and self-times show, in \
plain terms, including whether this looks main-thread-blocking, CPU-bound, or \
GC-related.

### Suspected plugins / subsystems
A short list. For each, cite the evidence (method + %) and how confident you \
are.

### Recommendations
Concrete, prioritized, actionable steps for a server admin or plugin dev. \
Prefer specific config/flags/code changes over generalities.

### Caveats
What the data can't tell you, and what to capture next if needed.

Be concise and technical. No filler."""


def has_api_key() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def build_prompt(summary_text: str) -> str:
    return (
        "Here is the deterministic analysis of a spark profiler report. "
        "Diagnose the lag spike(s).\n\n"
        f"{summary_text}\n"
    )


def _extract_text(message) -> str:
    parts = [
        block.text
        for block in message.content
        if getattr(block, "type", None) == "text"
    ]
    return "\n".join(parts).strip()


def run_analysis(
    summary_text: str,
    *,
    model: str = DEFAULT_MODEL,
    api_key: str | None = None,
    max_tokens: int = 8000,
) -> str:
    """Send the summary to Claude and return the Markdown diagnosis."""
    import anthropic

    client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
    base = dict(
        model=model,
        max_tokens=max_tokens,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": build_prompt(summary_text)}],
    )

    # Prefer adaptive thinking + high effort; fall back if the installed SDK or
    # the chosen model rejects those parameters.
    attempts = (
        {"thinking": {"type": "adaptive"}, "output_config": {"effort": "high"}},
        {},
    )
    last_error: Exception | None = None
    for extra in attempts:
        try:
            with client.messages.stream(**base, **extra) as stream:
                message = stream.get_final_message()
            return _extract_text(message)
        except TypeError as exc:  # SDK too old for these kwargs
            last_error = exc
        except anthropic.BadRequestError as exc:  # model rejects a parameter
            last_error = exc
    raise RuntimeError(f"Claude request failed: {last_error}")
