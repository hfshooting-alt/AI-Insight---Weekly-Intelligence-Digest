#!/usr/bin/env python3
"""
Daily paper scouting + deep-reading report agent.
"""

from __future__ import annotations

import datetime as dt
import html
import os
import re
import smtplib
import textwrap
import time
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Dict, Iterable, List, Optional, Tuple

import feedparser
import requests
from apscheduler.schedulers.blocking import BlockingScheduler
from openai import OpenAI

BEIJING_TZ = dt.timezone(dt.timedelta(hours=8))

SEARCH_TERMS = [
    "world engine",
    "world model",
    "world simulator",
    "digital twin",
    "synthetic data",
    "simulation data",
    "data infrastructure",
    "data ingestion",
    "data pipeline",
    "data processing",
    "data lakehouse",
    "agent simulation",
    "knowledge graph infrastructure",
]

TOPIC_KEYWORDS = SEARCH_TERMS + [
    "世界引擎",
    "世界模型",
    "合成数据",
    "数据基础设施",
    "数据采集",
    "数据处理",
    "仿真",
]

WORLD_STRICT_KEYWORDS = [
    "world engine", "world model", "world simulator", "interactive world",
    "physics simulator", "robot simulation", "digital twin", "embodied",
    "世界引擎", "世界模型", "仿真引擎",
]

INFRA_STRICT_KEYWORDS = [
    "data infrastructure", "data infra", "data pipeline", "data ingestion",
    "stream processing", "batch processing", "etl", "feature store",
    "data lake", "data lakehouse", "data quality", "data governance",
    "data orchestration", "knowledge graph infrastructure", "synthetic data generation",
    "vector database", "data observability", "schema evolution",
    "数据基础设施", "数据管道", "数据采集", "流处理", "湖仓", "特征库", "数据治理",
]

IRRELEVANT_HINT_KEYWORDS = [
    "t cell", "tumor", "cancer", "clinical", "patient", "medical", "medicine",
    "drug", "antigen", "genome", "protein", "cell", "herb", "medicinal plant",
    "botany", "agriculture", "crop", "ethnobotany", "pharmacology",
    "spacecraft", "satellite", "astronomy", "orbit",
    "航天", "医学", "肿瘤", "临床", "蛋白", "细胞", "草药", "药用植物", "农业", "作物",
]

INVESTMENT_TECH_KEYWORDS = [
    "model", "engine", "simulator", "training", "inference", "benchmark", "algorithm",
    "system", "framework", "platform", "pipeline", "infrastructure", "scalable",
    "latency", "throughput", "reliability", "dataset", "evaluation", "deployment",
    "architecture", "distributed", "stream", "batch", "etl", "lakehouse",
    "模型", "引擎", "仿真", "训练", "推理", "系统", "框架", "平台", "管道", "基础设施",
]

EXCLUDED_NON_TECH_KEYWORDS = [
    "art", "artist", "mural", "museum", "heritage", "aesthetics", "culture", "curation",
    "filipino", "humanities", "literature", "music", "dance", "painting", "exhibition",
    "艺术", "壁画", "博物馆", "文化", "文学", "音乐", "舞蹈", "展览", "美学",
]

CORE_WORLD_ANCHORS = [
    "world model", "world engine", "world simulator", "interactive world", "digital twin", "世界模型", "世界引擎",
]

CORE_INFRA_ANCHORS = [
    "data infrastructure", "data infra", "data pipeline", "data ingestion", "data lakehouse", "feature store",
    "stream processing", "batch processing", "etl", "data orchestration", "数据基础设施", "数据管道", "湖仓",
]

RSS_SOURCES = {
    "Nature": "https://www.nature.com/nature.rss",
    "Science": "https://www.science.org/action/showFeed?type=etoc&feed=rss&jc=science",
    "PNAS": "https://www.pnas.org/action/showFeed?type=etoc&feed=rss&jc=pnas",
    "PLOS ONE": "https://journals.plos.org/plosone/feed/atom",
    "bioRxiv": "https://connect.biorxiv.org/relate/feed/181",
    "medRxiv": "https://connect.medrxiv.org/relate/feed/181",
}

