from __future__ import annotations

import hashlib
import re
from html import unescape
from urllib.parse import urlparse, urlunparse

from typing import List

from .dates import parse_date_any, now_utc
from .models import NormalizedArticle, SourceConfig


GENERIC_TITLES = {
    "artificial intelligence", "ai", "news", "newsroom", "blog", "insights", "resources",
    "machine learning", "generative ai", "ai and machine learning", "latest news",
    "models", "datasets", "documentation", "storage", "pricing", "solutions",
    "partners", "customer stories", "case studies", "enterprise",
    "team & enterprise plans", "developer tools",
}


def _looks_like_listing_page(url: str, title_norm: str, raw_html: str) -> bool:
    p = urlparse(url)
    path = (p.path or "").lower().rstrip("/")
    segs = [s for s in path.split("/") if s]
    # Strip common site name suffixes: "Title | Company", "Title – Company", "Title - Company"
    clean_title = re.split(r'\s*[|–—\-]\s*', title_norm)[0].strip()
    if clean_title in GENERIC_TITLES:
        return True
    if title_norm in GENERIC_TITLES:
        return True
    if len(clean_title.split()) <= 3 and any(k in clean_title for k in ["artificial intelligence", "machine learning", "news", "blog", "insights", "models", "datasets", "documentation"]):
        return True
    # Only check the LAST segment — intermediate segments like /blog/ are fine
    if segs and segs[-1] in {"news", "blog", "insights", "resources", "topics", "categories", "tags"}:
        return True
    # Modern article pages easily have 80-120 nav/footer links.
    # True listing pages (index of 20+ articles) have 200+ anchors.
    if len(re.findall(r"<a[^>]+href=", raw_html, flags=re.I)) > 250:
        return True
    return False



def _canonicalize(url: str) -> str:
    p = urlparse(url)
    return urlunparse((p.scheme, p.netloc, p.path.rstrip('/'), '', '', ''))


def _strip_html(raw: str) -> str:
    txt = re.sub(r"<script[\s\S]*?</script>", " ", raw, flags=re.I)
    txt = re.sub(r"<style[\s\S]*?</style>", " ", txt, flags=re.I)
    txt = re.sub(r"<[^>]+>", " ", txt)
    txt = unescape(txt)
    return re.sub(r"\s+", " ", txt).strip()


def _meta_content(html: str, key: str, attr: str = "property") -> str:
    # Try attr-before-content order
    pat1 = rf'<meta[^>]*{attr}=["\']{re.escape(key)}["\'][^>]*content=["\']([^"\']+)["\']'
    m = re.search(pat1, html, flags=re.I)
    if m:
        return m.group(1).strip()
    # Try content-before-attr order
    pat2 = rf'<meta[^>]*content=["\']([^"\']+)["\'][^>]*{attr}=["\']{re.escape(key)}["\']'
    m = re.search(pat2, html, flags=re.I)
    return m.group(1).strip() if m else ""


def _title(html: str) -> str:
    # Try multiple patterns — sites use different markup:
    pats = [
        # og:title (property before content)
        r'<meta[^>]*property=["\']og:title["\'][^>]*content=["\']([^"\']+)["\']',
        # og:title (content before property)
        r'<meta[^>]*content=["\']([^"\']+)["\'][^>]*property=["\']og:title["\']',
        # twitter:title
        r'<meta[^>]*name=["\']twitter:title["\'][^>]*content=["\']([^"\']+)["\']',
        r'<meta[^>]*content=["\']([^"\']+)["\'][^>]*name=["\']twitter:title["\']',
        # JSON-LD headline
        r'"headline"\s*:\s*"([^"]{8,400})"',
        # <h1>
        r'<h1[^>]*>([\s\S]{3,400}?)</h1>',
        # <title>
        r'<title[^>]*>([\s\S]{3,400}?)</title>',
    ]
    for pat in pats:
        m = re.search(pat, html, flags=re.I)
        if m:
            t = _strip_html(m.group(1))
            if len(t) >= 8:
                return t
    return ""


