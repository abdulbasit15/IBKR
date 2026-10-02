#!/usr/bin/env python3
"""
Qullamaggie-style momentum screener  (pure stdlib -- no PyPI needed).

Replicates how Kristjan "Qullamaggie" Kullamagi builds his watchlist:
  1. A big prior move          -> % gain over the last ~1 / 3 / 6 months
  2. High volatility / range   -> ADR% (Average Daily Range, his key metric)
  3. Sitting near its highs     -> distance from the 52-week high
  4. In an uptrend             -> price above the 20 / 50 / 200-day SMAs
  5. Tradable liquidity        -> price and average $ volume floors

It fetches daily bars from Yahoo (primary) or Stooq (fallback) via urllib,
computes the metrics, applies hard filters, then ranks the survivors.

The screener only produces a WATCHLIST. The actual setup -- the tight
consolidation / higher-lows contraction after the run, and the breakout
trigger -- is judged by eye on the daily chart. No screen replaces that.

Usage:
    python qm_screener.py                         # default built-in universe
    python qm_screener.py --tickers mylist.txt    # one symbol per line
    python qm_screener.py --min-adr 5 --min-perf3m 30 --top 40
    python qm_screener.py --source stooq          # force data source
    python qm_screener.py --out watchlist.csv     # also write a CSV

No external packages. Reachable endpoints assumed: query1.finance.yahoo.com,
stooq.com  (matches this machine's network constraints).
"""

import argparse
import csv
import json
import sys
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

# ----------------------------------------------------------------------------
# Default universe: liquid US momentum / growth names to run out-of-the-box.
# Replace with a bigger list via --tickers for a real market-wide scan.
# ----------------------------------------------------------------------------
DEFAULT_UNIVERSE = [
    # mega/large growth
    "NVDA", "AMD", "TSLA", "META", "AVGO", "MSFT", "AAPL", "AMZN", "GOOGL",
    "NFLX", "CRM", "SMCI", "MU", "MRVL", "ARM", "PLTR", "SNOW", "DDOG",
    "CRWD", "PANW", "NET", "ZS", "MDB", "SHOP", "UBER", "ABNB", "COIN",
    "HOOD", "SOFI", "AFRM", "RBLX", "DKNG", "CVNA", "APP", "DASH", "TTD",
    # semis / AI adjacency
    "TSM", "ASML", "LRCX", "KLAC", "AMAT", "ON", "ANET", "DELL", "VRT",
    "CLS", "NBIS", "ALAB", "CRDO", "TEM", "IONQ", "RGTI",
    # energy / uranium / commodities momentum
    "CCJ", "UEC", "OKLO", "SMR", "VST", "TLN", "CEG", "GEV", "FSLR",
    # biotech / small-cap runners (illustrative)
    "VKTX", "CRSP", "RXRX", "TGTX",
    # crypto miners / high-beta
    "MARA", "RIOT", "CLSK", "MSTR", "BITF",
    # recent IPO / high momentum
    "RDDT", "ASTS", "RKLB", "SERV", "AISP", "CRWV",
]

YQ = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=1y&interval=1d"
STOOQ = "https://stooq.com/q/d/l/?s={sym}.us&i=d"
UA = {"User-Agent": "Mozilla/5.0 (screener; stdlib urllib)"}

TRADING_DAYS_1M = 21
TRADING_DAYS_3M = 63
TRADING_DAYS_6M = 126
TRADING_DAYS_1Y = 252


# ----------------------------------------------------------------------------
# Data fetch
# ----------------------------------------------------------------------------
def _http(url, timeout=15, retries=2):
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code in (429, 502, 503) and attempt < retries:
                time.sleep(1.0 + attempt)   # brief backoff on throttle
                continue
            raise


def fetch_yahoo(sym):
    """Return list of dicts {o,h,l,c,v} oldest->newest, or None."""
    raw = _http(YQ.format(sym=sym))
    j = json.loads(raw)
    res = j.get("chart", {}).get("result")
    if not res:
        return None
    r0 = res[0]
    q = r0["indicators"]["quote"][0]
    ts = r0.get("timestamp") or []
    o, h, l, c, v = (q.get(k) or [] for k in ("open", "high", "low", "close", "volume"))
    bars = []
    for i in range(len(ts)):
        try:
            oi, hi, li, ci, vi = o[i], h[i], l[i], c[i], v[i]
        except IndexError:
            continue
        if None in (hi, li, ci) or ci == 0:
            continue
        bars.append({"o": oi or ci, "h": hi, "l": li, "c": ci, "v": vi or 0})
    return bars or None