REQUEST_HEADERS = {
    "User-Agent": "daily-paper-agent/1.0 (academic-digest; mailto:report@example.com)",
}


@dataclass
class Paper:
    title: str
    url: str
    abstract: str
    source: str
    published: dt.datetime
    authors: List[str]
    citation_count: int = 0
    influence_score: float = 0.0


@dataclass
class AnalyzedPaper:
    paper: Paper
    category: str
    analysis_lines: List[str]


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def now_beijing() -> dt.datetime:
    return dt.datetime.now(BEIJING_TZ)


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def parse_iso_datetime(value: Optional[str]) -> Optional[dt.datetime]:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if not parsed.tzinfo:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed.astimezone(dt.timezone.utc)
    except Exception:
        return None


def parse_struct_time(value: Optional[time.struct_time]) -> Optional[dt.datetime]:
    if not value:
        return None
    try:
        return dt.datetime.fromtimestamp(time.mktime(value), tz=dt.timezone.utc)
    except Exception:
        return None


def parse_date_parts(parts: List[int]) -> Optional[dt.datetime]:
    if not parts or not parts[0]:
        return None
    y = parts[0]
    m = parts[1] if len(parts) > 1 else 1
    d = parts[2] if len(parts) > 2 else 1
    try:
        return dt.datetime(y, m, d, tzinfo=dt.timezone.utc)
    except Exception:
        return None


def parse_date_string(value: Optional[str]) -> Optional[dt.datetime]:
    if not value:
        return None
    try:
        d = dt.date.fromisoformat(value)
        return dt.datetime(d.year, d.month, d.day, tzinfo=dt.timezone.utc)
    except Exception:
        return None


def html_strip(value: str) -> str:
    v = html.unescape(value or "")
    return re.sub(r"<[^>]+>", " ", v)


def in_beijing_yesterday_or_today(published: Optional[dt.datetime]) -> bool:
    if not published:
        return False
    bj_date = published.astimezone(BEIJING_TZ).date()
    today = now_beijing().date()
    yesterday = today - dt.timedelta(days=1)
    return bj_date == today or bj_date == yesterday


def beijing_day_window() -> Tuple[str, str]:
    """Return yesterday/today in Beijing as YYYY-MM-DD (for source-side filters)."""
    today = now_beijing().date()
    yesterday = today - dt.timedelta(days=1)
    return yesterday.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")


def topical_score(title: str, abstract: str) -> int:
    hay = normalize(f"{title} {abstract}")
    base = sum(1 for kw in TOPIC_KEYWORDS if normalize(kw) in hay)
    world_hit = sum(1 for kw in WORLD_STRICT_KEYWORDS if normalize(kw) in hay)
    infra_hit = sum(1 for kw in INFRA_STRICT_KEYWORDS if normalize(kw) in hay)
    tech_hit = sum(1 for kw in INVESTMENT_TECH_KEYWORDS if normalize(kw) in hay)
    penalty = sum(1 for kw in IRRELEVANT_HINT_KEYWORDS if normalize(kw) in hay)
    exclude = sum(1 for kw in EXCLUDED_NON_TECH_KEYWORDS if normalize(kw) in hay)
    return base + world_hit * 3 + infra_hit * 3 + tech_hit - penalty * 3 - exclude * 4


def is_domain_relevant(title: str, abstract: str) -> bool:
    hay = normalize(f"{title} {abstract}")
    world_anchor_hit = sum(1 for kw in CORE_WORLD_ANCHORS if normalize(kw) in hay)
    infra_anchor_hit = sum(1 for kw in CORE_INFRA_ANCHORS if normalize(kw) in hay)
    world_hit = sum(1 for kw in WORLD_STRICT_KEYWORDS if normalize(kw) in hay)
    infra_hit = sum(1 for kw in INFRA_STRICT_KEYWORDS if normalize(kw) in hay)
    tech_hit = sum(1 for kw in INVESTMENT_TECH_KEYWORDS if normalize(kw) in hay)
    excluded = any(normalize(kw) in hay for kw in EXCLUDED_NON_TECH_KEYWORDS)
    penalty = sum(1 for kw in IRRELEVANT_HINT_KEYWORDS if normalize(kw) in hay)

    if excluded or penalty >= 1:
        return False
    has_core_anchor = (world_anchor_hit + infra_anchor_hit) >= 1
    if not has_core_anchor:
        return False
    return (world_hit + infra_hit + tech_hit) >= 3


