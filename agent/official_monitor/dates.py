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


def parse_date_any(value: str) -> Optional[dt.datetime]:
    if not value:
        return None
    v = value.strip()
    iso = v.replace('Z', '+00:00')
    try:
        d = dt.datetime.fromisoformat(iso)
        if not d.tzinfo:
            d = d.replace(tzinfo=dt.timezone.utc)
        return d.astimezone(dt.timezone.utc)
    except Exception:
        pass
    try:
        d = parsedate_to_datetime(v)
        if d:
            if not d.tzinfo:
                d = d.replace(tzinfo=dt.timezone.utc)
            return d.astimezone(dt.timezone.utc)
    except Exception:
        pass
    m = re.search(r'(20\d{2})[-/](\d{1,2})[-/](\d{1,2})', v)
    if m:
        try:
            return dt.datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=dt.timezone.utc)
        except Exception:
            return None
    return None
