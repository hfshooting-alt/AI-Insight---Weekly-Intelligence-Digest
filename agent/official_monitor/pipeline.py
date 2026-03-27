from __future__ import annotations

import datetime as dt
import json
import logging
import re
from collections import defaultdict, Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)

from .cluster import build_topic_meta, cluster_articles
from .dates import now_utc, within_last_days
from .dedupe import dedupe_articles
from .discover import discover_article_links, discover_listing_urls
from .extract import extract_article, extract_rss_articles
from .fetch import fetch_url
from .models import NormalizedArticle, RunSummary, TopicCluster
from .render import source_link_markdown
from .sources import load_sources
from .summarize import (
    infer_entities,
    summarize_article_zh,
    summarize_article_with_llm,
    summarize_cluster_event_zh,
    summarize_with_llm,
    summarize_cluster_bundle_with_llm,
)
from .export import export_raw_articles_excel

import sys as _sys
_sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from config import cfg


def _log(event: str, **kwargs) -> None:
    payload = {"event": event, **kwargs}
    print(json.dumps(payload, ensure_ascii=False))



def _passes_signal_gate(article: NormalizedArticle) -> bool:
    """Lightweight gate: only reject obvious noise (maintenance, changelogs, career pages).

    We intentionally keep the filter loose — the goal is to capture a broad
    range of content including podcasts, deep-dives, research, product updates,
    and technical blog posts, not just hard-news announcements.
    """
    text = f"{article.title} {(article.content_text or '')[:1600]}".lower()
    noise_patterns = [
        "bug fix", "bugfix", "patch release", "minor update", "known issues",
        "changelog", "maintenance", "status update", "incident report",
        "cookie policy", "terms of service", "privacy policy",
        "修复", "补丁", "已知问题", "维护更新", "服务条款",
    ]
    return not any(k in text for k in noise_patterns)




FUNDING_AMOUNT_PATTERNS = [
    r"\$\s?([0-9]+(?:\.[0-9]+)?)\s?([mb]illion|[mk]?)",
    r"([0-9]+(?:\.[0-9]+)?)\s?(million|billion)\s?(usd|dollars)?",
    r"(\d+(?:\.\d+)?)\s?(亿|万)\s?(美元|人民币|美金|元)",
]

SECTOR_HINTS = [
    "agent", "inference", "ai infra", "data infra", "robotics", "autonomous driving", "chip", "gpu", "foundation model",
    "智能体", "推理", "数据基础设施", "机器人", "自动驾驶", "芯片", "算力", "大模型",
]


def _extract_funding_amount(text: str) -> str:
    t = text or ""
    for pat in FUNDING_AMOUNT_PATTERNS:
        m = re.search(pat, t, flags=re.I)
        if m:
            return m.group(0).strip()
    return "未披露"


def _extract_sector(text: str) -> str:
    low = (text or '').lower()
    hits = [k for k in SECTOR_HINTS if k.lower() in low]
    if not hits:
        return "未明确赛道"
    return "、".join(list(dict.fromkeys(hits))[:3])


def _extract_company_name(article: NormalizedArticle) -> str:
    title = article.title or ""
    m = re.search(r"([A-Z][A-Za-z0-9\-\.]{1,30})\s+(raises|raised|announces|acquires|appoints)", title)
    if m:
        return m.group(1)
    return article.company_or_firm_name or "未披露"


def _passes_role_specific_gate(article: NormalizedArticle) -> bool:
    """Lightweight content-type filter.

    We keep almost everything — the goal is to surface podcasts, tech deep-dives,
    product releases, research papers, and long-form content. Only drop content
    that is clearly not substantive (empty pages, career listings, etc.).
    """
    txt = f"{article.title} {(article.content_text or '')[:1600]}".lower()
    title_low = (article.title or '').lower()

    # Only reject truly irrelevant content
    junk_patterns = [
        "cookie", "privacy policy", "terms of use", "404", "page not found",
        "unsubscribe", "job opening", "career", "we are hiring",
    ]
    if any(k in title_low for k in junk_patterns):
        return False

    # Reject if content is too thin to be useful
    content_len = len((article.content_text or '').strip())
    if content_len < 100 and not (article.summary or '').strip():
        return False

    return True


