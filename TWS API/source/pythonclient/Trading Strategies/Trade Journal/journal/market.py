"""Fetch daily market context per instrument/day from Yahoo Finance (stdlib only)."""
from __future__ import annotations

import json
import urllib.request
from datetime import date, datetime, timedelta

from . import config

_cache: dict[tuple, dict] = {}


def _http_json(url: str) -> dict | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": config.HTTP_UA})
        with urllib.request.urlopen(req, timeout=config.HTTP_TIMEOUT) as r:
            return json.loads(r.read())
    except Exception:
        return None


def _fetch_series(ticker: str) -> list[dict]:
    """Return recent daily bars [{date, open, high, low, close, volume}]."""
    if ticker in _cache:
        return _cache[ticker]
    url = config.YAHOO_CHART_URL.format(ticker=ticker) + "?range=1mo&interval=1d"
    data = _http_json(url)
    bars: list[dict] = []
    try:
        res = data["chart"]["result"][0]
        ts = res["timestamp"]
        q = res["indicators"]["quote"][0]
        for i, t in enumerate(ts):
            o, h, l, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
            if None in (o, h, l, c):
                continue
            bars.append({
                "date": datetime.utcfromtimestamp(t).date(),
                "open": o, "high": h, "low": l, "close": c,
                "volume": (q.get("volume") or [None])[i] if q.get("volume") else None,
            })
    except (KeyError, TypeError, IndexError):
        pass
    _cache[ticker] = bars
    return bars


def day_context(asset: str, d: date) -> dict | None:
    """Market context for one instrument on one day."""
    ticker = config.YAHOO_MAP.get(asset.upper())
    if not ticker:
        return None
    bars = _fetch_series(ticker)
    if not bars:
        return None
    if isinstance(d, datetime):
        d = d.date()
    idx = next((i for i, b in enumerate(bars) if b["date"] == d), None)
    if idx is None:  # exact day not in the free window
        return {"ticker": ticker, "available": False}
    bar = bars[idx]
    prev = bars[idx - 1] if idx > 0 else None
    rng = bar["high"] - bar["low"]
    body = bar["close"] - bar["open"]
    gap = (bar["open"] - prev["close"]) if prev else None
    # 10-day ATR-ish average range up to this day
    window = bars[max(0, idx - 10):idx] or [bar]
    avg_rng = sum(b["high"] - b["low"] for b in window) / len(window)
    return {
        "ticker": ticker, "available": True, "date": str(d),
        "open": bar["open"], "high": bar["high"], "low": bar["low"],
        "close": bar["close"], "range": round(rng, 4),
        "day_direction": "up" if body > 0 else ("down" if body < 0 else "flat"),
        "body_pct_of_range": round(abs(body) / rng, 2) if rng else None,
        "gap": round(gap, 4) if gap is not None else None,
        "avg_range_10d": round(avg_rng, 4),
        "range_vs_avg": round(rng / avg_rng, 2) if avg_rng else None,
    }


def summarize_days(trades) -> dict:
    """Build {(asset,date): context} for the distinct instrument-days traded."""
    out = {}
    for t in trades:
        if t.date is None:
            continue
        d = t.date.date() if isinstance(t.date, datetime) else t.date
        key = (t.asset, str(d))
        if key not in out:
            out[key] = day_context(t.asset, d)
    return out


# --- Intraday 5-minute candles -------------------------------------------
import calendar as _calendar

ET_OFFSET_HOURS = -4          # US Eastern (EDT) — valid for the summer dates traded
_intraday_cache: dict[tuple, list] = {}


def et_epoch(dt: datetime) -> int:
    """Epoch seconds for a naive datetime interpreted as US Eastern time."""
    return _calendar.timegm(dt.timetuple()) - ET_OFFSET_HOURS * 3600


def intraday_bars(asset: str, d, interval: str = "5m") -> list[list]:
    """5-min OHLC bars covering the ET trading day for (asset, date).

    Returns a compact list of [epoch, open, high, low, close]. Cached per
    (ticker, date). The window spans the ET calendar day plus the overnight
    into the next morning, so evening (Globex) trades are included.
    """
    ticker = config.YAHOO_MAP.get(asset.upper())
    if not ticker:
        return []
    if isinstance(d, datetime):
        d = d.date()
    key = (ticker, str(d), interval)
    if key in _intraday_cache:
        return _intraday_cache[key]

    start = et_epoch(datetime(d.year, d.month, d.day, 0, 0))
    end = start + 32 * 3600                       # ET day + 8h overnight
    url = (config.YAHOO_CHART_URL.format(ticker=ticker)
           + f"?period1={start - 6*3600}&period2={end + 6*3600}&interval={interval}")
    data = _http_json(url)
    bars: list[list] = []
    try:
        res = data["chart"]["result"][0]
        ts = res["timestamp"]
        q = res["indicators"]["quote"][0]
        for i, t in enumerate(ts):
            if not (start <= t < end):
                continue
            o, h, l, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
            if None in (o, h, l, c):
                continue
            bars.append([int(t), round(o, 4), round(h, 4), round(l, 4), round(c, 4)])
    except (KeyError, TypeError, IndexError):
        pass
    _intraday_cache[key] = bars
    return bars


def summarize_intraday(trades) -> dict:
    """{'ASSET|YYYY-MM-DD': [[epoch,o,h,l,c],...]} for each instrument-day."""
    out = {}
    for t in trades:
        if t.date is None:
            continue
        d = t.date.date() if isinstance(t.date, datetime) else t.date
        key = f"{t.asset}|{d}"
        if key not in out:
            out[key] = intraday_bars(t.asset, d)
    return out
