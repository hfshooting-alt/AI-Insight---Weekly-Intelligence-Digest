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

RSS_SOURCES = {
    "Nature": "https://www.nature.com/nature.rss",
    "Science": "https://www.science.org/action/showFeed?type=etoc&feed=rss&jc=science",
    "PNAS": "https://www.pnas.org/action/showFeed?type=etoc&feed=rss&jc=pnas",
    "PLOS ONE": "https://journals.plos.org/plosone/feed/atom",
    "bioRxiv": "https://connect.biorxiv.org/relate/feed/181",
    "medRxiv": "https://connect.medrxiv.org/relate/feed/181",
}


@dataclass
class Paper:
    title: str
    url: str
    abstract: str
    source: str
    published: dt.datetime
    authors: List[str]


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


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


def html_strip(value: str) -> str:
    v = html.unescape(value or "")
    return re.sub(r"<[^>]+>", " ", v)


def within_hours(published: Optional[dt.datetime], hours: int) -> bool:
    if not published:
        return False
    return published >= now_utc() - dt.timedelta(hours=hours)


def topical_score(title: str, abstract: str) -> int:
    hay = normalize(f"{title} {abstract}")
    return sum(1 for kw in TOPIC_KEYWORDS if normalize(kw) in hay)


def fetch_arxiv(lookback_hours: int) -> List[Paper]:
    query = " OR ".join([f'all:"{term}"' for term in SEARCH_TERMS])
    url = (
        "http://export.arxiv.org/api/query?"
        f"search_query=({requests.utils.quote(query)})&sortBy=submittedDate&sortOrder=descending&start=0&max_results=120"
    )
    feed = feedparser.parse(url)
    papers: List[Paper] = []
    for e in feed.entries:
        published = parse_iso_datetime(e.get("published"))
        if not within_hours(published, lookback_hours):
            continue
        papers.append(
            Paper(
                title=e.get("title", ""),
                url=e.get("link", ""),
                abstract=e.get("summary", ""),
                source="arXiv",
                published=published,
                authors=[a.name for a in e.get("authors", [])],
            )
        )
    return papers


def fetch_crossref(lookback_hours: int) -> List[Paper]:
    from_date = (now_utc() - dt.timedelta(days=7)).strftime("%Y-%m-%d")
    papers: List[Paper] = []

    for term in SEARCH_TERMS:
        params = {
            "query.bibliographic": term,
            "filter": f"from-index-date:{from_date}",
            "rows": 30,
            "sort": "indexed",
            "order": "desc",
            "select": "title,URL,abstract,container-title,author,indexed,published-online,published-print,created",
        }
        resp = requests.get("https://api.crossref.org/works", params=params, timeout=30)
        resp.raise_for_status()
        items = resp.json().get("message", {}).get("items", [])

        for item in items:
            title = (item.get("title") or [""])[0]
            abstract = html_strip(item.get("abstract") or "")
            indexed = parse_iso_datetime((item.get("indexed") or {}).get("date-time"))
            created = parse_iso_datetime((item.get("created") or {}).get("date-time"))
            published_online = parse_date_parts(((item.get("published-online") or {}).get("date-parts") or [[None]])[0])
            published_print = parse_date_parts(((item.get("published-print") or {}).get("date-parts") or [[None]])[0])
            published = indexed or created or published_online or published_print
            if not within_hours(published, lookback_hours):
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


def fetch_openalex(lookback_hours: int) -> List[Paper]:
    from_date = (now_utc() - dt.timedelta(days=7)).strftime("%Y-%m-%d")
    papers: List[Paper] = []

    for term in SEARCH_TERMS:
        params = {
            "search": term,
            "filter": f"from_updated_date:{from_date}",
            "sort": "updated_date:desc",
            "per-page": 25,
        }
        resp = requests.get("https://api.openalex.org/works", params=params, timeout=30)
        resp.raise_for_status()
        for r in resp.json().get("results", []):
            updated = parse_iso_datetime(r.get("updated_date"))
            created = parse_iso_datetime(r.get("created_date"))
            pub_date = parse_iso_datetime(r.get("publication_date"))
            published = updated or created or pub_date
            if not within_hours(published, lookback_hours):
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
                )
            )
    return papers


def fetch_semantic_scholar(lookback_hours: int) -> List[Paper]:
    papers: List[Paper] = []
    base = "https://api.semanticscholar.org/graph/v1/paper/search"

    for term in SEARCH_TERMS:
        params = {
            "query": term,
            "limit": 25,
            "offset": 0,
            "fields": "title,abstract,url,authors,publicationDate,publicationVenue",
        }
        resp = requests.get(base, params=params, timeout=30)
        resp.raise_for_status()

        for p in resp.json().get("data", []):
            published = parse_iso_datetime(p.get("publicationDate"))
            if not within_hours(published, lookback_hours):
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
                )
            )
    return papers


def fetch_rss_journals(lookback_hours: int) -> List[Paper]:
    papers: List[Paper] = []
    for source_name, rss_url in RSS_SOURCES.items():
        feed = feedparser.parse(rss_url)
        for e in feed.entries:
            published = (
                parse_iso_datetime(e.get("published"))
                or parse_iso_datetime(e.get("updated"))
                or parse_struct_time(e.get("published_parsed"))
                or parse_struct_time(e.get("updated_parsed"))
            )
            if not within_hours(published, lookback_hours):
                continue

            title = e.get("title", "")
            summary = html_strip(e.get("summary", "") or e.get("description", ""))
            if topical_score(title, summary) <= 0:
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

    filtered = [p for p in dedup.values() if topical_score(p.title, p.abstract) > 0]
    filtered.sort(key=lambda x: (topical_score(x.title, x.abstract), x.published), reverse=True)
    return filtered


