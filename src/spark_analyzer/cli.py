"""Command-line entry point for the AI Spark Analyzer."""

from __future__ import annotations

import argparse
import json
import sys

from . import __version__
from .ai import DEFAULT_MODEL, has_api_key, run_analysis
from .analysis import analysis_to_dict, analyze, summarize_for_ai
from .fetcher import FetchError, fetch
from .parser import parse_profile
from .report import render


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="spark-analyzer",
        description=(
            "Analyze a spark profiler report and use Claude to diagnose lag "
            "spikes. TARGET is a spark code (e.g. uksGhFmkWd), a viewer URL, "
            "or a local JSON export (?raw=1&full=true)."
        ),
    )
    parser.add_argument("target", help="spark code, viewer URL, or local .json file")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Claude model (default: {DEFAULT_MODEL})")
    parser.add_argument("--no-ai", action="store_true", help="skip the Claude call; print deterministic analysis only")
    parser.add_argument("--output", "-o", metavar="PATH", help="write the Markdown report to a file")
    parser.add_argument("--json", action="store_true", help="print the analysis as JSON instead of a report")
    parser.add_argument("--thread", metavar="NAME", help="focus on a thread whose name contains NAME")
    parser.add_argument("--top", type=int, default=15, help="number of hot methods/plugins to list (default: 15)")
    parser.add_argument("--min-pct", type=float, default=1.0, help="prune call-tree branches below this %% (default: 1.0)")
    parser.add_argument("--max-depth", type=int, default=14, help="max call-tree depth to render (default: 14)")
    parser.add_argument("--timeout", type=float, default=30.0, help="network timeout in seconds (default: 30)")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    # Stack traces can be deep; give the recursive parser/renderer headroom.
    sys.setrecursionlimit(max(sys.getrecursionlimit(), 20000))

    try:
        data = fetch(args.target, timeout=args.timeout)
    except FetchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    profile = parse_profile(data)
    if profile.source_type == "unknown":
        print(
            "error: this does not look like a spark sampler or health report.",
            file=sys.stderr,
        )
        return 2

    result = analyze(
        profile,
        top_n=args.top,
        min_pct=args.min_pct,
        max_depth=args.max_depth,
        thread_filter=args.thread,
    )

    if args.json:
        print(json.dumps(analysis_to_dict(result), indent=2))
        return 0

    ai_text: str | None = None
    if not args.no_ai:
        if not has_api_key():
            print(
                "note: ANTHROPIC_API_KEY not set — skipping AI diagnosis. "
                "Set it (or pass --no-ai) to silence this.",
                file=sys.stderr,
            )
        else:
            try:
                summary = summarize_for_ai(result)
                ai_text = run_analysis(summary, model=args.model)
            except Exception as exc:  # network / API / SDK errors shouldn't lose the report
                print(f"warning: AI diagnosis failed ({exc})", file=sys.stderr)

    report = render(result, ai_text)

    if args.output:
        try:
            with open(args.output, "w", encoding="utf-8") as fh:
                fh.write(report)
        except OSError as exc:
            print(f"error: could not write {args.output}: {exc}", file=sys.stderr)
            return 2
        print(f"wrote {args.output}")
    else:
        print(report)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