def fetch_arxiv() -> List[Paper]:
    query = " OR ".join([f'all:"{term}"' for term in SEARCH_TERMS])
    url = (
        "http://export.arxiv.org/api/query?"
        f"search_query=({requests.utils.quote(query)})&sortBy=submittedDate&sortOrder=descending&start=0&max_results=120"
    )
    feed = feedparser.parse(url)
    papers: List[Paper] = []
    for e in feed.entries:
        published = parse_iso_datetime(e.get("published"))
        if not in_beijing_yesterday_or_today(published):
            continue
        papers.append(
            Paper(
                title=e.get("title", ""),
                url=e.get("link", ""),
                abstract=e.get("summary", ""),
                source="arXiv",
                published=published,
                authors=[a.name for a in e.get("authors", [])],
                citation_count=0,
                influence_score=0.0,
            )
        )
    return papers


def fetch_crossref() -> List[Paper]:
    from_date, to_date = beijing_day_window()
    papers: List[Paper] = []

    for term in SEARCH_TERMS:
        params = {
            "query.bibliographic": term,
            "filter": f"from-pub-date:{from_date},until-pub-date:{to_date},type:journal-article",
            "rows": 30,
            "sort": "published",
            "order": "desc",
            "select": "title,URL,abstract,container-title,author,published-online,published-print,issued,is-referenced-by-count",
        }
        resp = requests.get("https://api.crossref.org/works", params=params, timeout=30, headers=REQUEST_HEADERS)
        resp.raise_for_status()
        for item in resp.json().get("message", {}).get("items", []):
            title = (item.get("title") or [""])[0]
            abstract = html_strip(item.get("abstract") or "")
            published_online = parse_date_parts(((item.get("published-online") or {}).get("date-parts") or [[None]])[0])
            published_print = parse_date_parts(((item.get("published-print") or {}).get("date-parts") or [[None]])[0])
            issued = parse_date_parts(((item.get("issued") or {}).get("date-parts") or [[None]])[0])
            published = published_online or published_print or issued
            if not in_beijing_yesterday_or_today(published):
                continue
            venue = (item.get("container-title") or ["Crossref"])[0]
            authors = [
                f"{a.get('given', '')} {a.get('family', '')}".strip()
                for a in item.get("author", [])
                if f"{a.get('given', '')} {a.get('family', '')}".strip()
            ]
            papers.append(
                Paper(
                    title=title,
                    url=item.get("URL", ""),
                    abstract=abstract,
                    source=f"Crossref/{venue}",
                    published=published,
                    authors=authors,
                    citation_count=int(item.get("is-referenced-by-count") or 0),
                    influence_score=0.0,
                )
            )
    return papers


def reconstruct_abstract(inverted_index: Dict[str, List[int]]) -> str:
    if not inverted_index:
        return ""
    positions = [p for pos in inverted_index.values() for p in pos]
    if not positions:
        return ""
    words = ["" for _ in range(max(positions) + 1)]
    for w, pos in inverted_index.items():
        for p in pos:
            if 0 <= p < len(words):
                words[p] = w
    return " ".join(words).strip()