def collect_recent_papers() -> Tuple[List[Paper], int, Dict[str, int]]:
    strict_hours = int(os.environ.get("LOOKBACK_HOURS", "24"))
    fallback_hours = int(os.environ.get("FALLBACK_LOOKBACK_HOURS", "168"))
    sources = [fetch_arxiv, fetch_crossref, fetch_openalex, fetch_semantic_scholar, fetch_rss_journals]

    def collect(hours: int) -> Tuple[List[Paper], Dict[str, int]]:
        got: List[Paper] = []
        counts: Dict[str, int] = {}
        for src in sources:
            try:
                rows = src(hours)
                got.extend(rows)
                counts[src.__name__] = len(rows)
                print(f"[INFO] {src.__name__}: {len(rows)} rows within {hours}h")
            except Exception as exc:
                counts[src.__name__] = 0
                print(f"[WARN] {src.__name__} failed: {exc}")
        return dedup_rank(got), counts

    strict, strict_counts = collect(strict_hours)
    if strict:
        return strict, strict_hours, strict_counts

    print(f"[WARN] no papers in {strict_hours}h, fallback to {fallback_hours}h window")
    fallback, fallback_counts = collect(fallback_hours)
    return fallback, fallback_hours, fallback_counts


def build_prompt(paper: Paper) -> str:
    return textwrap.dedent(
        f"""
        你是论文深读器（增量导向 + 博导审稿风格）。

        请分析下面论文并严格输出三段：
        1) 一句话核心（<=45字）
        2) 3-6个bullet points（关注缺口、增量、证据强弱、风险）
        3) 全文精读（分小标题，包含：缺口与增量、核心机制、关键概念、博导审稿判决）

        论文元信息：
        - 标题：{paper.title}
        - 来源：{paper.source}
        - 链接：{paper.url}
        - 作者：{', '.join(paper.authors[:10]) if paper.authors else 'N/A'}
        - 摘要：{paper.abstract[:7000]}

        重要约束：
        - 判断这篇工作“增量是否站得住”。
        - 给出明确判决：strong accept / weak accept / borderline / weak reject / strong reject。
        - 中文输出。
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


def to_html(report_text: str) -> str:
    lines = report_text.splitlines()
    html_lines = [
        "<html><body style='font-family:Arial,Helvetica,sans-serif;line-height:1.6;color:#111;'>",
        "<div style='max-width:920px;margin:0 auto;padding:16px;'>",
    ]
    for line in lines:
        if line.startswith("# "):
            html_lines.append(f"<h1 style='font-size:28px;margin:8px 0 12px'>{html.escape(line[2:])}</h1>")
        elif line.startswith("## "):
            html_lines.append(f"<h2 style='font-size:20px;margin:18px 0 8px'>{html.escape(line[3:])}</h2>")
        elif line.startswith("### "):
            html_lines.append(f"<h3 style='font-size:16px;margin:12px 0 6px'>{html.escape(line[4:])}</h3>")
        elif line.startswith("- "):
            html_lines.append(f"<p style='margin:4px 0 4px 16px'>• {html.escape(line[2:])}</p>")
        elif line.strip() == "---":
            html_lines.append("<hr style='border:none;border-top:1px solid #ddd;margin:18px 0' />")
        elif line.strip():
            safe = html.escape(line).replace("**", "")
            html_lines.append(f"<p style='margin:6px 0'>{safe}</p>")
        else:
            html_lines.append("<div style='height:8px'></div>")
    html_lines.append("</div></body></html>")
    return "\n".join(html_lines)


def build_daily_digest(client: OpenAI) -> Tuple[str, str]:
    papers, hours_used, source_counts = collect_recent_papers()
    if not papers:
        text = (
            "# World Engine & Data Infra 每日论文情报\n"
            "未检索到匹配论文。\n"
            "建议检查：API连通性、关键词、以及各来源限流。"
        )
        return text, to_html(text)

    source_summary = ", ".join([f"{k}:{v}" for k, v in source_counts.items()])
    header = (
        "# World Engine & Data Infra 每日论文情报\n"
        "### 今日概览\n"
        f"- 检索窗口：最近{hours_used}小时\n"
        f"- 覆盖来源：arXiv、Crossref、OpenAlex、Semantic Scholar、期刊RSS\n"
        f"- 原始命中：{source_summary}\n"
        f"- 入选论文：{min(len(papers), int(os.environ.get('MAX_PAPERS', '12')))}篇\n"
    )

    sections = []
    max_papers = int(os.environ.get("MAX_PAPERS", "12"))
    for i, paper in enumerate(papers[:max_papers], start=1):
        analysis = analyze_paper(client, paper)
        sections.append(
            f"## {i}. {paper.title}\n"
            f"- 来源：{paper.source}\n"
            f"- 链接：{paper.url}\n\n"
            f"{analysis}\n"
        )

    text_digest = header + "\n---\n\n".join(sections)
    return text_digest, to_html(text_digest)


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
        subject=f"[{date_str}] World Engine & Data Infra 每日论文简报",
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
