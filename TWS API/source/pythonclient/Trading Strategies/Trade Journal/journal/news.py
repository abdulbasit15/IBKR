"""Economic calendar / news context from the free ForexFactory JSON mirror.

Note: the free feed only covers the current week, so historical trades outside
that window will have no events. This is surfaced honestly in the output.
"""
from __future__ import annotations

import json
import urllib.request
from datetime import date, datetime

from . import config

# Currencies whose events move the instruments this journal tracks.
RELEVANT_CCY = {"USD"}
RELEVANT_IMPACT = {"High", "Medium"}

_cache: list[dict] | None = None


def _load() -> list[dict]:
    """Load the ForexFactory week feed with retries; don't cache failures."""
    global _cache
    if _cache:                      # only cache a non-empty success
        return _cache
    import time
    for attempt in range(3):
        try:
            req = urllib.request.Request(config.FF_CALENDAR_URL,
                                         headers={"User-Agent": config.HTTP_UA})
            with urllib.request.urlopen(req, timeout=config.HTTP_TIMEOUT) as r:
                data = json.loads(r.read())
            if data:
                _cache = data
                return _cache
        except Exception:
            pass
        time.sleep(2 * (attempt + 1))
    return []                       # transient failure — leave uncached for retry


def _event_date(ev) -> date | None:
    try:
        return datetime.fromisoformat(ev["date"]).date()
    except Exception:
        return None


def events_for_day(d: date) -> list[dict]:
    if isinstance(d, datetime):
        d = d.date()
    out = []
    for ev in _load():
        if ev.get("country") not in RELEVANT_CCY:
            continue
        if ev.get("impact") not in RELEVANT_IMPACT:
            continue
        if _event_date(ev) == d:
            out.append({
                "time": ev["date"][11:16] if len(ev.get("date", "")) >= 16 else "",
                "title": ev.get("title", ""),
                "impact": ev.get("impact", ""),
                "forecast": ev.get("forecast", ""),
                "previous": ev.get("previous", ""),
            })
    return out


def upcoming_week(currencies=None, impacts=None) -> list[dict]:
    """All calendar events in the current-week feed, filtered and sorted."""
    ccy = currencies or RELEVANT_CCY
    imp = impacts or RELEVANT_IMPACT
    out = []
    for ev in _load():
        if ev.get("country") not in ccy or ev.get("impact") not in imp:
            continue
        out.append({
            "date": ev.get("date", "")[:10],
            "time": ev.get("date", "")[11:16],
            "country": ev.get("country", ""),
            "title": ev.get("title", ""),
            "impact": ev.get("impact", ""),
            "forecast": ev.get("forecast", ""),
            "previous": ev.get("previous", ""),
        })
    out.sort(key=lambda e: (e["date"], e["time"]))
    return out


def all_events() -> list[dict]:
    """Every event in the current-week feed (all currencies, all impacts)."""
    out = []
    for ev in _load():
        out.append({
            "date": ev.get("date", "")[:10],
            "time": ev.get("date", "")[11:16],
            "country": ev.get("country", ""),
            "title": ev.get("title", ""),
            "impact": ev.get("impact", ""),
            "forecast": ev.get("forecast", ""),
            "previous": ev.get("previous", ""),
        })
    out.sort(key=lambda e: (e["date"], e["time"]))
    return out


def feed_window() -> dict:
    """The date span the current free feed covers (for honest UI messaging)."""
    dates = sorted({_event_date(ev) for ev in _load() if _event_date(ev)})
    return {"start": str(dates[0]) if dates else None,
            "end": str(dates[-1]) if dates else None,
            "count": len(_load())}


# --- Historical major events (Nasdaq economic calendar) ------------------
NASDAQ_URL = "https://api.nasdaq.com/api/calendar/economicevents?date={date}"
_nasdaq_cache: dict[str, list] = {}