def fetch_openalex() -> List[Paper]:
    from_date, to_date = beijing_day_window()
    papers: List[Paper] = []

    for term in SEARCH_TERMS:
        params = {
            "search": term,
            "filter": f"from_publication_date:{from_date},to_publication_date:{to_date}",
            "sort": "publication_date:desc",
            "per-page": 25,
            "mailto": "report@example.com",
        }
        resp = requests.get("https://api.openalex.org/works", params=params, timeout=30, headers=REQUEST_HEADERS)
        resp.raise_for_status()
        for r in resp.json().get("results", []):
            published = parse_date_string(r.get("publication_date"))
            if not in_beijing_yesterday_or_today(published):
                continue
            authors = [
                (a.get("author") or {}).get("display_name", "")
                for a in r.get("authorships", [])
                if (a.get("author") or {}).get("display_name")
            ]
            papers.append(
                Paper(
                    title=r.get("title") or "",
                    url=(r.get("primary_location") or {}).get("landing_page_url") or r.get("id") or "",
                    abstract=reconstruct_abstract(r.get("abstract_inverted_index") or {}),
                    source="OpenAlex",
                    published=published,
                    authors=authors,
                    citation_count=int(r.get("cited_by_count") or 0),
                    influence_score=float(r.get("cited_by_count") or 0) / 50.0,
                )
            )
    return papers


def fetch_semantic_scholar() -> List[Paper]:
    papers: List[Paper] = []
    base = "https://api.semanticscholar.org/graph/v1/paper/search"

    from_date, to_date = beijing_day_window()

    for term in SEARCH_TERMS:
        params = {
            "query": term,
            "limit": 25,
            "offset": 0,
            "fields": "title,abstract,url,authors,publicationDate,publicationVenue,citationCount,influentialCitationCount",
            "year": str(now_beijing().year),
        }
        resp = requests.get(base, params=params, timeout=30, headers=REQUEST_HEADERS)
        resp.raise_for_status()
        for p in resp.json().get("data", []):
            published = parse_iso_datetime(p.get("publicationDate"))
            if not published:
                published = parse_date_string(p.get("publicationDate"))
            if not in_beijing_yesterday_or_today(published):
                continue
            if not (from_date <= published.astimezone(BEIJING_TZ).strftime("%Y-%m-%d") <= to_date):
                continue
            venue = (p.get("publicationVenue") or {}).get("name") or "SemanticScholar"
            papers.append(
                Paper(
                    title=p.get("title") or "",
                    url=p.get("url") or "",
                    abstract=p.get("abstract") or "",
                    source=f"SemanticScholar/{venue}",
                    published=published,
                    authors=[a.get("name", "") for a in p.get("authors", []) if a.get("name")],
                    citation_count=int(p.get("citationCount") or 0),
                    influence_score=float(p.get("influentialCitationCount") or 0),
                )
            )
    return papers


def fetch_rss_journals() -> List[Paper]:
    papers: List[Paper] = []
    for source_name, rss_url in RSS_SOURCES.items():
        feed = feedparser.parse(rss_url)
        for e in feed.entries:
            published = (
                parse_iso_datetime(e.get("published"))
                or parse_struct_time(e.get("published_parsed"))
            )
            if not in_beijing_yesterday_or_today(published):
                continue

            title = e.get("title", "")
            summary = html_strip(e.get("summary", "") or e.get("description", ""))
            if not is_domain_relevant(title, summary):
                continue

            authors = []
            for a in e.get("authors", []):
                if getattr(a, "name", ""):
                    authors.append(a.name)
            papers.append(
                Paper(
                    title=title,
                    url=e.get("link", ""),
                    abstract=summary,
                    source=f"RSS/{source_name}",
                    published=published,
                    authors=authors,
                    citation_count=0,
                    influence_score=0.0,
                )
            )
    return papers


def dedup_rank(papers: Iterable[Paper]) -> List[Paper]:
    dedup: Dict[str, Paper] = {}
    for p in papers:
        key = normalize(p.title)
        if not key:
            continue
        prev = dedup.get(key)
        if not prev:
            dedup[key] = p
            continue
        if (topical_score(p.title, p.abstract), impact_score(p), p.published) > (
            topical_score(prev.title, prev.abstract),
            impact_score(prev),
            prev.published,
        ):
            dedup[key] = p

    filtered = [p for p in dedup.values() if is_domain_relevant(p.title, p.abstract)]
    filtered.sort(key=lambda x: (topical_score(x.title, x.abstract), impact_score(x), x.published), reverse=True)
    return filtered




