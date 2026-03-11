#!/usr/bin/env python3
"""
Daily paper scouting + deep-reading report agent.
"""

from __future__ import annotations

import datetime as dt
import html
import json
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
    "robot data pipeline", "embodied data pipeline", "autonomy data engine", "sim2real data",
    "teleoperation data", "fleet data", "sensor data pipeline", "perception data curation",
    "multimodal robot dataset", "policy dataset", "trajectory dataset", "feature store for robotics",
    "lakehouse for autonomy", "data labeling for perception", "data governance for robotics",
    "physical ai data", "具身智能数据", "机器人数据管道", "自动驾驶数据管道", "感知数据治理",
    "仿真到现实数据", "遥操作数据", "轨迹数据集", "策略数据集", "车队数据引擎",
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


PHYSICAL_AI_CONTEXT_KEYWORDS = [
    "embodied", "robot", "robotics", "autonomous driving", "self-driving", "carla", "airsim", "gazebo",
    "sim2real", "policy learning", "navigation", "manipulation", "perception", "lidar", "camera rig",
    "world model", "world simulator", "digital twin", "具身", "机器人", "自动驾驶", "导航", "操作", "感知", "仿真",
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
    institutions: List[str]
    citation_count: int = 0
    influence_score: float = 0.0


@dataclass
class AnalyzedPaper:
    paper: Paper
    category: str
    analysis_lines: List[str]
    early_score: int = 0


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
    physical_ai_hit = sum(1 for kw in PHYSICAL_AI_CONTEXT_KEYWORDS if normalize(kw) in hay)
    excluded = any(normalize(kw) in hay for kw in EXCLUDED_NON_TECH_KEYWORDS)
    penalty = sum(1 for kw in IRRELEVANT_HINT_KEYWORDS if normalize(kw) in hay)

    if excluded or penalty >= 1:
        return False

    world_ok = world_anchor_hit >= 1 and (world_hit + tech_hit + physical_ai_hit) >= 3
    infra_ok = infra_anchor_hit >= 1 and physical_ai_hit >= 1 and (infra_hit + tech_hit) >= 3
    return world_ok or infra_ok


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
                institutions=[],
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
            institutions = []
            for a in item.get("author", []):
                for aff in a.get("affiliation", []) or []:
                    name = (aff.get("name") or "").strip()
                    if name:
                        institutions.append(name)
            papers.append(
                Paper(
                    title=title,
                    url=item.get("URL", ""),
                    abstract=abstract,
                    source=f"Crossref/{venue}",
                    published=published,
                    authors=authors,
                    institutions=list(dict.fromkeys(institutions))[:8],
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
            institutions = []
            for a in r.get("authorships", []):
                for inst in a.get("institutions", []) or []:
                    nm = (inst.get("display_name") or "").strip()
                    if nm:
                        institutions.append(nm)
            papers.append(
                Paper(
                    title=r.get("title") or "",
                    url=(r.get("primary_location") or {}).get("landing_page_url") or r.get("id") or "",
                    abstract=reconstruct_abstract(r.get("abstract_inverted_index") or {}),
                    source="OpenAlex",
                    published=published,
                    authors=authors,
                    institutions=list(dict.fromkeys(institutions))[:8],
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
                    institutions=list(dict.fromkeys([aff.strip() for a in p.get("authors", []) for aff in (a.get("affiliations") or []) if isinstance(aff, str) and aff.strip()]))[:8],
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
                    institutions=[],
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
        if (topical_score(p.title, p.abstract), p.published) > (
            topical_score(prev.title, prev.abstract),
            prev.published,
        ):
            dedup[key] = p

    filtered = [p for p in dedup.values() if is_domain_relevant(p.title, p.abstract)]
    filtered.sort(key=lambda x: (topical_score(x.title, x.abstract), x.published), reverse=True)
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
        by_source[s].sort(key=lambda x: (topical_score(x.title, x.abstract), x.published), reverse=True)

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
        "robot data pipeline", "embodied data pipeline", "autonomy data engine", "sim2real data",
        "teleoperation data", "fleet data", "sensor data pipeline", "perception data curation",
        "multimodal robot dataset", "trajectory dataset", "具身智能数据", "机器人数据管道", "自动驾驶数据管道",
    ]
    physical_ai_keywords = ["robot", "embodied", "autonomous driving", "self-driving", "carla", "airsim", "gazebo", "具身", "机器人", "自动驾驶", "感知"]
    world_score = sum(1 for k in world_keywords if normalize(k) in txt)
    infra_score = sum(1 for k in infra_keywords if normalize(k) in txt)
    physical_score = sum(1 for k in physical_ai_keywords if normalize(k) in txt)

    if infra_score >= world_score and infra_score > 0 and physical_score > 0:
        return "Data Infra"
    return "World Engine"

    # tie-break: infra-first when data stack terms appear
    if any(normalize(k) in txt for k in ["pipeline", "ingestion", "etl", "lakehouse", "feature store", "数据管道", "湖仓"]):
        return "Data Infra"
    return "World Engine"


def infer_paper_type(paper: Paper) -> str:
    src = paper.source.lower()
    if "arxiv" in src or "biorxiv" in src or "medrxiv" in src:
        return "预印本"
    if "crossref" in src or "rss" in src or "openalex" in src or "semanticscholar" in src:
        return "期刊/索引收录论文"
    return "论文"


def infer_industry_interface(paper: Paper) -> str:
    txt = normalize(f"{paper.title} {paper.abstract}")
    tags: List[str] = []
    if any(k in txt for k in ["train", "training", "policy", "训练", "学习"]):
        tags.append("训练")
    if any(k in txt for k in ["evaluate", "benchmark", "评测", "evaluation"]):
        tags.append("评测")
    if any(k in txt for k in ["simulat", "digital twin", "仿真", "world model", "world simulator"]):
        tags.append("仿真")
    if any(k in txt for k in ["deploy", "serving", "latency", "inference", "部署", "推理"]):
        tags.append("部署")
    if any(k in txt for k in ["pipeline", "etl", "ingestion", "lakehouse", "feature store", "数据管道", "湖仓"]):
        tags.append("数据管道")
    if not tags:
        tags = ["评测"]
    return " / ".join(dict.fromkeys(tags))


def relevance_components(paper: Paper) -> Tuple[float, float, float]:
    txt = normalize(f"{paper.title} {paper.abstract}")
    relevance = float(max(topical_score(paper.title, paper.abstract), 1))

    method_cues = ["method", "approach", "framework", "architecture", "算法", "方法", "框架"]
    result_cues = ["result", "improv", "benchmark", "实验", "结果", "提升", "accuracy"]
    info_increment = 1.0
    if paper.abstract:
        info_increment += min(len(paper.abstract) / 1200.0, 1.5)
    info_increment += 0.4 * sum(1 for k in method_cues if normalize(k) in txt)
    info_increment += 0.4 * sum(1 for k in result_cues if normalize(k) in txt)

    industry_value = 1.0
    interface = infer_industry_interface(paper)
    industry_value += 0.5 * interface.count("/")
    industry_value += min(impact_score(paper) / 8.0, 2.0)
    return relevance, info_increment, industry_value


def ranking_score(paper: Paper) -> float:
    r, i, v = relevance_components(paper)
    return r * i * v


def _parse_arxiv_id(url: str) -> str:
    m = re.search(r"arxiv\.org/(abs|pdf)/([0-9]{4}\.[0-9]{4,5})(v\d+)?", url or "", re.I)
    return m.group(2) if m else ""


def _detect_links(text: str) -> Dict[str, str]:
    t = text or ""
    out = {"github": "", "huggingface": "", "paperswithcode": ""}
    g = re.search(r"https?://github\.com/[\w\-\.]+/[\w\-\.]+", t, re.I)
    h = re.search(r"https?://huggingface\.co/[\w\-\./]+", t, re.I)
    pwc = re.search(r"https?://paperswithcode\.com/[\w\-\./]+", t, re.I)
    if g:
        out["github"] = g.group(0)
    if h:
        out["huggingface"] = h.group(0)
    if pwc:
        out["paperswithcode"] = pwc.group(0)
    return out


def _github_metrics(repo_url: str) -> Tuple[int, int]:
    if not repo_url:
        return 0, 0
    m = re.search(r"github\.com/([\w\-\.]+)/([\w\-\.]+)", repo_url)
    if not m:
        return 0, 0
    owner, repo = m.group(1), m.group(2).replace('.git', '')
    try:
        r = requests.get(f"https://api.github.com/repos/{owner}/{repo}", timeout=15, headers=REQUEST_HEADERS)
        if r.status_code != 200:
            return 0, 0
        js = r.json()
        return int(js.get("stargazers_count") or 0), int(js.get("forks_count") or 0)
    except Exception:
        return 0, 0


def compute_early_quality_score(paper: Paper, category: str, fulltext_context: str) -> Dict[str, object]:
    text_blob = "\n".join([paper.title, paper.abstract, fulltext_context])
    links = _detect_links(text_blob)
    github_stars, github_forks = _github_metrics(links["github"])

    # A. Author Historical Hit Rate (conservative if data missing)
    core_authors = paper.authors[:3]
    relevant_last4y = 0
    high_impact_last4y = 0
    hit_rate = 0.0
    a_score = 0
    a_reason = "作者历史命中数据缺失，按保守分处理。"

    # B. Reproducibility & Artifact Completeness
    low = normalize(text_blob)
    has_repo = bool(links["github"])
    has_instr = any(k in low for k in ["installation", "usage", "train", "inference", "quick start", "运行", "训练", "推理"])
    has_weights = any(k in low for k in ["pretrained", "checkpoint", "weights", "模型权重"])
    has_dataset_or_eval = any(k in low for k in ["dataset", "benchmark", "evaluation script", "数据集", "评测脚本"])
    has_license = any(k in low for k in ["license", "mit", "apache-2.0", "bsd"])
    has_env = any(k in low for k in ["requirements.txt", "environment.yml", "dockerfile", "conda", "poetry"])
    b_score = min(25, (8 if has_repo else 0) + (4 if has_instr else 0) + (5 if has_weights else 0) + (4 if has_dataset_or_eval else 0) + (2 if has_license else 0) + (2 if has_env else 0))

    # C. Early Community Response
    c_score = 0
    if github_stars >= 1000:
        c_score += 12
    elif github_stars >= 300:
        c_score += 9
    elif github_stars >= 100:
        c_score += 6
    elif github_stars >= 30:
        c_score += 3
    elif github_stars >= 1:
        c_score += 1
    if github_forks >= 100:
        c_score += 4
    elif github_forks >= 30:
        c_score += 3
    elif github_forks >= 10:
        c_score += 2
    elif github_forks >= 1:
        c_score += 1
    pwc_listed = bool(links["paperswithcode"])
    hf_signal = bool(links["huggingface"])
    c_score += 2 if pwc_listed else 0
    c_score += 2 if hf_signal else 0
    c_score = min(20, c_score)

    # D. Experimental Strength
    strong_baselines = any(k in low for k in ["baseline", "sota", "state-of-the-art", "对比方法", "基线"])
    ablation = any(k in low for k in ["ablation", "消融"])
    multi_task = any(k in low for k in ["multi-task", "multiple datasets", "environments", "多个数据集", "多任务", "多环境"])
    efficiency = any(k in low for k in ["latency", "flops", "memory", "throughput", "training cost", "inference cost", "时延", "吞吐", "显存", "成本"])
    limitations = any(k in low for k in ["limitation", "future work", "局限", "未来工作"])
    benchmark_tables = any(k in low for k in ["table", "benchmark", "leaderboard", "表", "基准"])
    d_score = min(15, (4 if strong_baselines else 0) + (3 if ablation else 0) + (3 if multi_task else 0) + (2 if efficiency else 0) + (1 if limitations else 0) + (2 if benchmark_tables else 0))

    # E. Novelty & Problem Importance
    problem_clarity = 3 if any(k in low for k in ["we address", "problem", "challenge", "我们解决", "问题", "挑战"]) else 1
    contribution_specificity = 3 if any(k in low for k in ["we propose", "introduce", "our method", "提出", "方法", "框架"]) else 1
    difference_prior = 2 if any(k in low for k in ["compared with", "different from", "prior work", "相比", "不同于", "已有方法"]) else 1
    frontier = 2 if any(k in low for k in ["world model", "coding agent", "foundation model", "multimodal", "robot", "physical ai", "data infra", "世界模型", "具身", "机器人"]) else 1
    e_score = min(10, problem_clarity + contribution_specificity + difference_prior + frontier)

    total = int(max(0, min(100, a_score + b_score + c_score + d_score + e_score)))

    # confidence
    confidence = 1.0
    if relevant_last4y == 0:
        confidence -= 0.15
    if not has_repo:
        confidence -= 0.15
    if not (links["github"] or links["paperswithcode"] or links["huggingface"]):
        confidence -= 0.10
    if not has_readable_fulltext(fulltext_context):
        confidence -= 0.10
    confidence = max(0.3, round(confidence, 2))

    days_since = max(0, (now_beijing().date() - paper.published.astimezone(BEIJING_TZ).date()).days)
    arxiv_id = _parse_arxiv_id(paper.url)
    availability = {
        "arxiv": "arxiv" in (paper.source or "").lower() or "arxiv.org" in (paper.url or "").lower(),
        "semantic_scholar": "semanticscholar" in (paper.source or "").lower(),
        "openalex": "openalex" in (paper.source or "").lower(),
        "papers_with_code": bool(links["paperswithcode"]),
        "github": bool(links["github"]),
        "huggingface": bool(links["huggingface"]),
    }

    missing = [k for k, v in availability.items() if not v]
    tier = "A" if total >= 85 else "B" if total >= 70 else "C" if total >= 50 else "D"
    label = {"A": "very strong early signal", "B": "promising", "C": "mixed evidence", "D": "weak/insufficient"}[tier]

    return {
      "paper": {
        "title": paper.title,
        "arxiv_id": arxiv_id,
        "arxiv_url": f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else "",
        "published_date": paper.published.astimezone(BEIJING_TZ).strftime("%Y-%m-%d"),
        "days_since_release": days_since,
        "primary_category": category,
        "authors": core_authors,
      },
      "data_availability": availability,
      "scores": {
        "author_historical_hit_rate": {
          "score": a_score, "max_score": 30,
          "raw_metrics": {
            "core_authors": core_authors,
            "relevant_papers_last_4y": relevant_last4y,
            "high_impact_papers_last_4y": high_impact_last4y,
            "hit_rate": hit_rate,
          },
          "reasoning": a_reason,
        },
        "reproducibility_artifacts": {
          "score": b_score, "max_score": 25,
          "raw_metrics": {
            "code_repo": has_repo,
            "instructions": has_instr,
            "weights": has_weights,
            "dataset_or_eval_scripts": has_dataset_or_eval,
            "license": has_license,
            "env_files": has_env,
          },
          "reasoning": "依据代码/权重/说明文档等可复现资产打分。",
        },
        "early_community_response": {
          "score": c_score, "max_score": 20,
          "raw_metrics": {
            "github_stars": github_stars,
            "github_forks": github_forks,
            "papers_with_code_listed": pwc_listed,
            "huggingface_signal": hf_signal,
          },
          "reasoning": "依据早期社区可观测信号打分；新发布论文不做过度解读。",
        },
        "experimental_strength": {
          "score": d_score, "max_score": 15,
          "raw_metrics": {
            "strong_baselines": strong_baselines,
            "ablation": ablation,
            "multi_dataset_or_multi_task": multi_task,
            "efficiency_metrics": efficiency,
            "limitations": limitations,
            "benchmark_tables": benchmark_tables,
          },
          "reasoning": "依据正文中的实验设计与报告完整度打分。",
        },
        "novelty_and_problem_importance": {
          "score": e_score, "max_score": 10,
          "raw_metrics": {
            "problem_clarity": problem_clarity,
            "contribution_specificity": contribution_specificity,
            "difference_from_prior_work": difference_prior,
            "frontier_relevance": frontier,
          },
          "reasoning": "依据问题清晰度、贡献具体性与前沿相关性打分。",
        },
        "total_score": total,
        "confidence": confidence,
      },
      "verdict": {
        "tier": tier,
        "label": label,
        "summary": "早期质量评分用于快速优先级排序，需结合后续复现实验继续验证。",
        "main_strengths": ["结构化实验信号", "可复现资产信号"],
        "main_risks": ["作者历史数据缺失", "早期社区信号波动"],
      },
      "implementation_notes": {
        "missing_data": missing,
        "assumptions": ["仅使用可程序化访问数据源", "缺失字段按保守分处理"],
        "recommended_followup_checks": ["补全作者历史论文画像", "人工复核关键实验表格"],
      }
    }


def build_day_summary(papers: List[Paper]) -> str:
    total = len(papers)
    world = sum(1 for p in papers if classify_paper(p) == "World Engine")
    infra = total - world
    return f"今日总篇数：{total}；World Engine：{world}；Data Infra：{infra}"




def fetch_fulltext_context(paper: Paper) -> str:
    try:
        resp = requests.get(paper.url, timeout=20, headers=REQUEST_HEADERS)
        resp.raise_for_status()
        txt = html_strip(resp.text)
        txt = re.sub(r"\s+", " ", txt).strip()
        return txt[:20000]
    except Exception:
        return ""


def has_readable_fulltext(fulltext_context: str) -> bool:
    # protect against abstract-only snippets / nav noise
    return len(fulltext_context.strip()) >= 2500


def build_prompt(paper: Paper, category: str, fulltext_context: str) -> str:
    return textwrap.dedent(
        f"""
        你是论文原文信息整理 Agent。目标是给非专业读者输出“准确、完整、可读”的三段解读。

        工作方式（请先内部执行，再输出最终答案）：
        1) 先从正文提取：研究问题、已有局限、核心方法步骤、实验结论、作者写明的局限与未来方向。
        2) 仅保留标题/摘要/正文明确支持的信息；不补充推断，不脑补结论。
        3) 重新组织成清晰中文短句，避免术语堆砌与半句收尾。

        严格输出以下四行，不要输出其它字段：
        一句话核心：<一句话完整说明论文做了什么、解决什么问题、得到什么结果；必须是完整句>
        论文背景：<2-3句，包含“背景局限+论文创新点”，只写可证实内容>
        方法与结果：<2-3句，写清方法主线与结果；无量化就写“原文未披露具体幅度”>
        局限与展望：<2-3句，只写作者明确提到的边界与后续方向>

        语言要求：
        短句优先。易懂优先。禁止残句、禁止“推理…/指标…/性能和…”这种未说完的结尾。

        论文分类：{category}
        标题：{paper.title}
        作者：{", ".join(paper.authors[:10]) if paper.authors else "未披露"}
        发表机构：{", ".join(paper.institutions[:8]) if paper.institutions else "未披露"}
        摘要：{paper.abstract[:7000]}
        正文：{fulltext_context[:18000]}
        """
    ).strip()


def analyze_paper(client: OpenAI, paper: Paper, category: str, fulltext_context: str) -> str:
    completion = client.chat.completions.create(
        model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        temperature=0.1,
        messages=[
            {"role": "system", "content": "你是严谨的信息抽取助手。"},
            {"role": "user", "content": build_prompt(paper, category, fulltext_context)},
        ],
    )
    return (completion.choices[0].message.content or "").strip()




def clean_symbols(text: str) -> str:
    cleaned = text.replace("#", "").replace("*", "")
    lines = [re.sub(r"^[\-\s]+", "", line) for line in cleaned.splitlines()]
    return "\n".join(lines)


def parse_structured_analysis(text: str) -> Dict[str, str]:
    keys = ["一句话核心", "论文背景", "方法与结果", "局限与展望"]
    aliases = {
        "一句话核心": "一句话核心",
        "论文背景": "论文背景",
        "背景": "论文背景",
        "方法与结果": "方法与结果",
        "论文方法与结果": "方法与结果",
        "局限与展望": "局限与展望",
        "论文局限与展望": "局限与展望",
    }

    data: Dict[str, str] = {k: "未披露" for k in keys}
    for line in clean_symbols(text).splitlines():
        sline = line.strip()
        if "：" not in sline:
            continue
        k, v = sline.split("：", 1)
        k = aliases.get(k.strip(), "")
        if k and v.strip():
            data[k] = v.strip()

    if data["方法与结果"].strip() in ["未披露", "摘要未披露", "未知", "不详"]:
        data["方法与结果"] = "原文未披露具体幅度。"

    # keep complete sentences; no hard character truncation artifacts
    data["一句话核心"] = _keep_first_sentences(_finalize_sentence(data["一句话核心"]), 1)
    data["论文背景"] = _keep_first_sentences(_finalize_sentence(data["论文背景"]), 3)
    data["方法与结果"] = _keep_first_sentences(_finalize_sentence(data["方法与结果"]), 3)
    data["局限与展望"] = _keep_first_sentences(_finalize_sentence(data["局限与展望"]), 3)
    return data



def _finalize_sentence(text: str) -> str:
    t = re.sub(r"\s+", " ", (text or "")).replace("…", "").strip()
    if not t:
        return "未披露。"
    t = re.sub(r"(和|及|与|并|以及|并且|等)\s*[。！？]$", "。", t)
    t = re.sub(r"，[^，。！？；]{1,2}[。！？]$", "。", t)
    if not re.search(r"[。！？]$", t):
        t += "。"
    return t


def _keep_first_sentences(text: str, max_sentences: int) -> str:
    t = _finalize_sentence(text)
    pieces = [x.strip() for x in re.split(r"(?<=[。！？])", t) if x.strip()]
    if not pieces:
        return t
    out = "".join(pieces[:max_sentences]).strip()
    return _finalize_sentence(out)


def _trim_complete(text: str, max_len: int) -> str:
    t = _finalize_sentence(text)
    if len(t) <= max_len:
        return t
    window = t[:max_len]
    m = max(window.rfind("。"), window.rfind("！"), window.rfind("？"), window.rfind("；"))
    if m >= int(max_len * 0.5):
        return window[:m + 1]
    return _finalize_sentence(re.sub(r"(和|及|与|并|以及|并且|等)$", "", window[: max_len - 1].rstrip("，、；： ")) )


def confidence_level(paper: Paper) -> str:
    if paper.abstract and len(paper.abstract) > 900:
        return "中"
    if paper.abstract:
        return "低"
    return "低"




def importance_level(score: int) -> str:
    # non-linear buckets to better separate low-score papers
    if score >= 85:
        return "高"
    if score >= 70:
        return "较高"
    if score >= 55:
        return "中"
    if score >= 40:
        return "关注"
    if score >= 25:
        return "跟踪"
    if score >= 12:
        return "观察+"
    return "观察"


def format_author_orgs(paper: Paper) -> str:
    authors = paper.authors[:6] if paper.authors else []
    insts = paper.institutions[:6] if paper.institutions else []
    if authors and insts:
        return f"{', '.join(authors)}（{';'.join(insts)}）"
    if authors:
        return ", ".join(authors)
    if insts:
        return "（" + ";".join(insts) + "）"
    return "未披露"


def render_paper_block(index: int, item: AnalyzedPaper, parsed: Dict[str, str]) -> List[str]:
    paper = item.paper
    published_bj = paper.published.astimezone(BEIJING_TZ).strftime("%Y-%m-%d %H:%M")
    return [
        "分隔线",
        f"论文{index}：{paper.title}（重要程度：{importance_level(item.early_score)}）",
        f"发布时间：{published_bj}（北京时间）",
        f"链接：{paper.url}",
        f"作者：{format_author_orgs(paper)}",
        f"一句话核心：{parsed['一句话核心']}",
        f"论文背景：背景&创新点：{parsed['论文背景']}",
        f"方法与结果：{parsed['方法与结果']}",
        f"局限与展望：{parsed['局限与展望']}",
    ]


def build_overview_lines(items: List[AnalyzedPaper]) -> List[str]:
    if not items:
        return [
            "今日总篇数：0",
            "各方向篇数：World Engine 0；Data Infra 0",
            "今日最值得读 Top 3：无",
            "当日趋势：无",
            "总体判断：今天未检索到符合条件的论文。",
        ]

    world = [x for x in items if x.category == "World Engine"]
    infra = [x for x in items if x.category == "Data Infra"]
    top3 = sorted(items, key=lambda x: x.early_score, reverse=True)[:3]
    trend_pool = " ".join([normalize(f"{x.paper.title} {x.paper.abstract}") for x in items])

    trend_lines: List[str] = []
    if any(k in trend_pool for k in ["world model", "world simulator", "digital twin", "世界模型"]):
        trend_lines.append("世界模型与仿真能力继续朝可训练、可评测方向收敛")
    if any(k in trend_pool for k in ["pipeline", "etl", "ingestion", "lakehouse", "数据管道", "湖仓"]):
        trend_lines.append("数据基础设施关注管道效率、治理与可运营性")
    if any(k in trend_pool for k in ["benchmark", "evaluation", "评测", "部署", "latency"]):
        trend_lines.append("评测与部署指标被更频繁地前置到研究叙述")
    if not trend_lines:
        trend_lines = ["当日样本较少，趋势信号有限"]

    return [
        f"今日总篇数：{len(items)}",
        f"各方向篇数：World Engine {len(world)}；Data Infra {len(infra)}",
        "今日最值得读 Top 3：" + "；".join([f"{i+1}.{x.paper.title}" for i, x in enumerate(top3)]),
        "当日趋势：" + "；".join(trend_lines[:3]),
        "总体判断：今天的高相关论文以工程落地信息为主，适合用于技术路线和投资跟踪。",
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
        elif striped.startswith("论文背景：") or striped.startswith("方法与结果：") or striped.startswith("局限与展望："):
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
            "今日总篇数：0\n"
            "各方向篇数：World Engine 0；Data Infra 0\n"
            "今日最值得读 Top 3：无\n"
            "当日趋势：无\n"
            "总体判断：今天未检索到符合条件的论文。"
        )
        cleaned = clean_symbols(text)
        return cleaned, to_html(cleaned)

    selected = diversify_sources(
        sorted(papers, key=ranking_score, reverse=True),
        int(os.environ.get("MAX_PAPERS", "10")),
    )

    analyzed: List[AnalyzedPaper] = []
    parsed_map: Dict[str, Dict[str, str]] = {}
    score_detail_map: Dict[str, Dict[str, object]] = {}
    skipped_no_fulltext = 0
    for paper in selected:
        category = classify_paper(paper)
        fulltext_context = fetch_fulltext_context(paper)
        if not has_readable_fulltext(fulltext_context):
            skipped_no_fulltext += 1
            continue
        score_json = compute_early_quality_score(paper, category, fulltext_context)
        early_score = int(((score_json.get("scores") or {}).get("total_score") or 0))
        raw = analyze_paper(client, paper, category, fulltext_context)
        parsed = parse_structured_analysis(raw)
        analyzed.append(AnalyzedPaper(paper=paper, category=category, analysis_lines=[], early_score=early_score))
        parsed_map[paper.title] = parsed
        score_detail_map[paper.title] = score_json

    if not analyzed:
        text = (
            "World Engine 与 Data Infra 论文日报\n"
            "今日总篇数：0\n"
            "各方向篇数：World Engine 0；Data Infra 0\n"
            "今日最值得读 Top 3：无\n"
            "当日趋势：无\n"
            f"总体判断：候选论文正文抓取不足（跳过{skipped_no_fulltext}篇），未生成正文级解读。"
        )
        cleaned = clean_symbols(text)
        return cleaned, to_html(cleaned)


    analyzed.sort(key=lambda x: x.early_score, reverse=True)
    world_items = [x for x in analyzed if x.category == "World Engine"]
    infra_items = [x for x in analyzed if x.category == "Data Infra"]

    blocks: List[str] = ["World Engine 与 Data Infra 论文日报"]
    blocks.extend(build_overview_lines(analyzed))

    def append_category(cat_title: str, cat_items: List[AnalyzedPaper], start_idx: int) -> int:
        idx = start_idx
        if not cat_items:
            return idx
        blocks.append(f"分类标题：{cat_title}")
        for item in cat_items:
            blocks.extend(render_paper_block(idx, item, parsed_map[item.paper.title]))
            idx += 1
        return idx

    n = 1
    n = append_category("World Engine", world_items, n)
    append_category("Data Infra", infra_items, n)

    text = clean_symbols("\n".join(blocks))
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