def _build_precluster_summary(article: NormalizedArticle) -> str:
    txt = f"{article.title} {(article.content_text or '')[:1200]}".lower()
    raw = f"{article.title} {(article.content_text or '')[:2200]}"
    facets = []
    if any(k in txt for k in ["agent", "智能体", "assistant"]):
        facets.append("agent")
    if any(k in txt for k in ["api", "platform", "sdk", "开发者平台"]):
        facets.append("platform")
    if any(k in txt for k in ["gpu", "compute", "cloud", "算力", "芯片"]):
        facets.append("compute")
    if any(k in txt for k in ["funding", "financing", "investment", "融资", "投资", "并购", "收购"]):
        facets.append("capital")
    if any(k in txt for k in ["partnership", "collaboration", "合作", "生态"]):
        facets.append("ecosystem")
    if any(k in txt for k in ["robot", "robotics", "具身", "机器人"]):
        facets.append("robotics")
    if any(k in txt for k in ["enterprise", "production", "deployment", "企业", "落地", "部署"]):
        facets.append("enterprise")

    sig = (article.signal_type or 'event').lower()
    lead = f"{article.company_or_firm_name} {sig}"
    if (article.source_type or '').strip().lower() == 'investment_firm':
        company = _extract_company_name(article)
        amount = _extract_funding_amount(raw)
        sector = _extract_sector(raw)
        lead = f"{article.company_or_firm_name} capital_event target={company} amount={amount} sector={sector}"
    elif facets:
        lead += " " + " ".join(dict.fromkeys(facets))
    return lead.strip()


TOKEN_HINTS = {
    "agent", "api", "enterprise", "reasoning", "multimodal", "inference", "gpu", "compute", "cloud", "robotics",
    "融资", "投资", "并购", "合作", "推理", "多模态", "算力", "芯片", "平台", "发布",
}


def _article_tokens(article: NormalizedArticle) -> set[str]:
    txt = f"{article.title} {(article.content_text or '')[:1200]}".lower()
    toks = {t for t in TOKEN_HINTS if t in txt}
    toks.update({(x or '').strip().lower() for x in (article.tags or []) if (x or '').strip()})
    sig = (article.signal_type or '').strip().lower()
    if sig:
        toks.add(f"sig:{sig}")
    return toks


def _article_sim(a: NormalizedArticle, b: NormalizedArticle) -> float:
    ta, tb = _article_tokens(a), _article_tokens(b)
    inter = len(ta & tb)
    union = len(ta | tb) or 1
    return inter / union


def _cluster_signature(cluster: List[NormalizedArticle]) -> set[str]:
    c = Counter()
    for a in cluster:
        for t in _article_tokens(a):
            c[t] += 1
    return {k for k, v in c.items() if v >= 2}


def _cluster_sim(c1: List[NormalizedArticle], c2: List[NormalizedArticle]) -> float:
    s1, s2 = _cluster_signature(c1), _cluster_signature(c2)
    inter = len(s1 & s2)
    union = len(s1 | s2) or 1
    return inter / union

def _merge_small_clusters(clusters: List[List[NormalizedArticle]], min_cluster_size: int | None = None, min_merge_sim: float | None = None) -> List[List[NormalizedArticle]]:
    min_cluster_size = min_cluster_size if min_cluster_size is not None else cfg("cluster_merge.min_cluster_size", 2)
    min_merge_sim = min_merge_sim if min_merge_sim is not None else cfg("cluster_merge.min_merge_sim", 0.22)
    clusters = [sorted(c, key=lambda x: x.importance_score, reverse=True) for c in clusters if c]
    if not clusters:
        return []
    large = [c for c in clusters if len(c) >= min_cluster_size]
    small = [c for c in clusters if len(c) < min_cluster_size]
    if not large:
        return clusters
    for s in small:
        sims = [(_cluster_sim(s, c), i) for i, c in enumerate(large)]
        best_sim, best_idx = max(sims, key=lambda x: x[0]) if sims else (0.0, -1)
        if best_idx >= 0 and best_sim >= min_merge_sim:
            large[best_idx].extend(s)
            large[best_idx] = sorted(large[best_idx], key=lambda x: x.importance_score, reverse=True)
        else:
            large.append(s)
    return large

