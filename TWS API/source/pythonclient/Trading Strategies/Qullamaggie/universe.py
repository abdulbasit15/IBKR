#!/usr/bin/env python3
"""
Full US stock universe (pure stdlib) for the Qullamaggie screener / backtest.

Pulls the complete Nasdaq + NYSE + AMEX common-stock list from
api.nasdaq.com's screener (reachable on this machine), with symbol, name,
last price and market cap. The raw list is cached locally so repeated runs
don't re-hit the network; filtering is done in-memory.

This removes the survivorship bias of a hand-picked "today's winners" list:
you scan the whole market and let the momentum/ADR filters do the selecting.

Filters tuned for Qullamaggie's actual universe -- small/mid-cap movers, not
mega-caps or illiquid sub-$10 names:
    min-cap  ~ $300M     (tradable, not a microcap shell)
    max-cap  ~ optional  (0 = no cap; set e.g. 30000 to drop mega-caps)
    min-price ~ $10

Standalone:
    python universe.py                         # summary of the filtered list
    python universe.py --out us_universe.txt   # write one symbol per line
    python universe.py --min-cap-m 300 --max-cap-m 20000 --min-price 10
    python universe.py --refresh               # force re-download

As a module:
    from universe import get_us_universe
    syms = get_us_universe(min_cap_m=300, max_cap_m=0, min_price=10)
"""

import argparse
import csv
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error

NASDAQ_SCREENER = ("https://api.nasdaq.com/api/screener/stocks"
                   "?tableonly=true&limit=10000&offset=0")
UA = {"User-Agent": "Mozilla/5.0 (universe; stdlib urllib)",
      "Accept": "application/json"}

CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "universe_us_raw.csv")
CACHE_MAX_AGE_H = 24

# names we don't want as "stocks" to trade like equities
_BAD_NAME = re.compile(
    r"\b(warrant|unit|right|preferred|depositary|notes?|debenture|"
    r"trust preferred|% |etf|fund)\b", re.I)
_SYM_OK = re.compile(r"^[A-Z]{1,5}$")   # plain common-stock tickers only


def _num(s):
    """'$224.58' / '5,412,378,000,000' / 'N/A' -> float or None."""
    if not s:
        return None
    t = s.replace("$", "").replace(",", "").strip()
    if not t or t.upper() in ("N/A", "NA", "--"):
        return None
    try:
        return float(t)
    except ValueError:
        return None


def fetch_nasdaq_screener(timeout=40):
    """Return list of {symbol, name, price, cap_m} for all US stocks."""
    req = urllib.request.Request(NASDAQ_SCREENER, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        j = json.loads(r.read().decode("utf-8", "replace"))
    rows = j.get("data", {}).get("table", {}).get("rows") or []
    out = []
    for row in rows:
        sym = (row.get("symbol") or "").strip().upper()
        cap = _num(row.get("marketCap"))
        price = _num(row.get("lastsale"))
        out.append({"symbol": sym, "name": (row.get("name") or "").strip(),
                    "price": price, "cap_m": (cap / 1e6) if cap else None})
    return out


def _write_cache(rows):
    with open(CACHE, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["symbol", "name", "price", "cap_m"])
        w.writeheader()
        w.writerows(rows)


def _read_cache():
    with open(CACHE, encoding="utf-8") as f:
        out = []
        for r in csv.DictReader(f):
            out.append({"symbol": r["symbol"], "name": r["name"],
                        "price": _num(r["price"]), "cap_m": _num(r["cap_m"])})
        return out


def load_raw(refresh=False, max_age_h=CACHE_MAX_AGE_H):
    """Load the full raw list, refreshing the cache when stale/missing."""
    fresh = (os.path.exists(CACHE)
             and (time.time() - os.path.getmtime(CACHE)) < max_age_h * 3600)
    if fresh and not refresh:
        try:
            rows = _read_cache()
            if rows:
                return rows
        except (OSError, csv.Error):
            pass
    rows = fetch_nasdaq_screener()
    if rows:
        try:
            _write_cache(rows)
        except OSError:
            pass
    return rows


def filter_universe(rows, min_cap_m=300.0, max_cap_m=0.0, min_price=10.0,
                    exclude_funds=True):
    """Apply Qullamaggie-style universe filters. max_cap_m=0 -> no upper cap."""
    out = []
    for r in rows:
        sym = r["symbol"]
        if not sym or not _SYM_OK.match(sym):
            continue
        if exclude_funds and _BAD_NAME.search(r.get("name", "")):
            continue
        cap, price = r["cap_m"], r["price"]
        if cap is None or cap < min_cap_m:
            continue
        if max_cap_m and cap > max_cap_m:
            continue
        if price is not None and price < min_price:
            continue
        out.append(sym)
    return sorted(set(out))


def get_us_universe(min_cap_m=300.0, max_cap_m=0.0, min_price=10.0,
                    refresh=False, exclude_funds=True):
    """Convenience: full US common-stock universe after filters."""
    return filter_universe(load_raw(refresh=refresh),
                           min_cap_m=min_cap_m, max_cap_m=max_cap_m,
                           min_price=min_price, exclude_funds=exclude_funds)


def main():
    p = argparse.ArgumentParser(description="Build the full US stock universe")
    p.add_argument("--min-cap-m", type=float, default=300.0, help="min market cap ($M)")
    p.add_argument("--max-cap-m", type=float, default=0.0, help="max market cap ($M); 0=none")
    p.add_argument("--min-price", type=float, default=10.0)
    p.add_argument("--include-funds", action="store_true", help="keep ETFs/units/warrants")
    p.add_argument("--refresh", action="store_true", help="force re-download")
    p.add_argument("--out", help="write filtered symbols, one per line")
    a = p.parse_args()

    raw = load_raw(refresh=a.refresh)
    syms = filter_universe(raw, min_cap_m=a.min_cap_m, max_cap_m=a.max_cap_m,
                           min_price=a.min_price, exclude_funds=not a.include_funds)
    age = (time.time() - os.path.getmtime(CACHE)) / 3600 if os.path.exists(CACHE) else 0
    print(f"raw universe    : {len(raw)} rows  (cache age {age:.1f}h -> {CACHE})",
          file=sys.stderr)
    print(f"after filters   : {len(syms)} symbols "
          f"(cap>={a.min_cap_m:.0f}M"
          f"{', cap<=%.0fM' % a.max_cap_m if a.max_cap_m else ''}, "
          f"price>={a.min_price:.0f})", file=sys.stderr)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write("\n".join(syms) + "\n")
        print(f"wrote {a.out}", file=sys.stderr)
    else:
        print(" ".join(syms[:60]) + (" ..." if len(syms) > 60 else ""))


if __name__ == "__main__":
    main()
