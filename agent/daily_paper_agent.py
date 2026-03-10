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


def topical_score(title: str, abstract: str) -> int:
    hay = normalize(f"{title} {abstract}")
    return sum(1 for kw in TOPIC_KEYWORDS if normalize(kw) in hay)


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
            )
        )
    return papers


def fetch_crossref() -> List[Paper]:
    from_date = (now_utc() - dt.timedelta(days=2)).strftime("%Y-%m-%d")
    papers: List[Paper] = []

    for term in SEARCH_TERMS:
        params = {
            "query.bibliographic": term,
            "filter": f"from-index-date:{from_date}",
            "rows": 30,
            "sort": "indexed",
            "order": "desc",
            "select": "title,URL,abstract,container-title,author,published-online,published-print,issued",
        }
        resp = requests.get("https://api.crossref.org/works", params=params, timeout=30)
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
    from_date = (now_utc() - dt.timedelta(days=2)).strftime("%Y-%m-%d")
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
                )
            )
    return papers


def fetch_semantic_scholar() -> List[Paper]:
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
            if not in_beijing_yesterday_or_today(published):
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
    world_keywords = ["world engine", "world model", "world simulator", "世界引擎", "世界模型", "digital twin"]
    infra_keywords = ["data infrastructure", "data pipeline", "data ingestion", "data processing", "合成数据", "数据基础设施", "数据采集", "数据处理", "synthetic data"]
    world_score = sum(1 for k in world_keywords if normalize(k) in txt)
    infra_score = sum(1 for k in infra_keywords if normalize(k) in txt)
    if world_score >= infra_score:
        return "World Engine"
    return "Data Infra"


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
        "<html><body style='font-family:Inter,Segoe UI,Arial,Helvetica,sans-serif;line-height:1.85;color:#0f172a;background:#f5f7fb;'>",
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

        if striped.startswith("日报标题"):
            close_paper_card()
            html_lines.append(
                f"<h1 style='font-size:34px;font-weight:850;line-height:1.25;margin:6px 0 14px;color:#0b132b'>{html.escape(striped)}</h1>"
            )
        elif striped.startswith("今日发布概览："):
            close_paper_card()
            html_lines.append(
                f"<p style='margin:8px 0 18px;padding:12px 14px;border-radius:10px;background:#ecfeff;border:1px solid #a5f3fc;font-size:17px;font-weight:600;line-height:1.7'>{html.escape(striped)}</p>"
            )
        elif striped.startswith("分类标题："):
            close_paper_card()
            cat = striped.split("：", 1)[1]
            html_lines.append(
                f"<h2 style='font-size:40px;font-weight:900;line-height:1.2;margin:24px 0 12px;color:#0b132b;letter-spacing:0.1px'>{html.escape(cat)}</h2>"
            )
            html_lines.append("<hr style='border:none;border-top:1px solid #d7deea;margin:0 0 16px 0' />")
        elif re.match(r"^论文\d+：", striped):
            close_paper_card()
            in_paper = True
            html_lines.append(
                "<div style='border-left:4px solid #3b82f6;background:#ffffff;padding:16px 16px 14px;margin:14px 0 18px;border-radius:10px;box-shadow:0 1px 2px rgba(15,23,42,0.06);'>"
            )
            html_lines.append(
                f"<h3 style='font-size:40px;font-weight:800;line-height:1.3;margin:0 0 10px;color:#1f2937'>{html.escape(striped)}</h3>"
            )
        elif striped.startswith("分隔线"):
            close_paper_card()
            html_lines.append("<hr style='border:none;border-top:1px solid #d7deea;margin:18px 0' />")
        elif striped.startswith("一句话核心："):
            html_lines.append(
                f"<p style='margin:10px 0 14px;padding:10px 12px;background:#fff7ed;border:1px solid #fed7aa;border-radius:8px;font-size:28px;font-weight:700;line-height:1.75'>{html.escape(striped)}</p>"
            )
        elif striped.startswith("背景与现状：") or striped.startswith("方法与结果：") or striped.startswith("意义与局限："):
            title, content = striped.split("：", 1)
            html_lines.append(
                f"<p style='margin:14px 0 6px;font-size:30px;font-weight:800;line-height:1.35;color:#0f172a'>{html.escape(title)}</p>"
            )
            html_lines.append(
                f"<p style='margin:0 0 10px;font-size:25px;line-height:1.95;color:#1f2937'>{html.escape(content)}</p>"
            )
        else:
            html_lines.append(f"<p style='margin:8px 0;font-size:24px;line-height:1.9'>{html.escape(striped)}</p>")

    close_paper_card()
    html_lines.append("</div></body></html>")
    return "\n".join(html_lines)


def build_daily_digest(client: OpenAI) -> Tuple[str, str]:
    papers, _ = collect_recent_papers()

    if not papers:
        text = (
            "日报标题：World Engine 与 Data Infra 论文日报\n"
            "今日发布概览：今天没有检索到符合条件的论文。\n"
            "结果：未检索到符合条件的论文\n"
            "说明：当前严格按北京时间昨天与今天筛选"
        )
        text = clean_symbols(text)
        return text, to_html(text)

    max_papers = int(os.environ.get("MAX_PAPERS", "12"))
    selected = papers[:max_papers]

    world_papers = [p for p in selected if classify_paper(p) == "World Engine"]
    infra_papers = [p for p in selected if classify_paper(p) == "Data Infra"]

    blocks = [
        "日报标题：World Engine 与 Data Infra 论文日报",
        build_day_summary(selected),
    ]

    def append_category(cat_title: str, cat_papers: List[Paper], start_idx: int) -> int:
        idx = start_idx
        if not cat_papers:
            return idx
        blocks.append(f"分类标题：{cat_title}")
        for paper in cat_papers:
            published_bj = paper.published.astimezone(BEIJING_TZ).strftime("%Y-%m-%d %H:%M")
            analysis_lines = format_analysis_text(analyze_paper(client, paper))
            blocks.extend(
                [
                    "分隔线",
                    f"论文{idx}：{paper.title}",
                    f"发布时间：{published_bj}（北京时间）",
                    f"链接：{paper.url}",
                ] + analysis_lines
            )
            idx += 1
        return idx

    n = 1
    n = append_category("World Engine", world_papers, n)
    append_category("Data Infra", infra_papers, n)

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