def _split_cluster_by_signal(cluster: List[NormalizedArticle]) -> List[List[NormalizedArticle]]:
    buckets: Dict[str, List[NormalizedArticle]] = {}
    for a in cluster:
        key = (a.signal_type or '').strip().lower() or 'other'
        buckets.setdefault(key, []).append(a)
    groups = [v for v in buckets.values() if v]
    if len(groups) >= 2:
        return groups
    by_inst: Dict[str, List[NormalizedArticle]] = {}
    for a in cluster:
        key = (a.company_or_firm_name or '').strip().lower() or 'unknown'
        by_inst.setdefault(key, []).append(a)
    groups = [v for v in by_inst.values() if v]
    if len(groups) >= 2:
        return groups
    mid = max(1, len(cluster) // 2)
    return [cluster[:mid], cluster[mid:]] if len(cluster) > 1 else [cluster]


def _rebalance_cluster_count(clusters: List[List[NormalizedArticle]], min_topics: int | None = None, max_topics: int | None = None) -> List[List[NormalizedArticle]]:
    min_topics = min_topics if min_topics is not None else cfg("cluster_merge.min_topics", 2)
    max_topics = max_topics if max_topics is not None else cfg("cluster_merge.max_topics", 4)
    clusters = [c for c in clusters if c]
    if not clusters:
        return clusters

    # Split when topics are too few and there is enough material.
    while len(clusters) < min_topics:
        idx = max(range(len(clusters)), key=lambda i: len(clusters[i]))
        largest = clusters[idx]
        if len(largest) < 2:
            break
        parts = [x for x in _split_cluster_by_signal(largest) if x]
        if len(parts) <= 1:
            break
        clusters.pop(idx)
        clusters.extend(parts)
        if len(clusters) >= min_topics:
            break

    # Merge when topics are too many: merge the most similar pair first to reduce semantic drift.
    while len(clusters) > max_topics:
        best = (-1.0, 0, 1)
        for i in range(len(clusters)):
            for j in range(i + 1, len(clusters)):
                sim = _cluster_sim(clusters[i], clusters[j])
                if sim > best[0]:
                    best = (sim, i, j)
        _, i, j = best
        merged = sorted(clusters[i] + clusters[j], key=lambda x: x.importance_score, reverse=True)
        nxt = []
        for k, c in enumerate(clusters):
            if k not in {i, j}:
                nxt.append(c)
        nxt.append(merged)
        clusters = nxt

    return [sorted(c, key=lambda x: x.importance_score, reverse=True) for c in clusters if c]


def run_pipeline(lookback_days: int = 7, max_articles_per_source: int = 35) -> Tuple[RunSummary, List[NormalizedArticle], List[TopicCluster], List[NormalizedArticle], dict | None]:
    started = now_utc()
    sources = load_sources()
    drop_reasons = defaultdict(int)
    raw_articles: List[NormalizedArticle] = []
    article_idx = 1
    covered_sources = 0

    def _is_rss_content(text: str) -> bool:
        head = text.lstrip()[:500]
        return head.startswith("<?xml") or "<rss" in head or "<feed" in head

    def _fetch_one_source(s):
        """Fetch all articles from a single source. Returns (articles, local_drop_reasons)."""
        local_drops = defaultdict(int)
        local_articles = []
        _log("source_fetch_start", source=s.source_name, landing=s.landing_url)
        listing_urls = discover_listing_urls(s)
        source_candidates = []
        rss_articles = []

        for lu in listing_urls[:cfg("pipeline.listing_urls_limit", 6)]:
            html = fetch_url(lu)
            if not html:
                continue
            # If the listing page is RSS/Atom, extract articles directly from the
            # feed XML — this avoids 403 errors when individual article pages
            # block automated fetching (e.g. OpenAI, xAI).
            if _is_rss_content(html):
                rss_arts = extract_rss_articles(html, s)
                rss_articles.extend(rss_arts)
                _log("rss_feed_parsed", source=s.source_name, listing=lu, articles=len(rss_arts))
            else:
                links = discover_article_links(html, lu, s)
                source_candidates.extend(links)
                _log("listing_parsed", source=s.source_name, listing=lu, candidate_links=len(links))

        # Process RSS-extracted articles (already parsed, just need date filtering)
        for art in rss_articles[:max_articles_per_source]:
            pub_dt = dt.datetime.fromisoformat(art.published_at.replace("Z", "+00:00"))
            if not within_last_days(pub_dt, lookback_days):
                local_drops["outside_7d_window"] += 1
                continue
            local_articles.append(art)

        # Process HTML-discovered candidates (fetch each article page)
        uniq_candidates = list(dict.fromkeys(source_candidates))[: max_articles_per_source]
        for u in uniq_candidates:
            html = fetch_url(u)
            if not html:
                local_drops["empty_or_inaccessible"] += 1
                continue
            art = extract_article(html, u, s, 0)  # idx assigned later
            if not art:
                local_drops["not_real_article_or_bad_parse"] += 1
                continue
            pub_dt = dt.datetime.fromisoformat(art.published_at.replace("Z", "+00:00"))
            if not within_last_days(pub_dt, lookback_days):
                local_drops["outside_7d_window"] += 1
                continue
            if not art.content_text:
                local_drops["empty_content"] += 1
                continue
            local_articles.append(art)
        _log("source_fetch_end", source=s.source_name, kept=len(local_articles), candidates=len(uniq_candidates) + len(rss_articles))
        return local_articles, local_drops

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(_fetch_one_source, s): s for s in sources}
        for fut in as_completed(futures):
            try:
                arts, local_drops = fut.result()
            except Exception:
                logger.warning("source %s fetch failed", futures[fut].source_name, exc_info=True)
                continue
            for reason, cnt in local_drops.items():
                drop_reasons[reason] += cnt
            if arts:
                covered_sources += 1
            for a in arts:
                a.article_id = f"article_{article_idx:04d}"
                raw_articles.append(a)
                article_idx += 1

    deduped = dedupe_articles(raw_articles)
    _log("dedupe_complete", before=len(raw_articles), after=len(deduped))

    # Excel export is deferred to after cleaning so we can mark selection status.
    import os as _os
    import pathlib as _pathlib
    _excel_output_dir = _pathlib.Path(_os.environ.get("PAPERS_DIR", "papers"))

    # Step-2: traverse all deduped news and output structured paragraph first.
    for a in deduped:
        a.article_summary_zh = summarize_article_with_llm(a) or summarize_article_zh(a)
        if not (a.summary or "").strip():
            a.summary = _build_precluster_summary(a)
        a.related_entities = infer_entities(a)

    # Step-3: strict cleaning on structured paragraphs.
    cleaned: List[NormalizedArticle] = []
    for a in deduped:
        if not _passes_signal_gate(a):
            drop_reasons["low_signal_content"] += 1
            continue
        if not _passes_role_specific_gate(a):
            drop_reasons["role_specific_filtered"] += 1
            continue
        cleaned.append(a)

    _log("cluster_input_ready", events=len(cleaned), deduped=len(deduped))

    # Export ALL deduped articles to Excel with selection status.
    _excel_output_dir.mkdir(parents=True, exist_ok=True)
    excel_path = _excel_output_dir / "official_monitor_raw_articles.xlsx"
    selected_titles = {a.title for a in cleaned}
    export_raw_articles_excel(deduped, excel_path, selected_titles=selected_titles)
    _log("raw_articles_excel_exported", path=str(excel_path), total=len(deduped), selected=len(cleaned))

    clusters_raw = cluster_articles(cleaned)
    clusters_raw = _merge_small_clusters(clusters_raw, min_cluster_size=2)
    clusters_raw = _rebalance_cluster_count(clusters_raw, min_topics=2, max_topics=4)
    _log("cluster_counts", clusters=len(clusters_raw), events=sum(len(c) for c in clusters_raw))

    topic_clusters: List[TopicCluster] = []
    used_topic_titles: set[str] = set()
    for idx, cl in enumerate(clusters_raw, start=1):
        meta = build_topic_meta(cl, idx)
        bundle = summarize_cluster_bundle_with_llm(cl, meta["topic_keywords"])
        if bundle:
            llm_title, event_summary, strategic_signal = bundle
            if llm_title:
                meta["topic_title"] = llm_title
        else:
            llm_cluster_summary = summarize_with_llm(cl, meta["topic_keywords"])
            if llm_cluster_summary:
                event_summary, strategic_signal = llm_cluster_summary
            else:
                event_summary, strategic_signal = summarize_cluster_event_zh(cl, meta["topic_keywords"])

        # Final title de-dup after all title generation (including GPT title).
        t = str(meta.get("topic_title") or "").strip()
        if t in used_topic_titles:
            kw = next((k for k in (meta.get("topic_keywords") or []) if k), "综合")
            inst = next((a.company_or_firm_name for a in cl if a.company_or_firm_name), "多机构")
            meta["topic_title"] = f"{t}｜{kw}/{inst}"
        used_topic_titles.add(str(meta.get("topic_title") or ""))

        supporting = []
        for a in sorted(cl, key=lambda x: x.importance_score, reverse=True)[:4]:
            a.topic_cluster_id = meta["topic_cluster_id"]
            # Already generated in Step-2; keep deterministic fallback only.
            a.article_summary_zh = a.article_summary_zh or summarize_article_zh(a)
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
        kept_articles=len(cleaned),
        deduped_articles=len(deduped),
        topic_clusters=len(topic_clusters),
        drop_reasons=dict(drop_reasons),
    )
    _log("topic_generation_complete", topics=len(topic_clusters))
    _log("final_report_summary", deduped=len(deduped), topics=len(topic_clusters))

    # ── Post-pipeline self-reflection: evaluate filtering quality ──
    reflection_result = None
    try:
        from .reflection import reflect_on_filtering
        reflection_result = reflect_on_filtering(deduped, cleaned, topic_clusters)
    except Exception as exc:
        _log("reflection_error", error=str(exc))

    return summary, deduped, topic_clusters, cleaned, reflection_result


def sample_run_data() -> Tuple[RunSummary, List[NormalizedArticle], List[TopicCluster], List[NormalizedArticle], None]:
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
    return summary, ded, topic_clusters, ded, None
