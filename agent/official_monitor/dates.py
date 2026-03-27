from __future__ import annotations

import datetime as dt
import re
from email.utils import parsedate_to_datetime
from typing import Optional


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def within_last_days(ts: dt.datetime, days: int) -> bool:
    if not ts.tzinfo:
        ts = ts.replace(tzinfo=dt.timezone.utc)
    return now_utc() - ts.astimezone(dt.timezone.utc) <= dt.timedelta(days=days)


_HUMAN_DATE_FORMATS = [
    "%b %d, %Y",       # Mar 25, 2026
    "%b %d %Y",         # Mar 25 2026
    "%B %d, %Y",        # March 25, 2026
    "%B %d %Y",          # March 25 2026
    "%d %b %Y",          # 25 Mar 2026
    "%d %B %Y",          # 25 March 2026
    "%d %b, %Y",         # 25 Mar, 2026
    "%Y-%m-%dT%H:%M:%S",  # 2026-03-25T10:30:00
    "%Y-%m-%d %H:%M:%S",  # 2026-03-25 10:30:00
]


def parse_date_any(value: str) -> Optional[dt.datetime]:
    if not value:
        return None
    v = value.strip()
    # ISO 8601
    iso = v.replace('Z', '+00:00')
    try:
        d = dt.datetime.fromisoformat(iso)
        if not d.tzinfo:
            d = d.replace(tzinfo=dt.timezone.utc)
        return d.astimezone(dt.timezone.utc)
    except Exception:
        pass
    # RFC 2822 (RSS feeds, email headers)
    try:
        d = parsedate_to_datetime(v)
        if d:
            if not d.tzinfo:
                d = d.replace(tzinfo=dt.timezone.utc)
            return d.astimezone(dt.timezone.utc)
    except Exception:
        pass
    # Human-readable formats: "Mar 25, 2026", "March 25 2026", etc.
    for fmt in _HUMAN_DATE_FORMATS:
        try:
            d = dt.datetime.strptime(v, fmt).replace(tzinfo=dt.timezone.utc)
            return d
        except ValueError:
            continue
    # Regex fallback: 2026-03-25 or 2026/03/25
    m = re.search(r'(20\d{2})[-/](\d{1,2})[-/](\d{1,2})', v)
    if m:
        try:
            return dt.datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=dt.timezone.utc)
        except Exception:
            return None
    return None
