from __future__ import annotations

import argparse
import json
from pathlib import Path

from .pipeline import run_pipeline, sample_run_data
from .render import render_json, render_markdown


def main() -> None:
    parser = argparse.ArgumentParser(description="Official-source monitor and topic summarizer")
    parser.add_argument("--lookback-days", type=int, default=7)
    parser.add_argument("--json-out", default="agent/official_monitor_output.json")
    parser.add_argument("--md-out", default="agent/official_monitor_report.md")
    parser.add_argument("--sample", action="store_true", help="Run with built-in sample data")
    args = parser.parse_args()

    if args.sample:
        summary, articles, clusters = sample_run_data()
    else:
        summary, articles, clusters = run_pipeline(lookback_days=args.lookback_days)

    out_json = render_json(summary, articles, clusters)
    out_md = render_markdown(summary, clusters)

    Path(args.json_out).write_text(json.dumps(out_json, ensure_ascii=False, indent=2), encoding="utf-8")
    Path(args.md_out).write_text(out_md, encoding="utf-8")

    print(f"[OK] JSON written: {args.json_out}")
    print(f"[OK] Markdown written: {args.md_out}")
    print(f"[OK] topics={summary.topic_clusters}, deduped_articles={summary.deduped_articles}")


if __name__ == "__main__":
    main()
