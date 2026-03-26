"""Append-only run metrics persistence.

After each weekly report run, call ``record_run()`` to write a single
JSON line to ``papers/run_history.jsonl``.  This provides observability
for long-term trend tracking without any external database.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
from typing import Any, Dict, List, Optional


HISTORY_DIR = pathlib.Path(os.environ.get("PAPERS_DIR", "papers"))


def _history_path() -> pathlib.Path:
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    return HISTORY_DIR / "run_history.jsonl"


def record_run(
    *,
    # ── Paper digest metrics ──
    papers_fetched: int = 0,
    papers_after_filter: int = 0,
    top3_titles: Optional[List[str]] = None,
    top3_early_scores: Optional[List[int]] = None,
    fulltext_hit_rate: float = 0.0,
    abstract_fallback_count: int = 0,
    pdf_downloaded: int = 0,
    # ── Official monitor metrics ──
    signal_articles_fetched: int = 0,
    signal_articles_deduped: int = 0,
    signal_articles_kept: int = 0,
    signal_clusters: int = 0,
    signal_drop_reasons: Optional[Dict[str, int]] = None,
    # ── Reflection (self-evaluation) ──
    reflection: Optional[Dict[str, Any]] = None,
    # ── Extra ──
    extra: Optional[Dict[str, Any]] = None,
) -> pathlib.Path:
    """Append one run record to ``run_history.jsonl``."""
    record = {
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
        "paper_digest": {
            "fetched": papers_fetched,
            "after_filter": papers_after_filter,
            "top3_titles": top3_titles or [],
            "top3_early_scores": top3_early_scores or [],
            "fulltext_hit_rate": round(fulltext_hit_rate, 3),
            "abstract_fallback": abstract_fallback_count,
            "pdf_downloaded": pdf_downloaded,
        },
        "official_monitor": {
            "fetched": signal_articles_fetched,
            "deduped": signal_articles_deduped,
            "kept": signal_articles_kept,
            "clusters": signal_clusters,
            "drop_reasons": signal_drop_reasons or {},
        },
    }
    if reflection:
        record["reflection"] = reflection
    if extra:
        record["extra"] = extra

    path = _history_path()
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"[HISTORY] run metrics appended to {path}")
    return path


def load_recent_runs(n: int = 10) -> List[Dict[str, Any]]:
    """Load the last *n* run records for trend analysis."""
    path = _history_path()
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    records = []
    for ln in lines[-n:]:
        try:
            records.append(json.loads(ln))
        except json.JSONDecodeError:
            continue
    return records
