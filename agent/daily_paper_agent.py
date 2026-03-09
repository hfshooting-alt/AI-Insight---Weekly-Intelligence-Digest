#!/usr/bin/env python3
"""
Daily paper scouting + deep-reading report agent.

Features:
1) Aggregates papers from multiple academic sources in last 24h.
2) Filters for World Engine + data infra related topics.
3) Generates per-paper precision report (one-line core + bullets + full deep read).
4) Sends a daily email digest at 10:00 local time.

Required env vars:
- OPENAI_API_KEY
- REPORT_EMAIL_TO

Optional env vars:
- REPORT_EMAIL_FROM
- SMTP_HOST / SMTP_PORT / SMTP_USER / SMTP_PASS
- REPORT_TIME (default: 10:00)
- TZ (default: Asia/Shanghai)
"""

from __future__ import annotations

import datetime as dt
import os
import re
import smtplib
import textwrap
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Dict, List, Optional

import feedparser
import requests
from apscheduler.schedulers.blocking import BlockingScheduler
from openai import OpenAI


TOPIC_KEYWORDS = [
    "world engine",
    "world model",
    "world simulator",
    "digital twin engine",
    "synthetic data",
    "simulation data",
    "data infrastructure",
    "data pipeline",
    "data ingestion",
    "data production",
    "data processing",
    "data lakehouse",
    "retrieval infrastructure",
    "infra layer",
    "knowledge graph infrastructure",
    "agentic simulation",
    "cn: 世界引擎",
    "cn: 数据基础设施",
    "cn: 数据采集",
    "cn: 数据处理",
    "cn: 合成数据",
]


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


def parse_dt(value: str) -> Optional[dt.datetime]:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def within_24h(published: Optional[dt.datetime]) -> bool:
    if not published:
        return False
    return published >= now_utc() - dt.timedelta(hours=24)


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def topical_score(title: str, abstract: str) -> int:
    hay = f"{normalize(title)} {normalize(abstract)}"
    score = 0
    for kw in TOPIC_KEYWORDS:
        k = normalize(kw.replace("cn:", ""))
        if k and k in hay:
            score += 1
    return score


def fetch_arxiv() -> List[Paper]:
    query = "(all:world%20model%20OR%20all:synthetic%20data%20OR%20all:data%20infrastructure)"
    url = (
        "http://export.arxiv.org/api/query?"
        f"search_query={query}&sortBy=submittedDate&sortOrder=descending&start=0&max_results=60"
    )
    feed = feedparser.parse(url)
    papers: List[Paper] = []
    for entry in feed.entries:
        published = parse_dt(entry.get("published"))
        if not within_24h(published):
            continue
        papers.append(
            Paper(
                title=entry.get("title", ""),
                url=entry.get("link", ""),
                abstract=entry.get("summary", ""),
                source="arXiv",
                published=published,
                authors=[a.name for a in entry.get("authors", [])],
            )
        )
    return papers


def fetch_crossref() -> List[Paper]:
    since = (now_utc() - dt.timedelta(hours=24)).strftime("%Y-%m-%d")
    url = "https://api.crossref.org/works"
    params = {
        "filter": f"from-pub-date:{since}",
        "rows": 80,
        "sort": "published",
        "order": "desc",
        "select": "title,URL,abstract,container-title,author,issued",
    }
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    items = resp.json().get("message", {}).get("items", [])

    papers: List[Paper] = []
    for item in items:
        title_list = item.get("title", [])
        title = title_list[0] if title_list else ""
        abstract = item.get("abstract", "") or ""
        issued = item.get("issued", {}).get("date-parts", [[None, None, None]])[0]
        if not issued or not issued[0]:
            continue
        y, m, d = (issued + [1, 1, 1])[:3]
        published = dt.datetime(y, m or 1, d or 1, tzinfo=dt.timezone.utc)
        if not within_24h(published):
            continue
        authors = []
        for a in item.get("author", []):
            given = a.get("given", "")
            family = a.get("family", "")
            name = f"{given} {family}".strip()
            if name:
                authors.append(name)

        venue = (item.get("container-title") or ["Crossref"])[0]
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