def fetch_stooq(sym):
    raw = _http(STOOQ.format(sym=sym.lower()))
    rows = list(csv.DictReader(raw.splitlines()))
    if not rows or "Close" not in (rows[0] if rows else {}):
        return None
    bars = []
    for r in rows:
        try:
            bars.append({
                "o": float(r["Open"]), "h": float(r["High"]),
                "l": float(r["Low"]), "c": float(r["Close"]),
                "v": float(r.get("Volume") or 0),
            })
        except (ValueError, KeyError):
            continue
    return bars[-TRADING_DAYS_1Y - 5:] or None


def fetch(sym, source):
    order = {"yahoo": (fetch_yahoo, fetch_stooq),
             "stooq": (fetch_stooq, fetch_yahoo),
             "auto": (fetch_yahoo, fetch_stooq)}[source]
    for fn in order:
        try:
            b = fn(sym)
            if b and len(b) >= 30:
                return b
        except (urllib.error.URLError, urllib.error.HTTPError,
                json.JSONDecodeError, KeyError, ValueError, TimeoutError):
            continue
    return None


# ----------------------------------------------------------------------------
# Metrics
# ----------------------------------------------------------------------------
def _sma(vals, n):
    return sum(vals[-n:]) / n if len(vals) >= n else None


def _perf(closes, n):
    if len(closes) <= n:
        return None
    past = closes[-1 - n]
    return (closes[-1] / past - 1.0) * 100.0 if past else None


def adr_pct(bars, n=20):
    """Average Daily Range % = mean(high/low - 1) over last n days * 100.
    This is Qullamaggie's preferred volatility gauge."""
    seg = bars[-n:]
    vals = [(b["h"] / b["l"] - 1.0) for b in seg if b["l"] > 0]
    return (sum(vals) / len(vals)) * 100.0 if vals else None


def compute(sym, bars):
    closes = [b["c"] for b in bars]
    highs = [b["h"] for b in bars]
    price = closes[-1]
    hi_52 = max(highs[-TRADING_DAYS_1Y:]) if highs else price
    dist_high = (price / hi_52 - 1.0) * 100.0 if hi_52 else None  # <=0, closer to 0 = nearer high
    dollar_vol = (sum(b["c"] * b["v"] for b in bars[-20:]) / min(20, len(bars)))
    sma20, sma50, sma200 = _sma(closes, 20), _sma(closes, 50), _sma(closes, 200)
    return {
        "sym": sym,
        "price": price,
        "perf_1m": _perf(closes, TRADING_DAYS_1M),
        "perf_3m": _perf(closes, TRADING_DAYS_3M),
        "perf_6m": _perf(closes, TRADING_DAYS_6M),
        "adr_pct": adr_pct(bars, 20),
        "dist_high": dist_high,
        "dollar_vol_m": dollar_vol / 1e6,
        "above_20": sma20 is not None and price > sma20,
        "above_50": sma50 is not None and price > sma50,
        "above_200": sma200 is not None and price > sma200,
    }


def passes(m, args):
    def ok(v):  # None-safe
        return v is not None
    if not ok(m["perf_3m"]) or not ok(m["adr_pct"]) or not ok(m["dist_high"]):
        return False
    if m["price"] < args.min_price:
        return False
    if m["dollar_vol_m"] < args.min_dollar_vol_m:
        return False
    if m["adr_pct"] < args.min_adr:
        return False
    if m["perf_3m"] < args.min_perf3m:
        return False
    if m["dist_high"] < -args.max_off_high:   # within X% of 52w high
        return False
    if args.require_trend and not (m["above_20"] and m["above_50"]):
        return False
    return True


def score(m):
    """Composite: reward big move + high ADR + proximity to highs.
    dist_high is <=0, so adding it (a negative) penalizes being far below highs."""
    return (m["perf_3m"] or 0) + 2.0 * (m["adr_pct"] or 0) + (m["dist_high"] or -100)


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def load_tickers(path):
    out = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            s = line.strip().upper().split(",")[0].split()[0] if line.strip() else ""
            if s and not s.startswith("#"):
                out.append(s)
    return out


