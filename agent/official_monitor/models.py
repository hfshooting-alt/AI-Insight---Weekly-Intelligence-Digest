from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


@dataclass
class SourceConfig:
    source_name: str
    source_type: str
    region: str
    official_domain: str
    landing_url: str
    allowed_domains: List[str]
    candidate_paths: List[str]
    parser_hint: str
    language: str
    priority: int
    exclude_url_patterns: List[str]
    notes: str = ""


@dataclass
class NormalizedArticle:
    article_id: str
    source_name: str
    source_type: str
    region: str
    company_or_firm_name: str
    title: str
    url: str
    canonical_url: str
    published_at: str
    collected_at: str
    author: str
    language: str
    page_type: str
    signal_type: str
    importance_score: float
    summary: str
    content_text: str
    tags: List[str] = field(default_factory=list)
    related_entities: List[str] = field(default_factory=list)
    content_hash: str = ""
    dedupe_key: str = ""
    normalized_title: str = ""
    cluster_features: Dict[str, Any] = field(default_factory=dict)
    topic_cluster_id: Optional[str] = None
    article_summary_zh: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TopicCluster:
    topic_cluster_id: str
    topic_title: str
    event_summary: str
    topic_keywords: List[str]
    strategic_signal: str
    article_count: int
    sources: List[str]
    cluster_confidence_score: float
    topic_priority_score: float
    supporting_articles: List[Dict[str, Any]]


@dataclass
class RunSummary:
    started_at: str
    finished_at: str
    lookback_days: int
    trusted_sources: int
    covered_sources: int
    fetched_articles: int
    kept_articles: int
    deduped_articles: int
    topic_clusters: int
    drop_reasons: Dict[str, int]
