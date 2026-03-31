from __future__ import annotations

import logging
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def fetch_url(url: str, timeout: int = 20, retries: int = 2) -> Optional[str]:
    for i in range(retries + 1):
        try:
            r = requests.get(url, timeout=timeout, headers=DEFAULT_HEADERS)
            if r.status_code == 200 and r.text:
                return r.text
            logger.debug("fetch_url %s returned status %d", url, r.status_code)
        except Exception as exc:
            logger.debug("fetch_url %s attempt %d failed: %s", url, i + 1, exc)
        if i < retries:
            time.sleep(0.6 * (i + 1))
    return None


def js_render_stub(url: str) -> Optional[str]:
    """Reserved for future Playwright integration."""
    return None
