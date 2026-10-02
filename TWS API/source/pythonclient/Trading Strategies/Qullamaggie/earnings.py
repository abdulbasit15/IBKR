#!/usr/bin/env python3
"""
Earnings calendar (pure stdlib) for the Qullamaggie EP (Episodic Pivot) setup.

EP is a catalyst play: a stock gaps up on an earnings beat. To confirm the catalyst
live we pull the Nasdaq earnings calendar (reachable on this machine, same API family
the trade journal already uses for economic events).

A stock that gaps up THIS morning either:
  * reported AFTER the close on the previous trading day, or
  * reported PRE-MARKET this morning.
So `recent_earnings(today)` merges the previous trading day + today and returns a
dict: symbol -> {"time", "surprise", "eps", "eps_forecast", "date"}.

Standalone:
    python earnings.py                 # today + prev trading day
    python earnings.py --date 2026-09-25
"""
import argparse
import json
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
URL = "https://api.nasdaq.com/api/calendar/earnings?date={date}"
UA = {"User-Agent": "Mozilla/5.0 (earnings; stdlib urllib)", "Accept": "application/json"}

_CACHE = {}   # date_str -> {sym: info}


def _num(s):
    if s is None:
        return None
    t = str(s).replace("$", "").replace(",", "").replace("%", "").strip()
    if not t or t.upper() in ("N/A", "NA", "--", "(N/A)"):
        return None
    neg = t.startswith("(") and t.endswith(")")
    t = t.strip("()")
    try:
        v = float(t)
        return -v if neg else v
    except ValueError:
        return None


def fetch_earnings(date_str, timeout=30):
    """Return {symbol: info} for one calendar date (cached per date)."""
    if date_str in _CACHE:
        return _CACHE[date_str]
    out = {}
    try:
        req = urllib.request.Request(URL.format(date=date_str), headers=UA)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            j = json.loads(r.read().decode("utf-8", "replace"))
        rows = (j.get("data") or {}).get("rows") or []
        for row in rows:
            sym = (row.get("symbol") or "").strip().upper()
            if not sym:
                continue
            out[sym] = {
                "time": row.get("time", ""),
                "surprise": _num(row.get("surprise")),
                "eps": _num(row.get("eps")),
                "eps_forecast": _num(row.get("epsForecast")),
                "date": date_str,
            }
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError,
            ValueError, TimeoutError):
        pass
    _CACHE[date_str] = out
    return out


def _prev_trading_day(d):
    d = d - timedelta(days=1)
    while d.weekday() >= 5:            # skip Sat/Sun (holidays not handled -> harmless extra day)
        d = d - timedelta(days=1)
    return d


def recent_earnings(today=None):
    """Symbols that could gap THIS morning: prev-trading-day after-hours + today pre-market.
    Merged dict symbol -> info. today = a date (defaults to now ET)."""
    if today is None:
        today = datetime.now(ET).date()
    prev = _prev_trading_day(today)
    merged = {}
    # previous day first, today second so today's (fresher) info wins on overlap
    for d in (prev, today):
        for sym, info in fetch_earnings(d.strftime("%Y-%m-%d")).items():
            merged[sym] = info
    return merged


def main():
    p = argparse.ArgumentParser(description="Nasdaq earnings calendar")
    p.add_argument("--date", help="YYYY-MM-DD (default: today + prev trading day merged)")
    a = p.parse_args()
    if a.date:
        data = fetch_earnings(a.date)
        print(f"{a.date}: {len(data)} symbols")
    else:
        data = recent_earnings()
        print(f"recent (today + prev trading day): {len(data)} symbols")
    for sym, info in sorted(data.items()):
        print(f"  {sym:<6} {info['time']:<20} surprise={info['surprise']} "
              f"eps={info['eps']} fcast={info['eps_forecast']} ({info['date']})")


if __name__ == "__main__":
    main()
