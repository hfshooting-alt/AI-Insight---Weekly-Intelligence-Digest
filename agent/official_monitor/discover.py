from __future__ import annotations

import datetime as dt
import re
from typing import List, Optional, Tuple
from urllib.parse import urljoin, urlparse

from .dates import parse_date_any, within_last_days
from .models import SourceConfig

# URL path segments / extensions that are definitely NOT articles.
# We use a blocklist approach — accept all links by default, only reject
# navigation, legal, media assets, and other clearly non-article URLs.
_NON_ARTICLE_PATTERNS = [
    # Navigation & structural pages
    "/careers", "/jobs", "/hiring", "/about-us", "/about/",
    "/contact", "/login", "/signup", "/register", "/sign-in",
    "/pricing", "/demo", "/request-demo",
    "/team/", "/people/", "/leadership",
    "/portfolio/", "/companies/",
    # Product / docs / platform pages (not articles)
    "/docs/", "/documentation", "/api-reference", "/sdk",
    "/models/", "/datasets/", "/spaces/",
    "/solutions", "/partners", "/customers",
    "/customer-stories", "/case-studies",
    "/storage", "/enterprise",
    # RSS/feed/API endpoints (not article pages)
    "/feed/", "/feed", "/rss", "xmlrpc.php", "/comments/",
    "/wp-json/", "/wp-admin/", "/wp-login",
    # Legal / policy
    "/privacy", "/terms", "/cookie", "/legal", "/sitemap",
    "/acceptable-use", "/dmca", "/compliance",
    # Taxonomy / pagination
    "/page/", "/author/",
    # Static assets
    ".css", ".js", ".png", ".jpg", ".jpeg", ".gif", ".svg",
    ".pdf", ".xml", ".json", ".zip", ".woff", ".ttf",
    # Social / external
    "javascript:", "mailto:", "tel:", "#",
    "twitter.com", "linkedin.com", "facebook.com", "youtube.com",
    "github.com",
]

# Minimum URL path depth — reject root/homepage links like "https://openai.com/"
_MIN_PATH_SEGMENTS = 1  # At least one path segment after domain


def _is_allowed(url: str, source: SourceConfig) -> bool:
    netloc = urlparse(url).netloc.lower()
    return any(netloc == d or netloc.endswith('.' + d) for d in source.allowed_domains)


def _is_excluded(url: str, source: SourceConfig) -> bool:
    return any(pat in url for pat in source.exclude_url_patterns)


def _is_non_article(url: str) -> bool:
    """Return True if URL is clearly not an article (nav, legal, asset, etc.)."""
    low = url.lower()
    return any(pat in low for pat in _NON_ARTICLE_PATTERNS)


def _has_enough_path(url: str) -> bool:
    """Reject bare domain or single-segment URLs (e.g. https://x.ai/)."""
    path = urlparse(url).path.strip("/")
    if not path:
        return False
    segments = [s for s in path.split("/") if s]
    return len(segments) >= _MIN_PATH_SEGMENTS


def discover_listing_urls(source: SourceConfig) -> list[str]:
    urls = [source.landing_url]
    for p in source.candidate_paths:
        urls.append(urljoin(source.landing_url, p))
    out = []
    seen = set()
    for u in urls:
        if u not in seen and _is_allowed(u, source) and not _is_excluded(u, source):
            seen.add(u)
            out.append(u)
    return out


def _extract_rss_links(xml_text: str, listing_url: str, source: SourceConfig) -> list[str]:
    """Extract article URLs from RSS/Atom XML content."""
    links = []
    seen = set()
    # Match <link>URL</link> (RSS) and <link href="URL"/> (Atom)
    for url in re.findall(r'<link[^>]*>([^<]+)</link>', xml_text):
        url = url.strip()
        if url and url.startswith("http") and url not in seen:
            if _is_allowed(url, source) and not _is_excluded(url, source):
                seen.add(url)
                links.append(url)
    for url in re.findall(r'<link[^>]+href=["\']([^"\']+)["\']', xml_text):
        url = url.strip()
        if url and url.startswith("http") and url not in seen:
            if _is_allowed(url, source) and not _is_excluded(url, source):
                seen.add(url)
                links.append(url)
    return links


def _url_year_too_old(url: str, lookback_days: int = 60) -> bool:
    """If the URL contains a year (e.g. /2023/05/article), reject if clearly too old."""
    m = re.search(r'/(20\d{2})/(\d{1,2})/', url)
    if m:
        try:
            url_year, url_month = int(m.group(1)), int(m.group(2))
            url_date = dt.datetime(url_year, url_month, 1, tzinfo=dt.timezone.utc)
            now = dt.datetime.now(dt.timezone.utc)
            if (now - url_date).days > lookback_days:
                return True
        except ValueError:
            pass
    return False


def _extract_nearby_date(html: str, href_pos: int) -> Optional[dt.datetime]:
    """Try to find a date string near the link in the listing HTML."""
    # Look at the 300 chars surrounding the href position
    start = max(0, href_pos - 200)
    end = min(len(html), href_pos + 200)
    snippet = html[start:end]
    # Common date patterns in listing pages
    for pat in [
        r'(20\d{2}[-/]\d{1,2}[-/]\d{1,2})',
        r'<time[^>]*datetime=["\']([^"\']+)["\']',
        r'((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+\d{1,2},?\s+20\d{2})',
        r'(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+20\d{2})',
    ]:
        m = re.search(pat, snippet, flags=re.I)
        if m:
            d = parse_date_any(m.group(1))
            if d:
                return d
    return None


def discover_article_links(
    listing_html: str,
    listing_url: str,
    source: SourceConfig,
    lookback_days: int = 14,
) -> List[Tuple[str, Optional[dt.datetime]]]:
    """Discover article links, returning (url, hint_date) tuples.

    hint_date is extracted from the listing page HTML context near the link,
    allowing the caller to skip articles outside the time window WITHOUT
    fetching each article page.
    """
    # Detect RSS/Atom feed content and use specialized parser.
    head = listing_html.lstrip()[:500]
    is_feed = (
        head.startswith("<?xml")
        or "<rss" in head
        or "<feed" in head
    )
    if is_feed:
        rss_links = _extract_rss_links(listing_html, listing_url, source)
        return [(url, None) for url in rss_links[:200]]

    links = []
    seen = set()
    for m in re.finditer(r'href=["\']([^"\']+)["\']', listing_html, flags=re.I):
        href = m.group(1)
        full = urljoin(listing_url, href.strip())
        if not full.startswith("http"):
            continue
        if not _is_allowed(full, source) or _is_excluded(full, source):
            continue
        low = full.lower()
        if any(tok in low for tok in reject_tokens):
            continue
        if not any(k in low for k in ["/news", "/blog", "/research", "/article", "/insights", "/press", "/stories", "/posts"]):
            continue
        # Skip URLs with year/month in path that are clearly too old
        if _url_year_too_old(full, lookback_days=lookback_days + 30):
            continue
        # Deduplicate ignoring trailing slash and fragment
        norm = full.split("#")[0].rstrip("/")
        if norm not in seen:
            seen.add(norm)
            hint_date = _extract_nearby_date(listing_html, m.start())
            links.append((full, hint_date))
    return links[:200]