# (keywords, canonical label, impact) — first match wins. High = market movers.
_RULES = [
    (["core pce", "pce price"], "PCE", "High"),
    (["cpi"], "CPI", "High"),
    (["ppi"], "PPI", "High"),
    (["gdp"], "GDP", "High"),
    (["nonfarm", "non-farm", "payroll"], "Payrolls", "High"),
    (["fomc meeting minutes", "fomc minutes"], "FOMC Minutes", "High"),
    (["interest rate decision", "rate decision", "fed funds"], "Fed Rate Decision", "High"),
    (["retail sales"], "Retail Sales", "High"),
    (["ism manufacturing", "ism services", "ism non-manufacturing"], "ISM", "High"),
    (["unemployment rate"], "Unemployment Rate", "High"),
    (["fed chair", "powell", "chairman", "warsh speaks"], "Fed Chair Speaks", "High"),
    (["fomc member", "goolsbee", "barkin", "williams", "waller", "bowman",
      "fed's", "fed governor", "fed logan", "fed daly", "fed bostic"], "Fed Speaker", "Medium"),
    (["initial jobless", "continuing jobless", "jobless claims"], "Jobless Claims", "Medium"),
    (["consumer confidence", "consumer sentiment", "michigan"], "Consumer Sentiment", "Medium"),
    (["durable goods"], "Durable Goods", "Medium"),
    (["crude oil inventories"], "Crude Oil Inventories", "Medium"),
    (["empire state", "philadelphia fed", "philly fed"], "Regional Fed Mfg", "Medium"),
    (["housing starts", "building permits", "existing home", "new home sales", "nahb"], "Housing", "Medium"),
    (["adp employment"], "ADP Employment", "Medium"),
    (["president", "trump speaks"], "Presidential Remarks", "Medium"),
]
_IMP_ORDER = {"High": 0, "Medium": 1, "Low": 2}


def _clean(v) -> str:
    s = str(v or "").replace("\xa0", " ").replace("&nbsp;", " ").strip()
    return s


def _match_rule(name: str):
    ln = name.lower()
    for kws, label, impact in _RULES:
        if any(k in ln for k in kws):
            return label, impact
    return None


def nasdaq_events(d: str) -> list[dict]:
    if d in _nasdaq_cache:
        return _nasdaq_cache[d]
    rows = []
    try:
        req = urllib.request.Request(
            NASDAQ_URL.format(date=d),
            headers={"User-Agent": config.HTTP_UA, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=config.HTTP_TIMEOUT) as r:
            j = json.loads(r.read())
        rows = ((j.get("data") or {}).get("rows")) or []
    except Exception:
        rows = []
    _nasdaq_cache[d] = rows
    return rows


def major_events_by_day(dates, country: str = "United States") -> dict:
    """{date: [major events]} classified from Nasdaq's historical calendar."""
    out = {}
    for d in dates:
        seen = {}
        for r in nasdaq_events(d):
            if r.get("country") != country:
                continue
            m = _match_rule(r.get("eventName", ""))
            if not m:
                continue
            label, impact = m
            if label in seen:
                continue
            seen[label] = {
                "time": _clean(r.get("gmt")), "label": label, "impact": impact,
                "event": _clean(r.get("eventName")),
                "actual": _clean(r.get("actual")),
                "forecast": _clean(r.get("consensus")),
                "previous": _clean(r.get("previous")),
            }
        if seen:
            out[d] = sorted(seen.values(),
                            key=lambda e: (_IMP_ORDER[e["impact"]], e["time"]))
    return out


def summarize_days(trades) -> dict:
    """{date_str: [events]} for each traded day within the available window."""
    out = {}
    covered = {_event_date(ev) for ev in _load()}
    for t in trades:
        if t.date is None:
            continue
        d = t.date.date() if isinstance(t.date, datetime) else t.date
        key = str(d)
        if key in out:
            continue
        if d in covered:
            out[key] = events_for_day(d)
        else:
            out[key] = None  # outside the free feed's window
    return out
