"""ICT Killzones — shared, reusable by any strategy.

Killzones are the intraday time windows ICT traders watch for the day's high-probability
moves. Times are New York (America/New_York) clock times. Defaults (ICT / TFO style):

    Asian        20:00 - 00:00     (accumulation / range)
    London       02:00 - 05:00     (London open killzone)
    NY AM        07:00 - 10:00     (New York AM killzone)
    London Close 10:00 - 12:00
    NY PM        13:30 - 16:00

This is a TIME tool, not a price calculation: given a timestamp it tells you which killzone
(if any) is active. Windows are configurable; a window may wrap past midnight (the Asian one).

Two layers:

1. Pure: ``killzone_at(dt, zones=None)`` -> the active killzone name (or None) for a datetime.
2. Config-driven value: ``killzone_value(...)`` -> KillzoneResult for the last bar's timestamp.

Pure-Python (only stdlib datetime / zoneinfo) so it bundles cleanly into a one-file exe.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from zoneinfo import ZoneInfo

from ..market_data import fetch_bars

ET = ZoneInfo("America/New_York")

DEFAULT_ZONES = [
    ("Asian", time(20, 0), time(0, 0)),
    ("London", time(2, 0), time(5, 0)),
    ("NY AM", time(7, 0), time(10, 0)),
    ("London Close", time(10, 0), time(12, 0)),
    ("NY PM", time(13, 30), time(16, 0)),
]


def _in_window(t, start, end):
    """True if time-of-day `t` is within [start, end); handles a window that wraps midnight."""
    if start <= end:
        return start <= t < end
    return t >= start or t < end   # wraps past midnight


def killzone_at(dt, zones=None):
    """Return the name of the active killzone for datetime `dt` (converted to ET when it is
    timezone-aware; assumed already ET if naive), or None if outside every window."""
    if zones is None:
        zones = DEFAULT_ZONES
    if dt is None:
        return None
    if getattr(dt, "tzinfo", None) is not None:
        dt = dt.astimezone(ET)
    t = dt.time()
    for name, start, end in zones:
        if _in_window(t, start, end):
            return name
    return None


@dataclass
class KillzoneResult:
    zone: str            # active killzone name, or "" if none
    active: bool         # inside any killzone
    close: float
    time: object = None

    def __bool__(self) -> bool:
        return self.active


def killzone_value(symbol=None, bar_size="15 mins", *, zones=None, ib=None, bars=None,
                   duration=None, use_rth=False, what="TRADES", exchange="SMART",
                   currency="USD", throttle=None, completed=True):
    """Killzone active on the last (completed) bar as a KillzoneResult, or None if there are no
    bars. Use ``use_rth=False`` so pre/post-market killzones are visible. Provide EITHER
    ``bars`` OR ``ib`` + ``symbol``."""
    if bars is None:
        if ib is None or symbol is None:
            raise ValueError("killzone_value needs bars=..., or ib=... and symbol=...")
        bars = fetch_bars(ib, symbol, bar_size, duration=duration, use_rth=use_rth,
                          what=what, exchange=exchange, currency=currency, throttle=throttle)
    if not bars:
        return None
    i = len(bars) - (2 if completed else 1)
    if i < 0:
        return None
    bar = bars[i]
    name = killzone_at(bar.date, zones)
    return KillzoneResult(zone=name or "", active=name is not None, close=bar.close, time=bar.date)
