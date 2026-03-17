from __future__ import annotations

import hashlib
import re
from html import unescape
from urllib.parse import urlparse, urlunparse

from .dates import parse_date_any, now_utc
from .models import NormalizedArticle, SourceConfig


GENERIC_TITLES = {
    "artificial intelligence", "ai", "news", "newsroom", "blog", "insights", "resources",
    "machine learning", "generative ai", "ai and machine learning", "latest news",
}


def _looks_like_listing_page(url: str, title_norm: str, plain_text: str) -> bool:
    p = urlparse(url)
    path = (p.path or "").lower().rstrip("/")
    segs = [s for s in path.split("/") if s]
    if title_norm in GENERIC_TITLES:
        return True
    if len(title_norm.split()) <= 3 and any(k in title_norm for k in ["artificial intelligence", "machine learning", "news", "blog", "insights"]):
        return True
    if segs and segs[-1] in {"news", "blog", "insights", "resources", "topic", "topics", "category", "categories", "tag", "tags"}:
        return True
    if any(s in {"tag", "tags", "category", "categories", "topics"} for s in segs):
        return True
    # listing pages usually contain many repeated teaser anchors
    if len(re.findall(r"<a[^>]+href=", plain_text, flags=re.I)) > 80:
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
    pat = rf'<meta[^>]*{attr}=["\']{re.escape(key)}["\'][^>]*content=["\']([^"\']+)["\']'
    m = re.search(pat, html, flags=re.I)
    return m.group(1).strip() if m else ""


def _title(html: str) -> str:
    for pat in [r'<meta[^>]*property=["\']og:title["\'][^>]*content=["\']([^"\']+)["\']', r'<h1[^>]*>([\s\S]{3,400}?)</h1>', r'<title[^>]*>([\s\S]{3,400}?)</title>']:
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
    ]:
        v = _meta_content(html, k, attr)
        if v:
            cands.append(v)
    cands += re.findall(r'<time[^>]*datetime=["\']([^"\']+)["\']', html, flags=re.I)
    cands += re.findall(r'(20\d{2}[-/]\d{1,2}[-/]\d{1,2})', text[:8000])
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
        return None

    content_text = plain
    if len(content_text) < 220:
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