def fetch_openalex() -> List[Paper]:
    since_iso = (now_utc() - dt.timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
    url = "https://api.openalex.org/works"
    params = {
        "filter": f"from_publication_date:{since_iso[:10]}",
        "sort": "publication_date:desc",
        "per-page": 80,
    }
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    results = resp.json().get("results", [])

    papers: List[Paper] = []
    for r in results:
        date_str = r.get("publication_date")
        if not date_str:
            continue
        published = dt.datetime.fromisoformat(date_str).replace(tzinfo=dt.timezone.utc)
        if not within_24h(published):
            continue

        title = r.get("title") or ""
        abstract_idx = r.get("abstract_inverted_index") or {}
        abstract = reconstruct_abstract(abstract_idx)
        authors = [
            (a.get("author") or {}).get("display_name", "")
            for a in r.get("authorships", [])
            if (a.get("author") or {}).get("display_name")
        ]
        papers.append(
            Paper(
                title=title,
                url=r.get("id", ""),
                abstract=abstract,
                source="OpenAlex",
                published=published,
                authors=authors,
            )
        )
    return papers


def reconstruct_abstract(inverted_index: Dict[str, List[int]]) -> str:
    if not inverted_index:
        return ""
    length = 1 + max(max(pos) for pos in inverted_index.values() if pos)
    words = ["" for _ in range(length)]
    for word, positions in inverted_index.items():
        for p in positions:
            if 0 <= p < length:
                words[p] = word
    return " ".join(words).strip()


def collect_recent_papers() -> List[Paper]:
    sources = [fetch_arxiv, fetch_crossref, fetch_openalex]
    all_papers: List[Paper] = []
    for src in sources:
        try:
            all_papers.extend(src())
        except Exception as exc:  # keep one source failure from breaking daily run
            print(f"[WARN] source {src.__name__} failed: {exc}")

    dedup: Dict[str, Paper] = {}
    for p in all_papers:
        key = normalize(p.title)
        if not key:
            continue
        if key not in dedup or topical_score(p.title, p.abstract) > topical_score(
            dedup[key].title, dedup[key].abstract
        ):
            dedup[key] = p

    filtered = [p for p in dedup.values() if topical_score(p.title, p.abstract) > 0]
    filtered.sort(key=lambda x: (topical_score(x.title, x.abstract), x.published), reverse=True)
    return filtered


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
    prompt = build_prompt(paper)
    completion = client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0.2,
        messages=[
            {"role": "system", "content": "你是严谨的论文评审助手。"},
            {"role": "user", "content": prompt},
        ],
    )
    return completion.choices[0].message.content.strip()


def build_daily_digest(client: OpenAI) -> str:
    papers = collect_recent_papers()
    if not papers:
        return "过去24小时没有检索到匹配“World Engine / 数据Infra层”主题的论文。"

    sections = []
    for i, paper in enumerate(papers[:15], start=1):
        analysis = analyze_paper(client, paper)
        sections.append(
            f"## {i}. {paper.title}\n"
            f"- 来源: {paper.source}\n"
            f"- 链接: {paper.url}\n"
            f"- 时间(UTC): {paper.published.isoformat()}\n\n"
            f"{analysis}\n"
        )

    header = (
        f"# World Engine & Data Infra 每日论文情报\n"
        f"生成时间(UTC): {now_utc().isoformat()}\n"
        f"检索窗口: 最近24小时\n"
        f"覆盖来源: arXiv, Crossref(含Science/AAAS/Elsevier/Springer/ACM/IEEE等索引), OpenAlex(跨学科索引)\n\n"
    )
    return header + "\n---\n\n".join(sections)


def send_email(subject: str, body: str) -> None:
    to_email = os.environ["REPORT_EMAIL_TO"]
    from_email = os.environ.get("REPORT_EMAIL_FROM", to_email)

    smtp_host = os.environ.get("SMTP_HOST", "smtp.163.com")
    smtp_port = int(os.environ.get("SMTP_PORT", "465"))
    smtp_user = os.environ.get("SMTP_USER", from_email)
    smtp_pass = os.environ.get("SMTP_PASS", "")

    msg = MIMEMultipart()
    msg["From"] = from_email
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))

    with smtplib.SMTP_SSL(smtp_host, smtp_port) as server:
        if smtp_user and smtp_pass:
            server.login(smtp_user, smtp_pass)
        server.sendmail(from_email, [to_email], msg.as_string())


def run_once() -> None:
    api_key = os.environ["OPENAI_API_KEY"]
    client = OpenAI(api_key=api_key)
    digest = build_daily_digest(client)

    date_str = dt.datetime.now().strftime("%Y-%m-%d")
    send_email(subject=f"[{date_str}] World Engine & Data Infra 每日论文简报", body=digest)
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
    mode = os.environ.get("AGENT_MODE", "once").strip().lower()
    if mode == "schedule":
        run_scheduler()
    else:
        run_once()
