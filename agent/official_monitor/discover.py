from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

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


def discover_article_links(listing_html: str, listing_url: str, source: SourceConfig) -> list[str]:
    # Detect RSS/Atom feed content and use specialized parser.
    head = listing_html.lstrip()[:500]
    is_feed = (
        head.startswith("<?xml")
        or "<rss" in head
        or "<feed" in head
    )
    if is_feed:
        return _extract_rss_links(listing_html, listing_url, source)[:200]

    links = []
    seen = set()
    for href in re.findall(r'href=["\']([^"\']+)["\']', listing_html, flags=re.I):
        full = urljoin(listing_url, href.strip())
        if not full.startswith("http"):
            continue
        if not _is_allowed(full, source) or _is_excluded(full, source):
            continue
        if _is_non_article(full):
            continue
        if not _has_enough_path(full):
            continue
        # Deduplicate ignoring trailing slash and fragment
        norm = full.split("#")[0].rstrip("/")
        if norm not in seen:
            seen.add(norm)
            links.append(full)
    return links[:200]
