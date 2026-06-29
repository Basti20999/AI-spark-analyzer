# AI Spark Analyzer

AI-powered root-cause analysis for **[spark](https://spark.lucko.me)** profiler
reports. Point it at a spark report and it pulls the call tree, computes where
the time really went (self-time, per-plugin attribution, the heaviest call
path, worst-MSPT windows), then has **Claude** read that evidence and tell you
what's causing your Minecraft server's lag spikes — and what to do about it.

It's built around the workflow in spark's own guide,
[Finding lag spikes](https://spark.lucko.me/docs/guides/Finding-lag-spikes):
capture the spike with `/spark profiler --only-ticks-over <ms>`, then feed the
report here for analysis.

```
spark report ──▶ fetch (JSON) ──▶ parse call tree ──▶ deterministic analysis ──▶ Claude ──▶ diagnosis
```

## Why

spark's viewer shows you the call tree, but reading a flame graph and working
out *which plugin is the problem and why* takes experience. This tool does the
mechanical part deterministically (so the numbers are exact, not hallucinated)
and uses Claude only for the judgement part — interpreting the hot path,
naming the likely cause, and giving concrete, prioritized fixes. Every claim
the model makes is grounded in the computed metrics it's handed.

## How it works

1. **Fetch** — resolves a spark code / URL / local file to JSON via spark's
   official endpoint `https://spark.lucko.me/<code>?raw=1&full=true` (which
   decodes spark's protobuf to JSON for us). See
   [Raw spark data](https://spark.lucko.me/docs/misc/Raw-spark-data).
2. **Parse** — rebuilds each thread's call tree, handling both the flat
   index-referenced format and the legacy nested format, and resolves spark's
   class/method → plugin source maps.
3. **Analyze** (no AI) — self-time per method, time attributed per plugin/mod,
   the single heaviest root→leaf path, the worst lag windows by max MSPT, and a
   pruned call tree.
4. **Diagnose** (Claude) — a compact, token-budgeted summary of the above goes
   to Claude Opus 4.8 (adaptive thinking) for an expert verdict, root-cause
   analysis, suspect list, and recommendations.

## Install

Requires Python 3.10+. The core tool has **no third-party dependencies** — the
fetch/parse/analyze pipeline uses only the standard library.

```bash
pip install -e .
```

## Getting the AI diagnosis

The deterministic analysis always works on its own. For the AI diagnosis you
have three options — pick whichever matches what you have:

### Option A — Claude Pro / Max subscription (no API key) ✅ recommended

If you already pay for Claude (Pro or Max), you can use that subscription
directly — **no API key and no per-call API billing.** The analyzer drives the
[Claude Code CLI](https://claude.com/claude-code) under the hood, which signs in
with your subscription.

```bash
# one-time setup
npm install -g @anthropic-ai/claude-code   # install the Claude Code CLI
claude login                               # sign in with your Pro/Max account

# then just run the analyzer (auto-detects the CLI)
spark-analyzer uksGhFmkWd
# or force it explicitly:
spark-analyzer uksGhFmkWd --backend cli
```

### Option B — Anthropic API key (pay-as-you-go)

Best for servers / CI. Install the API extra and set a key:

```bash
pip install -e ".[api]"          # adds the Anthropic SDK
export ANTHROPIC_API_KEY=sk-ant-...   # or copy .env.example to .env
spark-analyzer uksGhFmkWd --backend api
```

### Option C — copy/paste into claude.ai (any plan, even free)

No CLI, no key — just print a ready-made prompt and paste it into
[claude.ai](https://claude.ai):

```bash
spark-analyzer uksGhFmkWd --print-prompt    # prints the deterministic analysis
                                            # wrapped in an expert prompt
```

> By default the backend is `auto`: it uses the API if `ANTHROPIC_API_KEY` is
> set, otherwise the Claude Code CLI (your subscription) if it's installed.

## Usage

```bash
# By spark code
spark-analyzer uksGhFmkWd

# By viewer URL
spark-analyzer https://spark.lucko.me/uksGhFmkWd

# From a local JSON export (download <code>?raw=1&full=true)
spark-analyzer ./myreport.json

# Without installing the console script
python -m spark_analyzer uksGhFmkWd
```

### Options

| Flag | Description |
| --- | --- |
| `--backend {auto,cli,api}` | How to reach Claude. `cli` = your Pro/Max subscription via the Claude Code CLI; `api` = `ANTHROPIC_API_KEY`; `auto` (default) prefers a key if set, else the CLI. |
| `--print-prompt` | Print a ready-to-paste prompt for claude.ai and exit (works with any plan, even free). |
| `--no-ai` | Skip Claude; print the deterministic analysis only (no account needed). |
| `--json` | Emit the analysis as JSON instead of a Markdown report. |
| `-o, --output PATH` | Write the Markdown report to a file. |
| `--thread NAME` | Focus on a thread whose name contains `NAME` (default: the busiest "Server thread"). |
| `--top N` | Number of hot methods / plugins to list (default 15). |
| `--min-pct P` | Prune call-tree branches below `P`% (default 1.0). |
| `--max-depth D` | Max call-tree depth to render (default 14). |
| `--model ID` | Claude model to use (default `claude-opus-4-8`). |
| `--timeout S` | Network timeout in seconds (default 30). |

### Capturing a good report

For lag spikes specifically, capture only the slow ticks so the cause isn't
averaged away (per spark's guide):

```
/spark profiler --only-ticks-over 50 --timeout 120
```

Then run the analyzer on the resulting report link.

## Example output

```
## Verdict
Severe — a plugin is doing synchronous chunk scanning on the main thread every tick.

## Suspected plugins / subsystems
- LaggyPlugin — `scanLoadedChunks` is 70% of focus-thread self-time, called
  from its per-tick handler. High confidence.
...
```

(See `examples/usage.md` for a full walkthrough against the bundled fixture.)

## Development

```bash
python -m unittest discover -s tests -t tests
# or, if you have pytest:
pytest
```

The fetcher and parser use only the standard library, so the test suite runs
offline with no API key.

## Notes & limitations

- Uses the **JSON** endpoint, so it does not need protobuf tooling. Raw
  `.sparkprofile` (protobuf) files are not parsed directly — export JSON with
  `?raw=1&full=true` instead.
- Time values are spark's sampled wall-time accumulators; the analysis leans on
  **percentages and self-time**, which are robust regardless of units.
- Health/heap reports are recognized but the deep analysis targets **sampler**
  (profiler) reports, which is where lag-spike call data lives.

## Credits

Built on the data and documentation of **[spark](https://spark.lucko.me)** by
lucko. AI diagnosis powered by **[Claude](https://claude.com)** — via your Claude
Pro/Max subscription (through the [Claude Code CLI](https://claude.com/claude-code))
or the [Anthropic API](https://docs.claude.com). Not affiliated with the spark
project.
