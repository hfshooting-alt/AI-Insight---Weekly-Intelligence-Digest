from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from .models import SourceConfig


def _is_allowed(url: str, source: SourceConfig) -> bool:
    netloc = urlparse(url).netloc.lower()
    return any(netloc == d or netloc.endswith('.' + d) for d in source.allowed_domains)


def _is_excluded(url: str, source: SourceConfig) -> bool:
    return any(pat in url for pat in source.exclude_url_patterns)


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


def discover_article_links(listing_html: str, listing_url: str, source: SourceConfig) -> list[str]:
    links = []
    seen = set()
    for href in re.findall(r'href=["\']([^"\']+)["\']', listing_html, flags=re.I):
        full = urljoin(listing_url, href.strip())
        if not full.startswith("http"):
            continue
        if not _is_allowed(full, source) or _is_excluded(full, source):
            continue
        low = full.lower()
        if not any(k in low for k in ["/news", "/blog", "/research", "/article", "/insights", "/press", "/stories", "/posts"]):
            continue
        if full not in seen:
            seen.add(full)
            links.append(full)
    return links[:120]