def main():
    p = argparse.ArgumentParser(description="Qullamaggie-style momentum screener")
    p.add_argument("--tickers", help="file with one symbol per line (overrides --universe)")
    p.add_argument("--universe", choices=["builtin", "us"], default="builtin",
                   help="'us' = full US market via universe.py (Nasdaq/NYSE/AMEX)")
    p.add_argument("--min-cap-m", type=float, default=300.0, help="[us] min market cap $M")
    p.add_argument("--max-cap-m", type=float, default=0.0, help="[us] max market cap $M (0=none)")
    p.add_argument("--refresh", action="store_true", help="[us] force re-download of the list")
    p.add_argument("--max-symbols", type=int, default=0, help="cap number scanned (0=all)")
    p.add_argument("--source", choices=["auto", "yahoo", "stooq"], default="auto")
    p.add_argument("--min-price", type=float, default=10.0)
    p.add_argument("--min-adr", type=float, default=3.0, help="min ADR%% (Qullamaggie likes >=5)")
    p.add_argument("--min-perf3m", type=float, default=20.0, help="min 3-month %% gain")
    p.add_argument("--max-off-high", type=float, default=25.0, help="max %% below 52w high")
    p.add_argument("--min-dollar-vol-m", type=float, default=5.0, help="min avg $ volume in $M")
    p.add_argument("--require-trend", action="store_true", default=True)
    p.add_argument("--no-trend", dest="require_trend", action="store_false")
    p.add_argument("--top", type=int, default=30)
    p.add_argument("--workers", type=int, default=6)
    p.add_argument("--out", help="write ranked results to this CSV")
    args = p.parse_args()

    if args.tickers:
        tickers = load_tickers(args.tickers)
    elif args.universe == "us":
        from universe import get_us_universe
        tickers = get_us_universe(min_cap_m=args.min_cap_m, max_cap_m=args.max_cap_m,
                                  min_price=args.min_price, refresh=args.refresh)
    else:
        tickers = DEFAULT_UNIVERSE
    tickers = sorted(set(tickers))
    if args.max_symbols:
        tickers = tickers[: args.max_symbols]
    print(f"Scanning {len(tickers)} symbols via {args.source} ...", file=sys.stderr)

    metrics, failed = [], []

    def work(sym):
        b = fetch(sym, args.source)
        if not b:
            return sym, None
        return sym, compute(sym, b)

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(work, s): s for s in tickers}
        for fut in as_completed(futs):
            sym, m = fut.result()
            if m is None:
                failed.append(sym)
            else:
                metrics.append(m)

    survivors = [m for m in metrics if passes(m, args)]
    survivors.sort(key=score, reverse=True)
    survivors = survivors[: args.top]

    # ---- print table ----
    hdr = f"{'#':>2} {'SYM':<6} {'PRICE':>8} {'1M%':>7} {'3M%':>7} {'6M%':>7} {'ADR%':>6} {'OFFHI%':>7} {'$VOLM':>7} {'>20':>4} {'>50':>4} {'>200':>4}"
    print("\n" + hdr)
    print("-" * len(hdr))
    for i, m in enumerate(survivors, 1):
        def f(x, w=7, d=1):
            return f"{x:>{w}.{d}f}" if x is not None else f"{'-':>{w}}"
        print(f"{i:>2} {m['sym']:<6} {f(m['price'],8,2)} "
              f"{f(m['perf_1m'])} {f(m['perf_3m'])} {f(m['perf_6m'])} "
              f"{f(m['adr_pct'],6)} {f(m['dist_high'])} {f(m['dollar_vol_m'])} "
              f"{('Y' if m['above_20'] else 'n'):>4} "
              f"{('Y' if m['above_50'] else 'n'):>4} "
              f"{('Y' if m['above_200'] else 'n'):>4}")

    print(f"\n{len(survivors)} passed of {len(metrics)} fetched "
          f"({len(failed)} failed{': ' + ','.join(failed[:10]) if failed else ''}).")
    print("Filters: price>=%.0f  ADR%%>=%.1f  3M%%>=%.0f  within %.0f%% of 52w-high  "
          "$vol>=%.0fM  trend=%s"
          % (args.min_price, args.min_adr, args.min_perf3m, args.max_off_high,
             args.min_dollar_vol_m, args.require_trend))
    print("NOTE: this is a WATCHLIST. Confirm the tight consolidation + breakout on the daily chart yourself.")

    if args.out:
        cols = ["sym", "price", "perf_1m", "perf_3m", "perf_6m", "adr_pct",
                "dist_high", "dollar_vol_m", "above_20", "above_50", "above_200"]
        with open(args.out, "w", newline="", encoding="utf-8") as fcsv:
            w = csv.DictWriter(fcsv, fieldnames=cols)
            w.writeheader()
            for m in survivors:
                w.writerow({k: m[k] for k in cols})
        print(f"Wrote {args.out}")


if __name__ == "__main__":
    t0 = time.time()
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
    print(f"[{datetime.now():%H:%M:%S}] done in {time.time()-t0:.1f}s", file=sys.stderr)
