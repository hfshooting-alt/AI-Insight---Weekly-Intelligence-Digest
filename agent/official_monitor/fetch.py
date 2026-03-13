from __future__ import annotations

import time
from typing import Optional

import requests

DEFAULT_HEADERS = {
    "User-Agent": "official-monitor/1.0 (+https://example.internal)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def fetch_url(url: str, timeout: int = 20, retries: int = 2) -> Optional[str]:
    for i in range(retries + 1):
        try:
            r = requests.get(url, timeout=timeout, headers=DEFAULT_HEADERS)
            if r.status_code == 200 and r.text:
                return r.text
        except Exception:
            pass
        if i < retries:
            time.sleep(0.6 * (i + 1))
    return None


def js_render_stub(url: str) -> Optional[str]:
    """Reserved for future Playwright integration."""
    return None
