"""US equity market hours helper.

Regular session: 09:30 - 16:00 America/New_York, Monday through Friday.
Covers full-day holidays for 2025/2026 out of the box. Swap in
``pandas_market_calendars`` if you need early-close / extended coverage.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Optional

import pytz

_TZ = pytz.timezone("America/New_York")
_OPEN = time(9, 30)
_CLOSE = time(16, 0)

_HOLIDAYS = {
    # 2025
    "2025-01-01", "2025-01-20", "2025-02-17", "2025-04-18", "2025-05-26",
    "2025-06-19", "2025-07-04", "2025-09-01", "2025-11-27", "2025-12-25",
    # 2026
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25",
    "2026-06-19", "2026-07-03", "2026-09-07", "2026-11-26", "2026-12-25",
}


def now_et(ref: Optional[datetime] = None) -> datetime:
    if ref is None:
        return datetime.now(_TZ)
    return ref.astimezone(_TZ) if ref.tzinfo else _TZ.localize(ref)


def _is_trading_day(t: datetime) -> bool:
    return t.weekday() < 5 and t.strftime("%Y-%m-%d") not in _HOLIDAYS


def is_market_open(ref: Optional[datetime] = None) -> bool:
    t = now_et(ref)
    return _is_trading_day(t) and _OPEN <= t.time() < _CLOSE


def next_open(ref: Optional[datetime] = None) -> datetime:
    t = now_et(ref)
    candidate = t.replace(hour=_OPEN.hour, minute=_OPEN.minute, second=0, microsecond=0)
    if t.time() >= _OPEN:
        candidate = candidate + timedelta(days=1)
    while not _is_trading_day(candidate):
        candidate = candidate + timedelta(days=1)
    return candidate