def impact_score(p: Paper) -> float:
    # log-like scaling without math import for stability
    c = max(p.citation_count, 0)
    citation_term = 0.0
    while c > 0:
        citation_term += 1.0
        c //= 10
    return citation_term * 2.5 + max(p.influence_score, 0.0)


def diversify_sources(papers: List[Paper], limit: int) -> List[Paper]:
    """Prefer source diversity so non-arXiv papers are not starved by ranking."""
    if len(papers) <= limit:
        return papers
    by_source: Dict[str, List[Paper]] = {}
    for p in papers:
        by_source.setdefault(p.source.split("/", 1)[0], []).append(p)

    ordered_sources = sorted(by_source.keys(), key=lambda s: len(by_source[s]), reverse=True)
    for s in ordered_sources:
        by_source[s].sort(key=lambda x: (topical_score(x.title, x.abstract), impact_score(x), x.published), reverse=True)

    out: List[Paper] = []
    while len(out) < limit:
        progressed = False
        for source in ordered_sources:
            if by_source[source]:
                out.append(by_source[source].pop(0))
                progressed = True
                if len(out) >= limit:
                    break
        if not progressed:
            break
    return out


def collect_recent_papers() -> Tuple[List[Paper], Dict[str, int]]:
    sources = [fetch_arxiv, fetch_crossref, fetch_openalex, fetch_semantic_scholar, fetch_rss_journals]
    got: List[Paper] = []
    counts: Dict[str, int] = {}

    for src in sources:
        try:
            rows = src()
            got.extend(rows)
            counts[src.__name__] = len(rows)
            print(f"[INFO] {src.__name__}: {len(rows)} rows in Beijing yesterday/today")
        except Exception as exc:
            counts[src.__name__] = 0
            print(f"[WARN] {src.__name__} failed: {exc}")

    return dedup_rank(got), counts




def classify_paper(paper: Paper) -> str:
    txt = normalize(f"{paper.title} {paper.abstract}")
    world_keywords = [
        "world engine", "world model", "world simulator", "interactive world", "digital twin",
        "embodied", "robot simulation", "世界引擎", "世界模型", "仿真引擎",
    ]
    infra_keywords = [
        "data infrastructure", "data infra", "data pipeline", "data ingestion", "etl",
        "stream processing", "batch processing", "feature store", "data lakehouse",
        "data governance", "data observability", "vector database", "synthetic data generation",
        "数据基础设施", "数据管道", "湖仓", "数据治理", "合成数据",
    ]
    world_score = sum(1 for k in world_keywords if normalize(k) in txt)
    infra_score = sum(1 for k in infra_keywords if normalize(k) in txt)

    if infra_score > world_score:
        return "Data Infra"
    if world_score > infra_score:
        return "World Engine"

    # tie-break: infra-first when data stack terms appear
    if any(normalize(k) in txt for k in ["pipeline", "ingestion", "etl", "lakehouse", "feature store", "数据管道", "湖仓"]):
        return "Data Infra"
    return "World Engine"