def _date(html: str, text: str):
    cands = []
    for k, attr in [
        ("article:published_time", "property"),
        ("pubdate", "name"),
        ("date", "name"),
        ("article:modified_time", "property"),
        ("og:updated_time", "property"),
        ("datePublished", "itemprop"),
    ]:
        v = _meta_content(html, k, attr)
        if v:
            cands.append(v)
    # JSON-LD schema (very common in modern sites)
    for m in re.finditer(r'"datePublished"\s*:\s*"([^"]+)"', html):
        cands.append(m.group(1))
    for m in re.finditer(r'"dateModified"\s*:\s*"([^"]+)"', html):
        cands.append(m.group(1))
    cands += re.findall(r'<time[^>]*datetime=["\']([^"\']+)["\']', html, flags=re.I)
    # "Published Mar 25, 2026" / "March 25, 2026" patterns in text
    cands += re.findall(
        r'(?:published|posted|date)[:\s]+(\w+\s+\d{1,2},?\s+20\d{2})',
        text[:8000], flags=re.I
    )
    cands += re.findall(r'(20\d{2}[-/]\d{1,2}[-/]\d{1,2})', text[:8000])
    # "Mar 25, 2026" / "25 Mar 2026" loose date patterns
    cands += re.findall(
        r'(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+20\d{2})',
        text[:8000], flags=re.I
    )
    cands += re.findall(
        r'((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+\d{1,2},?\s+20\d{2})',
        text[:8000], flags=re.I
    )
    for c in cands:
        d = parse_date_any(c)
        if d:
            return d
    return None


def extract_article(article_html: str, url: str, source: SourceConfig, idx: int) -> NormalizedArticle | None:
    title = _title(article_html)
    if not title:
        return None

    plain = _strip_html(article_html)
    title_norm = re.sub(r"\s+", " ", title.lower()).strip()
    if _looks_like_listing_page(url, title_norm, article_html):
        return None
    published = _date(article_html, plain)
    if not published:
        # Fallback: use current time so the article isn't silently dropped.
        # The 7-day window filter downstream will still reject truly old content.
        published = now_utc()

    content_text = plain
    # Lower threshold — some JS-heavy pages have minimal static HTML but the
    # title + meta description are still valuable for clustering / summarisation.
    if len(content_text) < 80:
        return None

    author = _meta_content(article_html, "author", "name") or "未披露"
    canonical = _canonicalize(url)
    content_hash = hashlib.sha1(content_text[:4000].encode("utf-8", "ignore")).hexdigest()
    dedupe_key = hashlib.sha1((canonical + title_norm).encode("utf-8", "ignore")).hexdigest()

    tags = []
    for kw in ["agent", "reasoning", "multimodal", "inference", "api", "enterprise", "robotics", "融资", "并购", "推理", "多模态", "智能体", "芯片", "云"]:
        if kw.lower() in content_text.lower() or kw.lower() in title_norm:
            tags.append(kw)

    signal_type = "research_update"
    low = content_text.lower()
    if any(k in low for k in ["launch", "release", "announce", "发布"]):
        signal_type = "product_release"
    if any(k in low for k in ["funding", "investment", "financing", "融资"]):
        signal_type = "investment_signal"
    if any(k in low for k in ["partnership", "collaboration", "合作"]):
        signal_type = "partnership"

    importance = min(100.0, 35.0 + 8.0 * len(tags) + (10.0 if signal_type in {"product_release", "investment_signal"} else 0.0))

    return NormalizedArticle(
        article_id=f"article_{idx:04d}",
        source_name=source.source_name,
        source_type=source.source_type,
        region=source.region,
        company_or_firm_name=source.source_name.split(" ")[0],
        title=title,
        url=url,
        canonical_url=canonical,
        published_at=published.isoformat(),
        collected_at=now_utc().isoformat(),
        author=author,
        language=source.language,
        page_type="article",
        signal_type=signal_type,
        importance_score=importance,
        summary="",
        content_text=content_text,
        tags=tags[:10],
        related_entities=[],
        content_hash=content_hash,
        dedupe_key=dedupe_key,
        normalized_title=title_norm,
        cluster_features={"tags": tags, "signal_type": signal_type},
    )


