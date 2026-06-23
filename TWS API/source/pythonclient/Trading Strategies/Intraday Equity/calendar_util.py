"""US equity-market calendar + Eastern-Time helpers (stdlib only, PyInstaller-friendly).

ALL wall-clock logic in the intraday bots MUST route through here so trade windows,
the opening-range bar, EOD flatten, and RVOL bucketing stay anchored to
America/New_York regardless of the host machine's local timezone.
(Adversarial-review must-fix: ic.py used naive datetime.now() = local time.)

Note: zoneinfo needs the `tzdata` package bundled on Windows (see requirements.txt /
PyInstaller .spec) or ZoneInfoNotFoundError is raised at runtime.
"""
from __future__ import annotations
import datetime as _dt

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    from backports.zoneinfo import ZoneInfo  # type: ignore

ET = ZoneInfo("America/New_York")

# NYSE/Nasdaq full-holiday closures (extend each year). Format YYYY-MM-DD (ET).
_HOLIDAYS = {
    "2025-01-01", "2025-01-20", "2025-02-17", "2025-04-18", "2025-05-26",
    "2025-06-19", "2025-07-04", "2025-09-01", "2025-11-27", "2025-12-25",
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25",
    "2026-06-19", "2026-07-03", "2026-09-07", "2026-11-26", "2026-12-25",
    "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26", "2027-05-31",
    "2027-06-18", "2027-07-05", "2027-09-06", "2027-11-25", "2027-12-24",
}
# Early-close days: regular session ends 13:00 ET.
_HALF_DAYS = {
    "2025-07-03", "2025-11-28", "2025-12-24",
    "2026-11-27", "2026-12-24",
    "2027-11-26",
}


def now_et() -> _dt.datetime:
    return _dt.datetime.now(tz=ET)


def _key(d: _dt.datetime) -> str:
    return d.strftime("%Y-%m-%d")


def is_trading_day(d: _dt.datetime | None = None) -> bool:
    d = d or now_et()
    if d.weekday() >= 5:  # Sat/Sun
        return False
    return _key(d) not in _HOLIDAYS


def is_half_day(d: _dt.datetime | None = None) -> bool:
    d = d or now_et()
    return _key(d) in _HALF_DAYS


def session_open(d: _dt.datetime | None = None) -> _dt.datetime:
    d = d or now_et()
    return d.replace(hour=9, minute=30, second=0, microsecond=0)


def session_close(d: _dt.datetime | None = None) -> _dt.datetime:
    d = d or now_et()
    hour = 13 if is_half_day(d) else 16
    return d.replace(hour=hour, minute=0, second=0, microsecond=0)


def at_et(hhmm: str, d: _dt.datetime | None = None) -> _dt.datetime:
    """Today's ET datetime for an 'HH:MM' string."""
    d = d or now_et()
    h, m = map(int, hhmm.split(":"))
    return d.replace(hour=h, minute=m, second=0, microsecond=0)


def effective_flatten_time(configured_hhmm: str, d: _dt.datetime | None = None) -> _dt.datetime:
    """EOD flatten time, pulled earlier on half-days so we never flatten post-close.
    Always at least 5 minutes before the session close."""
    d = d or now_et()
    cfg = at_et(configured_hhmm, d)
    cutoff = session_close(d) - _dt.timedelta(minutes=5)
    return min(cfg, cutoff)


def in_window(start_hhmm: str, end_hhmm: str, d: _dt.datetime | None = None) -> bool:
    d = d or now_et()
    return at_et(start_hhmm, d) <= d <= at_et(end_hhmm, d)
