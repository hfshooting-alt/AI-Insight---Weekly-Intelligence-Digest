from __future__ import annotations

from typing import Dict, List

from .models import NormalizedArticle


def dedupe_articles(items: List[NormalizedArticle]) -> List[NormalizedArticle]:
    by_canonical: Dict[str, NormalizedArticle] = {}
    for it in items:
        prev = by_canonical.get(it.canonical_url)
        if not prev or it.importance_score > prev.importance_score:
            by_canonical[it.canonical_url] = it

    by_title: Dict[str, NormalizedArticle] = {}
    for it in by_canonical.values():
        prev = by_title.get(it.normalized_title)
        if not prev or it.importance_score > prev.importance_score:
            by_title[it.normalized_title] = it

    by_hash: Dict[str, NormalizedArticle] = {}
    for it in by_title.values():
        prev = by_hash.get(it.content_hash)
        if not prev or it.importance_score > prev.importance_score:
            by_hash[it.content_hash] = it
    return list(by_hash.values())