def extract_rss_articles(rss_xml: str, source: SourceConfig) -> List[NormalizedArticle]:
    """Extract articles directly from RSS/Atom XML without fetching individual pages.

    This is essential for sites like OpenAI that return 403 on article pages
    but expose full content in their RSS feed.
    """
    articles = []
    # Split into items
    items = re.findall(r'<item>([\s\S]*?)</item>', rss_xml, flags=re.I)
    if not items:
        # Atom format
        items = re.findall(r'<entry>([\s\S]*?)</entry>', rss_xml, flags=re.I)

    for idx, item_xml in enumerate(items):
        # Title
        m = re.search(r'<title[^>]*>(?:<!\[CDATA\[)?([\s\S]*?)(?:\]\]>)?</title>', item_xml)
        title = _strip_html(m.group(1).strip()) if m else ""
        if not title or len(title) < 8:
            continue

        # URL
        link = ""
        m = re.search(r'<link[^>]*>([^<]+)</link>', item_xml)
        if m:
            link = m.group(1).strip()
        if not link:
            m = re.search(r'<link[^>]+href=["\']([^"\']+)["\']', item_xml)
            if m:
                link = m.group(1).strip()
        if not link:
            continue

        # Date
        pub_date = None
        for tag in ['pubDate', 'dc:date', 'published', 'updated']:
            m = re.search(rf'<{tag}[^>]*>([^<]+)</{tag}>', item_xml, flags=re.I)
            if m:
                pub_date = parse_date_any(m.group(1).strip())
                if pub_date:
                    break
        if not pub_date:
            pub_date = now_utc()

        # Content / description
        content = ""
        for tag in ['content:encoded', 'content', 'description', 'summary']:
            m = re.search(rf'<{tag}[^>]*>(?:<!\[CDATA\[)?([\s\S]*?)(?:\]\]>)?</{tag}>', item_xml, flags=re.I)
            if m and len(m.group(1).strip()) > len(content):
                content = m.group(1).strip()
        content_text = _strip_html(content) if content else title

        # Author
        author = "未披露"
        m = re.search(r'<(?:dc:creator|author)[^>]*>(?:<!\[CDATA\[)?([\s\S]*?)(?:\]\]>)?</(?:dc:creator|author)>', item_xml, flags=re.I)
        if m:
            author = _strip_html(m.group(1).strip()) or "未披露"

        title_norm = re.sub(r"\s+", " ", title.lower()).strip()
        if title_norm in GENERIC_TITLES:
            continue

        canonical = _canonicalize(link)
        content_hash = hashlib.sha1(content_text[:4000].encode("utf-8", "ignore")).hexdigest()
        dedupe_key = hashlib.sha1((canonical + title_norm).encode("utf-8", "ignore")).hexdigest()

        tags = []
        low_combined = (title + " " + content_text).lower()
        for kw in ["agent", "reasoning", "multimodal", "inference", "api", "enterprise", "robotics", "融资", "并购", "推理", "多模态", "智能体", "芯片", "云"]:
            if kw.lower() in low_combined:
                tags.append(kw)

        signal_type = "research_update"
        if any(k in low_combined for k in ["launch", "release", "announce", "发布"]):
            signal_type = "product_release"
        if any(k in low_combined for k in ["funding", "investment", "financing", "融资"]):
            signal_type = "investment_signal"
        if any(k in low_combined for k in ["partnership", "collaboration", "合作"]):
            signal_type = "partnership"

        importance = min(100.0, 35.0 + 8.0 * len(tags) + (10.0 if signal_type in {"product_release", "investment_signal"} else 0.0))

        articles.append(NormalizedArticle(
            article_id=f"article_{idx:04d}",
            source_name=source.source_name,
            source_type=source.source_type,
            region=source.region,
            company_or_firm_name=source.source_name.split(" ")[0],
            title=title,
            url=link,
            canonical_url=canonical,
            published_at=pub_date.isoformat(),
            collected_at=now_utc().isoformat(),
            author=author,
            language=source.language,
            page_type="article",
            signal_type=signal_type,
            importance_score=importance,
            summary=content_text[:500] if content_text != title else "",
            content_text=content_text,
            tags=tags[:10],
            related_entities=[],
            content_hash=content_hash,
            dedupe_key=dedupe_key,
            normalized_title=title_norm,
            cluster_features={"tags": tags, "signal_type": signal_type},
        ))

    return articles
