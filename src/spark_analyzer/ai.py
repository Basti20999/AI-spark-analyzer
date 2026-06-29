"""Claude integration: turn the analysis summary into an expert diagnosis.

Three ways to get the AI diagnosis, in order of "no extra setup required":

* **CLI backend** — shells out to the Claude Code CLI (``claude -p``). This uses
  your Claude **Pro / Max subscription** login, so no API key (and no
  pay-as-you-go API billing) is needed. Just install Claude Code and run
  ``claude login`` once.
* **API backend** — the official Anthropic SDK with an ``ANTHROPIC_API_KEY``.
  Best for automation / CI. Streams so large profiles don't hit timeouts and
  degrades gracefully on older SDKs that don't accept ``thinking`` /
  ``output_config``.
* **Manual** — ``build_manual_prompt`` emits a ready-to-paste prompt you can
  drop straight into https://claude.ai (works with *any* plan, even free).
"""

from __future__ import annotations

import os
import shutil
import subprocess

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


def has_claude_cli(cli_path: str = "claude") -> bool:
    """True if the Claude Code CLI is on PATH (usable with a Pro/Max plan)."""
    return shutil.which(cli_path) is not None


def choose_backend(requested: str = "auto", *, cli_path: str = "claude") -> str:
    """Resolve the AI backend to use.

    ``"auto"`` prefers an explicit API key (preserves prior behaviour for API
    users) and otherwise falls back to the Claude Code CLI / subscription.
    Returns one of ``"api"``, ``"cli"``, or ``"none"``.
    """
    if requested in ("api", "cli"):
        return requested
    if has_api_key():
        return "api"
    if has_claude_cli(cli_path):
        return "cli"
    return "none"


def build_prompt(summary_text: str) -> str:
    return (
        "Here is the deterministic analysis of a spark profiler report. "
        "Diagnose the lag spike(s).\n\n"
        f"{summary_text}\n"
    )


def build_manual_prompt(summary_text: str) -> str:
    """A single self-contained prompt to paste into claude.ai (any plan)."""
    return (
        f"{SYSTEM_PROMPT}\n\n"
        "---\n\n"
        f"{build_prompt(summary_text)}"
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
    """Send the summary to Claude via the Anthropic API and return the diagnosis."""
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


def run_analysis_cli(
    summary_text: str,
    *,
    model: str = DEFAULT_MODEL,
    cli_path: str = "claude",
    timeout: float = 600.0,
    use_subscription: bool = True,
) -> str:
    """Run the diagnosis through the Claude Code CLI (Pro/Max subscription).

    Drives ``claude --print`` in a hermetic, single-shot configuration: our
    analysis system prompt replaces the default agentic one, all tools are
    disabled (we only want a text answer), and ``--safe-mode`` skips the user's
    local hooks / plugins / MCP / CLAUDE.md so nothing interferes.

    With ``use_subscription`` (the default) any API-key environment variables
    are stripped from the child process so the CLI authenticates with the
    logged-in subscription rather than billing the API.
    """
    if not has_claude_cli(cli_path):
        raise RuntimeError(
            "Claude Code CLI not found. Install it (https://claude.com/claude-code) "
            "and run `claude login` to use your Pro/Max subscription, set "
            "ANTHROPIC_API_KEY for the API, or re-run with --print-prompt."
        )

    cmd = [
        cli_path,
        "--print",
        "--model", model,
        "--system-prompt", SYSTEM_PROMPT,
        "--tools", "",
        "--safe-mode",
    ]

    env = dict(os.environ)
    if use_subscription:
        env.pop("ANTHROPIC_API_KEY", None)
        env.pop("ANTHROPIC_AUTH_TOKEN", None)

    try:
        proc = subprocess.run(
            cmd,
            input=build_prompt(summary_text),
            text=True,
            capture_output=True,
            timeout=timeout,
            env=env,
        )
    except FileNotFoundError as exc:  # CLI vanished between check and run
        raise RuntimeError(f"could not launch Claude CLI ({cli_path!r}): {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Claude CLI timed out after {timeout:.0f}s") from exc

    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        hint = ""
        if "login" in detail.lower() or "auth" in detail.lower() or not detail:
            hint = " — run `claude login` to sign in with your Pro/Max subscription."
        raise RuntimeError(
            f"Claude CLI failed (exit {proc.returncode}){hint}\n{detail}".rstrip()
        )

    out = proc.stdout.strip()
    if not out:
        raise RuntimeError("Claude CLI returned no output.")
    return out