def build_day_lead_from_analyses(items: List[AnalyzedPaper]) -> str:
    if not items:
        return "今日导读：今天暂无符合条件的新论文。"

    world_items = [it for it in items if it.category == "World Engine"]
    infra_items = [it for it in items if it.category == "Data Infra"]

    def count_matches(rows: List[AnalyzedPaper], keywords: List[str]) -> int:
        c = 0
        for row in rows:
            hay = normalize(f"{row.paper.title} {row.paper.abstract} {' '.join(row.analysis_lines)}")
            if any(normalize(k) in hay for k in keywords):
                c += 1
        return c

    world_sim = count_matches(world_items, ["simulator", "simulation", "仿真", "digital twin", "interactive world"])
    world_agent = count_matches(world_items, ["robot", "policy", "agent", "embodied", "规划", "控制"])
    infra_pipeline = count_matches(infra_items, ["pipeline", "ingestion", "etl", "orchestration", "stream", "batch", "数据管道", "采集", "流处理"])
    infra_quality = count_matches(infra_items, ["quality", "lineage", "lakehouse", "knowledge graph", "synthetic", "数据质量", "湖仓", "知识图谱", "合成数据"])

    parts: List[str] = [
        f"今日导读：今天共收录{len(items)}篇高相关论文，World Engine方向{len(world_items)}篇，Data Infra方向{len(infra_items)}篇。"
    ]

    trend_bits: List[str] = []
    if world_items:
        seg = "World Engine 方向主要围绕"
        seg += "交互式仿真与世界建模" if world_sim else "世界模型能力优化"
        if world_agent:
            seg += "，并与智能体训练或策略执行结合"
        trend_bits.append(seg)

    if infra_items:
        seg = "Data Infra 方向集中在"
        if infra_pipeline and infra_quality:
            seg += "数据采集/处理链路与数据质量治理的协同优化"
        elif infra_pipeline:
            seg += "数据采集、管道编排与处理效率"
        else:
            seg += "数据资产组织、质量与可复用性"
        trend_bits.append(seg)

    if trend_bits:
        parts.append("总体趋势上，" + "；".join(trend_bits) + "。")

    parts.append("整体来看，研究重心更加偏向可落地的系统能力提升，而非单点实验现象。")
    return "".join(parts)


def build_day_summary(papers: List[Paper]) -> str:
    total = len(papers)
    world = sum(1 for p in papers if classify_paper(p) == "World Engine")
    infra = total - world
    return f"今日发布概览：共{total}篇，World Engine方向{world}篇，Data Infra方向{infra}篇。"

def build_prompt(paper: Paper) -> str:
    return textwrap.dedent(
        f"""
        你是论文深读器（增量导向）。

        请严格按下面四行模板输出，不要添加其它栏目：
        一句话核心：<一句话，点出论文最关键贡献>
        背景与现状：<当前技术现状、痛点、论文填补的缺口>
        方法与结果：<论文方法要点、关键实验结果、是否站得住>
        意义与局限：<这项工作的意义、可迁移价值、主要局限>

        输出要求：
        只输出以上四行。
        不要输出“45字以内”等说明。
        不要输出审稿判决。

        论文元信息：
        标题：{paper.title}
        链接：{paper.url}
        作者：{', '.join(paper.authors[:10]) if paper.authors else 'N/A'}
        摘要：{paper.abstract[:7000]}
        """
    ).strip()


def analyze_paper(client: OpenAI, paper: Paper) -> str:
    completion = client.chat.completions.create(
        model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        temperature=0.2,
        messages=[
            {"role": "system", "content": "你是严谨的论文评审助手。"},
            {"role": "user", "content": build_prompt(paper)},
        ],
    )
    return (completion.choices[0].message.content or "").strip()


def clean_symbols(text: str) -> str:
    cleaned = text.replace("#", "").replace("*", "")
    lines = [re.sub(r"^[\-\s]+", "", line) for line in cleaned.splitlines()]
    return "\n".join(lines)


def strip_meta_labels(text: str) -> str:
    banned = [
        "45字",
        "几个要点",
        "全文精读",
        "核心结论",
    ]
    kept: List[str] = []
    for line in text.splitlines():
        s = line.strip()
        if any(k in s for k in banned):
            continue
        kept.append(line)
    return "\n".join(kept).strip()




def format_analysis_text(text: str) -> List[str]:
    raw = clean_symbols(strip_meta_labels(text))
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]

    def pick(prefix: str) -> str:
        for ln in lines:
            if ln.startswith(prefix):
                return ln
        return ""

    core = pick("一句话核心：")
    bg = pick("背景与现状：")
    mr = pick("方法与结果：")
    sig = pick("意义与局限：")

    if core and bg and mr and sig:
        return [core, bg, mr, sig]

    # fallback: keep first long sentence as core and then structured blocks
    joined = " ".join(lines)
    if not joined:
        return []
    parts = [s.strip() for s in re.split(r"[。!?]", joined) if s.strip()]
    core_fallback = f"一句话核心：{parts[0]}" if parts else "一句话核心："
    rest = joined.replace(parts[0], "", 1).strip() if parts else joined
    return [
        core_fallback,
        f"背景与现状：{rest[:180]}",
        f"方法与结果：{rest[180:360] if len(rest) > 180 else rest}",
        f"意义与局限：{rest[360:540] if len(rest) > 360 else rest}",
    ]

