from __future__ import annotations

import datetime as dt
import json
from collections import defaultdict
from typing import Dict, List, Tuple

from .cluster import build_topic_meta, cluster_articles
from .dates import now_utc, within_last_days
from .dedupe import dedupe_articles
from .discover import discover_article_links, discover_listing_urls
from .extract import extract_article
from .fetch import fetch_url
from .models import NormalizedArticle, RunSummary, TopicCluster
from .render import source_link_markdown
from .sources import load_sources
from .summarize import infer_entities, summarize_article_zh, summarize_cluster_event_zh


def _log(event: str, **kwargs) -> None:
    payload = {"event": event, **kwargs}
    print(json.dumps(payload, ensure_ascii=False))


def run_pipeline(lookback_days: int = 7, max_articles_per_source: int = 35) -> Tuple[RunSummary, List[NormalizedArticle], List[TopicCluster]]:
    started = now_utc()
    sources = load_sources()
    drop_reasons = defaultdict(int)
    raw_articles: List[NormalizedArticle] = []
    article_idx = 1
    covered_sources = 0

    for s in sources:
        _log("source_fetch_start", source=s.source_name, landing=s.landing_url)
        listing_urls = discover_listing_urls(s)
        source_candidates = []
        for lu in listing_urls[:6]:
            html = fetch_url(lu)
            if not html:
                continue
            links = discover_article_links(html, lu, s)
            source_candidates.extend(links)
            _log("listing_parsed", source=s.source_name, listing=lu, candidate_links=len(links))

        uniq_candidates = list(dict.fromkeys(source_candidates))[: max_articles_per_source]
        kept_here = 0
        for u in uniq_candidates:
            html = fetch_url(u)
            if not html:
                drop_reasons["empty_or_inaccessible"] += 1
                continue
            art = extract_article(html, u, s, article_idx)
            if not art:
                drop_reasons["not_real_article_or_bad_parse"] += 1
                continue
            pub_dt = dt.datetime.fromisoformat(art.published_at.replace("Z", "+00:00"))
            if not within_last_days(pub_dt, lookback_days):
                drop_reasons["outside_7d_window"] += 1
                continue
            if not art.content_text:
                drop_reasons["empty_content"] += 1
                continue

            art.related_entities = infer_entities(art)
            raw_articles.append(art)
            article_idx += 1
            kept_here += 1
        if kept_here > 0:
            covered_sources += 1
        _log("source_fetch_end", source=s.source_name, kept=kept_here, candidates=len(uniq_candidates))

    deduped = dedupe_articles(raw_articles)
    _log("dedupe_complete", before=len(raw_articles), after=len(deduped))

    clusters_raw = cluster_articles(deduped)
    _log("cluster_counts", clusters=len(clusters_raw))

    topic_clusters: List[TopicCluster] = []
    for idx, cl in enumerate(clusters_raw, start=1):
        meta = build_topic_meta(cl, idx)
        event_summary, strategic_signal = summarize_cluster_event_zh(cl, meta["topic_keywords"])
        supporting = []
        for a in sorted(cl, key=lambda x: x.importance_score, reverse=True):
            a.topic_cluster_id = meta["topic_cluster_id"]
            a.article_summary_zh = summarize_article_zh(a)
            link = source_link_markdown(a.company_or_firm_name, a.url)
            supporting.append(
                {
                    "article_id": a.article_id,
                    "title": a.title,
                    "institution_name": a.company_or_firm_name,
                    "published_at": a.published_at,
                    "article_summary_zh": a.article_summary_zh,
                    "source_link_markdown": link,
                    "url": a.url,
                }
            )
        topic_clusters.append(
            TopicCluster(
                topic_cluster_id=meta["topic_cluster_id"],
                topic_title=meta["topic_title"],
                event_summary=event_summary,
                topic_keywords=meta["topic_keywords"][:8],
                strategic_signal=strategic_signal,
                article_count=len(cl),
                sources=sorted(list({a.company_or_firm_name for a in cl})),
                cluster_confidence_score=meta["cluster_confidence_score"],
                topic_priority_score=meta["topic_priority_score"],
                supporting_articles=supporting,
            )
        )

    finished = now_utc()
    summary = RunSummary(
        started_at=started.isoformat(),
        finished_at=finished.isoformat(),
        lookback_days=lookback_days,
        trusted_sources=len(sources),
        covered_sources=covered_sources,
        fetched_articles=len(raw_articles),
        kept_articles=len(raw_articles),
        deduped_articles=len(deduped),
        topic_clusters=len(topic_clusters),
        drop_reasons=dict(drop_reasons),
    )
    _log("topic_generation_complete", topics=len(topic_clusters))
    _log("final_report_summary", deduped=len(deduped), topics=len(topic_clusters))
    return summary, deduped, topic_clusters


