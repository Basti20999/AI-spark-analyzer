# Walkthrough

This walks through analyzing the bundled synthetic fixture
(`tests/fixtures/sample_sampler.json`), which models a server thread where a
plugin scans loaded chunks every tick.

## Deterministic analysis (no API key)

```bash
python -m spark_analyzer tests/fixtures/sample_sampler.json --no-ai
```

This prints:

- an **overview** (platform, MC version, profiler mode),
- **server health** (TPS 14.2/1m, MSPT max 412ms),
- the **worst lag windows** by max MSPT,
- **time by plugin** — `LaggyPlugin` at 70% of focus-thread self-time,
- the **hottest methods** — `scanLoadedChunks` dominates,
- the **heaviest call path** `tick → onServerTick → scanLoadedChunks`,
- a **pruned call tree**.

## JSON output

For piping into other tooling:

```bash
python -m spark_analyzer tests/fixtures/sample_sampler.json --json | jq '.plugins'
```

```json
[
  { "source": "LaggyPlugin", "self_time": 700.0 }
]
```

## Full AI diagnosis

### With a Claude Pro/Max subscription (no API key)

Install the [Claude Code CLI](https://claude.com/claude-code), sign in once
with `claude login`, then let the analyzer use your subscription:

```bash
python -m spark_analyzer tests/fixtures/sample_sampler.json --backend cli -o report.md
```

### With an Anthropic API key

```bash
pip install -e ".[api]"
export ANTHROPIC_API_KEY=sk-ant-...
python -m spark_analyzer tests/fixtures/sample_sampler.json --backend api -o report.md
```

### No account? Paste it into claude.ai

```bash
python -m spark_analyzer tests/fixtures/sample_sampler.json --print-prompt
```

Copy the output into [claude.ai](https://claude.ai) and Claude will reply with
the diagnosis.

Either way the report ends with an **AI diagnosis** section: a verdict,
root-cause analysis, the suspect plugin list (with the percentages cited as
evidence), and prioritized recommendations.

## Against a real report

1. In-game, capture a spike-only profile:
   ```
   /spark profiler --only-ticks-over 50 --timeout 120
   ```
2. Stop it / let it finish; spark prints a viewer link like
   `https://spark.lucko.me/uksGhFmkWd`.
3. Analyze it:
   ```bash
   spark-analyzer https://spark.lucko.me/uksGhFmkWd
   ```