def to_html(report_text: str) -> str:
    lines = report_text.splitlines()
    html_lines = [
        "<html><body style='font-family:Inter,Segoe UI,Arial,Helvetica,sans-serif;line-height:1.7;color:#0f172a;background:#f5f7fb;'>",
        "<div style='max-width:980px;margin:0 auto;padding:20px 18px;'>",
    ]
    in_paper = False

    def close_paper_card() -> None:
        nonlocal in_paper
        if in_paper:
            html_lines.append("</div>")
            in_paper = False

    for line in lines:
        striped = line.strip()
        if not striped:
            html_lines.append("<div style='height:12px'></div>")
            continue

        if striped.startswith("World Engine 与 Data Infra 论文日报"):
            close_paper_card()
            html_lines.append(
                f"<h1 style='font-size:38px;font-weight:850;line-height:1.25;margin:6px 0 14px;color:#0b132b'>{html.escape(striped)}</h1>"
            )
        elif striped.startswith("今日发布概览："):
            close_paper_card()
            html_lines.append(
                f"<p style='margin:8px 0 12px;padding:12px 14px;border-radius:10px;background:#ecfeff;border:1px solid #a5f3fc;font-size:16px;font-weight:600;line-height:1.7'>{html.escape(striped)}</p>"
            )
        elif striped.startswith("今日导读："):
            close_paper_card()
            html_lines.append(
                f"<p style='margin:0 0 18px;padding:12px 14px;border-radius:10px;background:#fefce8;border:1px solid #fde68a;font-size:16px;font-weight:500;line-height:1.8'>{html.escape(striped)}</p>"
            )
        elif striped.startswith("分类标题："):
            close_paper_card()
            cat = striped.split("：", 1)[1]
            html_lines.append(
                f"<h2 style='font-size:34px;font-weight:850;line-height:1.25;margin:24px 0 12px;color:#0b132b;letter-spacing:0.1px'>{html.escape(cat)}</h2>"
            )
            html_lines.append("<hr style='border:none;border-top:1px solid #d7deea;margin:0 0 16px 0' />")
        elif re.match(r"^论文\d+：", striped):
            close_paper_card()
            in_paper = True
            html_lines.append(
                "<div style='border-left:4px solid #3b82f6;background:#ffffff;padding:16px 16px 14px;margin:14px 0 18px;border-radius:10px;box-shadow:0 1px 2px rgba(15,23,42,0.06);'>"
            )
            html_lines.append(
                f"<h3 style='font-size:24px;font-weight:800;line-height:1.35;margin:0 0 10px;color:#1f2937'>{html.escape(striped)}</h3>"
            )
        elif striped.startswith("分隔线"):
            close_paper_card()
            html_lines.append("<hr style='border:none;border-top:1px solid #d7deea;margin:18px 0' />")
        elif striped.startswith("一句话核心："):
            html_lines.append(
                f"<p style='margin:10px 0 14px;padding:10px 12px;background:#fff7ed;border:1px solid #fed7aa;border-radius:8px;font-size:19px;font-weight:700;line-height:1.75'>{html.escape(striped)}</p>"
            )
        elif striped.startswith("背景与现状：") or striped.startswith("方法与结果：") or striped.startswith("意义与局限："):
            title, content = striped.split("：", 1)
            html_lines.append(
                f"<p style='margin:14px 0 6px;font-size:20px;font-weight:800;line-height:1.35;color:#0f172a'>{html.escape(title)}</p>"
            )
            html_lines.append(
                f"<p style='margin:0 0 10px;font-size:17px;line-height:1.9;color:#1f2937'>{html.escape(content)}</p>"
            )
        else:
            html_lines.append(f"<p style='margin:8px 0;font-size:17px;line-height:1.85'>{html.escape(striped)}</p>")

    close_paper_card()
    html_lines.append("</div></body></html>")
    return "\n".join(html_lines)