def sample_run_data() -> Tuple[RunSummary, List[NormalizedArticle], List[TopicCluster]]:
    from .models import NormalizedArticle
    now = now_utc().isoformat()
    arts = [
        NormalizedArticle(article_id="article_0001", source_name="OpenAI Newsroom", source_type="ai_company", region="global", company_or_firm_name="OpenAI", title="OpenAI releases enterprise agent toolkit", url="https://openai.com/news/agent-toolkit", canonical_url="https://openai.com/news/agent-toolkit", published_at=now, collected_at=now, author="OpenAI", language="en", page_type="article", signal_type="product_release", importance_score=88, summary="", content_text="OpenAI announced enterprise agent toolkit for workflows", tags=["agent","api","enterprise"], related_entities=["OpenAI"], content_hash="h1", dedupe_key="d1", normalized_title="openai releases enterprise agent toolkit"),
        NormalizedArticle(article_id="article_0002", source_name="Anthropic Newsroom", source_type="ai_company", region="global", company_or_firm_name="Anthropic", title="Anthropic launches new API controls for enterprise AI", url="https://www.anthropic.com/news/api-controls", canonical_url="https://www.anthropic.com/news/api-controls", published_at=now, collected_at=now, author="Anthropic", language="en", page_type="article", signal_type="product_release", importance_score=82, summary="", content_text="Anthropic launched enterprise controls and governance", tags=["api","enterprise"], related_entities=["Anthropic"], content_hash="h2", dedupe_key="d2", normalized_title="anthropic launches new api controls for enterprise ai"),
        NormalizedArticle(article_id="article_0003", source_name="a16z News & Content", source_type="investment_firm", region="global", company_or_firm_name="a16z", title="Why AI infrastructure investment is accelerating", url="https://a16z.com/news-content/ai-infra-investment", canonical_url="https://a16z.com/news-content/ai-infra-investment", published_at=now, collected_at=now, author="a16z", language="en", page_type="article", signal_type="investment_signal", importance_score=76, summary="", content_text="a16z discusses compute and data-layer investment thesis", tags=["investment","compute","cloud"], related_entities=["a16z"], content_hash="h3", dedupe_key="d3", normalized_title="why ai infrastructure investment is accelerating"),
    ]
    ded = dedupe_articles(arts)
    clusters_raw = cluster_articles(ded)
    from .cluster import build_topic_meta
    from .summarize import summarize_article_zh, summarize_cluster_event_zh
    topic_clusters = []
    for idx, cl in enumerate(clusters_raw, 1):
        m = build_topic_meta(cl, idx)
        ev, sig = summarize_cluster_event_zh(cl, m["topic_keywords"])
        sup=[]
        for a in cl:
            a.topic_cluster_id=m["topic_cluster_id"]
            a.article_summary_zh=summarize_article_zh(a)
            sup.append({"article_id":a.article_id,"title":a.title,"institution_name":a.company_or_firm_name,"published_at":a.published_at,"article_summary_zh":a.article_summary_zh,"source_link_markdown":source_link_markdown(a.company_or_firm_name,a.url),"url":a.url})
        topic_clusters.append(TopicCluster(topic_cluster_id=m["topic_cluster_id"],topic_title=m["topic_title"],event_summary=ev,topic_keywords=m["topic_keywords"],strategic_signal=sig,article_count=len(cl),sources=sorted(list({a.company_or_firm_name for a in cl})),cluster_confidence_score=m["cluster_confidence_score"],topic_priority_score=m["topic_priority_score"],supporting_articles=sup))
    summary=RunSummary(started_at=now,finished_at=now,lookback_days=7,trusted_sources=35,covered_sources=3,fetched_articles=3,kept_articles=3,deduped_articles=len(ded),topic_clusters=len(topic_clusters),drop_reasons={})
    return summary,ded,topic_clusters