def build_daily_digest(client: OpenAI) -> Tuple[str, str]:
    papers, _ = collect_recent_papers()

    if not papers:
        text = (
            "World Engine 与 Data Infra 论文日报\n"
            "今日发布概览：今天没有检索到符合条件的论文。\n"
            "结果：未检索到符合条件的论文\n"
            "说明：当前严格按北京时间昨天与今天筛选"
        )
        text = clean_symbols(text)
        return text, to_html(text)

    selected = diversify_sources(papers, int(os.environ.get("MAX_PAPERS", "10")))

    analyzed: List[AnalyzedPaper] = []
    for paper in selected:
        category = classify_paper(paper)
        analysis_lines = format_analysis_text(analyze_paper(client, paper))
        analyzed.append(AnalyzedPaper(paper=paper, category=category, analysis_lines=analysis_lines))

    world_items = [x for x in analyzed if x.category == "World Engine"]
    infra_items = [x for x in analyzed if x.category == "Data Infra"]

    blocks = [
        "World Engine 与 Data Infra 论文日报",
        build_day_summary(selected),
        build_day_lead_from_analyses(analyzed),
    ]

    def append_category(cat_title: str, cat_items: List[AnalyzedPaper], start_idx: int) -> int:
        idx = start_idx
        if not cat_items:
            return idx
        blocks.append(f"分类标题：{cat_title}")
        for item in cat_items:
            paper = item.paper
            published_bj = paper.published.astimezone(BEIJING_TZ).strftime("%Y-%m-%d %H:%M")
            blocks.extend(
                [
                    "分隔线",
                    f"论文{idx}：{paper.title}",
                    f"发布时间：{published_bj}（北京时间）",
                    f"链接：{paper.url}",
                ] + item.analysis_lines
            )
            idx += 1
        return idx

    n = 1
    n = append_category("World Engine", world_items, n)
    append_category("Data Infra", infra_items, n)

    text = "\n".join(blocks)
    text = clean_symbols(text)
    return text, to_html(text)


def send_email(subject: str, text_body: str, html_body: str) -> None:
    to_email = os.environ["REPORT_EMAIL_TO"]
    from_email = os.environ.get("REPORT_EMAIL_FROM", to_email)
    smtp_host = os.environ.get("SMTP_HOST", "smtp.163.com")
    smtp_port = int(os.environ.get("SMTP_PORT", "465"))
    smtp_user = os.environ.get("SMTP_USER", from_email)
    smtp_pass = os.environ.get("SMTP_PASS", "")

    msg = MIMEMultipart("alternative")
    msg["From"] = from_email
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP_SSL(smtp_host, smtp_port) as server:
        if smtp_user and smtp_pass:
            server.login(smtp_user, smtp_pass)
        server.sendmail(from_email, [to_email], msg.as_string())


def run_once() -> None:
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    text_digest, html_digest = build_daily_digest(client)
    date_str = dt.datetime.now().strftime("%Y-%m-%d")
    send_email(
        subject=f"[{date_str}] World Engine 与 Data Infra 每日论文简报",
        text_body=text_digest,
        html_body=html_digest,
    )
    print("[OK] daily digest sent")


def run_scheduler() -> None:
    report_time = os.environ.get("REPORT_TIME", "10:00")
    hour, minute = [int(x) for x in report_time.split(":", 1)]
    timezone = os.environ.get("TZ", "Asia/Shanghai")

    scheduler = BlockingScheduler(timezone=timezone)
    scheduler.add_job(run_once, "cron", hour=hour, minute=minute)
    print(f"[INFO] scheduler started, daily at {report_time} ({timezone})")
    scheduler.start()


if __name__ == "__main__":
    if os.environ.get("AGENT_MODE", "once").strip().lower() == "schedule":
        run_scheduler()
    else:
        run_once()
