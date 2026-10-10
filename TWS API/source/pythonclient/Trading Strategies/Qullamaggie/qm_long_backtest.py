#!/usr/bin/env python3
"""
Qullamaggie LONG-ONLY strategy backtest  (pure stdlib -- no PyPI).

Implements only the two LONG setups. The parabolic SHORT setup is intentionally
excluded.

  1. BREAKOUT  -- stock up big over 1-3 months, pulls back into a tight base,
                  then breaks out of the base. Enter on the breakout.
  2. EP        -- Episodic Pivot: a >=10% gap up on a volume surge in a stock
                  that had NOT already run huge. (No earnings feed available on
                  this machine, so EP is approximated by gap + volume + "not
                  already extended". Off by default.)

Exit rules (both setups), from Qullamaggie's own description:
  * Initial stop = low of the breakout / gap day (never wider than the ADR).
  * After PARTIAL_DAYS (3-5), sell half and move the stop to break-even.
  * Trail the remainder on the 10- or 20-day SMA; exit on the first close below it.

Sizing: risk RISK_PCT of equity per trade (stop distance = 1R), capped so no
position exceeds MAX_POS_PCT of equity. Compounding.

Data via urllib from Yahoo (primary) / Stooq (fallback) -- both reachable here.
No lookahead: a signal on day D is filled at day D+1's OPEN.

Output: prints a summary and (with --out DIR) writes <SYM>_<strat>_trades.csv per
symbol in the Backtest Journal format:
  symbol,strat,entry_id,side,qty,entry_time_et,entry_price,exit_time_et,
  exit_price,reason,R_points,R_result,pnl
One row per leg; legs of one trade share entry_id (partial + final).

Usage:
    python qm_long_backtest.py                          # breakout, built-in universe
    python qm_long_backtest.py --setup both --range 5y
    python qm_long_backtest.py --tickers mylist.txt --out trades_out
    python qm_long_backtest.py --min-move 30 --trail-sma 20 --partial-days 5
"""

import argparse
import csv
import json
import os
import sys
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

DEFAULT_UNIVERSE = [
    "NVDA", "AMD", "TSLA", "META", "AVGO", "MSFT", "AAPL", "AMZN", "GOOGL",
    "NFLX", "CRM", "SMCI", "MU", "MRVL", "ARM", "PLTR", "SNOW", "DDOG",
    "CRWD", "PANW", "NET", "ZS", "MDB", "SHOP", "UBER", "ABNB", "COIN",
    "HOOD", "SOFI", "AFRM", "RBLX", "DKNG", "CVNA", "APP", "DASH", "TTD",
    "TSM", "ASML", "LRCX", "KLAC", "AMAT", "ON", "ANET", "DELL", "VRT",
    "CLS", "NBIS", "ALAB", "CRDO", "TEM", "IONQ", "RGTI",
    "CCJ", "UEC", "OKLO", "SMR", "VST", "TLN", "CEG", "GEV", "FSLR",
    "VKTX", "CRSP", "RXRX", "TGTX", "MARA", "RIOT", "CLSK", "MSTR",
    "RDDT", "ASTS", "RKLB",
]

YQ = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range={rng}&interval=1d"
STOOQ = "https://stooq.com/q/d/l/?s={sym}.us&i=d"
UA = {"User-Agent": "Mozilla/5.0 (backtest; stdlib urllib)"}


# ----------------------------------------------------------------------------
# Data
# ----------------------------------------------------------------------------
def _http(url, timeout=20, retries=2):
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code in (429, 502, 503) and attempt < retries:
                time.sleep(1.0 + attempt)
                continue
            raise


def fetch_yahoo(sym, rng):
    j = json.loads(_http(YQ.format(sym=sym, rng=rng)))
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
        d = datetime.fromtimestamp(ts[i], tz=timezone.utc).strftime("%Y-%m-%d")
        bars.append({"d": d, "o": oi or ci, "h": hi, "l": li, "c": ci, "v": vi or 0})
    return bars or None


def fetch_stooq(sym, rng):
    rows = list(csv.DictReader(_http(STOOQ.format(sym=sym.lower())).splitlines()))
    if not rows or "Close" not in rows[0]:
        return None
    bars = []
    for r in rows:
        try:
            bars.append({"d": r["Date"], "o": float(r["Open"]), "h": float(r["High"]),
                         "l": float(r["Low"]), "c": float(r["Close"]),
                         "v": float(r.get("Volume") or 0)})
        except (ValueError, KeyError):
            continue
    return bars or None


def fetch(sym, source, rng):
    order = {"yahoo": (fetch_yahoo, fetch_stooq),
             "stooq": (fetch_stooq, fetch_yahoo),
             "auto": (fetch_yahoo, fetch_stooq)}[source]
    for fn in order:
        try:
            b = fn(sym, rng)
            if b and len(b) >= 160:
                return b
        except (urllib.error.URLError, urllib.error.HTTPError,
                json.JSONDecodeError, KeyError, ValueError, TimeoutError):
            continue
    return None


# ----------------------------------------------------------------------------
# Indicators (rolling arrays, index-aligned with bars)
# ----------------------------------------------------------------------------
def sma_series(vals, n):
    out = [None] * len(vals)
    s = 0.0
    for i, x in enumerate(vals):
        s += x
        if i >= n:
            s -= vals[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def adr_pct_at(bars, i, n=20):
    if i < n:
        return None
    seg = bars[i - n + 1:i + 1]
    vals = [(b["h"] / b["l"] - 1.0) for b in seg if b["l"] > 0]
    return (sum(vals) / len(vals)) * 100.0 if vals else None


def apply_adr_stop(trigger, raw_stop, adr_pct, use_adr, mult=1.0):
    """Qullamaggie's 'stop no wider than ~1 ADR'. Returns the TIGHTER of the raw structural stop
    (base / crash / opening-range low) and an ADR-based stop at trigger - mult*ADR. This caps the
    stop DISTANCE at mult*ADR -> larger notional for the same 1% risk. No-op when use_adr is off
    or ADR is unavailable; also never widens a stop that's already tighter than mult*ADR."""
    if not use_adr or not adr_pct or adr_pct <= 0 or trigger <= 0:
        return raw_stop
    adr_stop = trigger - (mult * adr_pct / 100.0) * trigger
    return max(raw_stop, adr_stop)


# ----------------------------------------------------------------------------
# Signals (evaluated on day i using bars[..i]; filled at open[i+1])
# ----------------------------------------------------------------------------
def breakout_signal(bars, i, sma20, sma50, a):
    """Big prior move -> tight base -> breakout above the base high today."""
    cons = a.cons_days
    if i < a.warmup or sma20[i] is None or sma50[i] is None:
        return None
    c = bars[i]["c"]
    # uptrend
    if not (c > sma20[i] > sma50[i]):
        return None
    # big prior move over 63 trading days (~3 months)
    base_c = bars[i - 63]["c"]
    perf3m = (c / base_c - 1.0) * 100.0 if base_c else 0.0
    if perf3m < a.min_move or perf3m > a.max_move:
        return None
    # the base = prior `cons` days excluding today
    prior_hi = max(b["h"] for b in bars[i - cons:i])
    prior_lo = min(b["l"] for b in bars[i - cons:i])
    # tight contraction
    if prior_lo <= 0 or (prior_hi / prior_lo - 1.0) > a.max_base_range / 100.0:
        return None
    # fresh breakout: close clears the base high today, didn't yesterday
    if not (c > prior_hi and bars[i - 1]["c"] <= prior_hi):
        return None
    # EXTENSION filter: skip a breakout already too far above the 50-day SMA (late-stage / extended).
    max_ext = getattr(a, "max_ext_pct", 0)
    if max_ext and sma50[i] and (c / sma50[i] - 1.0) * 100.0 > max_ext:
        return None
    # ADR sanity
    adr = adr_pct_at(bars, i)
    if adr is not None and adr < a.min_adr:
        return None
    return {"stop": bars[i]["l"]}  # initial stop = breakout-day low


def ep_signal(bars, i, sma50, a):
    """Episodic Pivot approx: >=10% gap up on a volume surge, not already extended."""
    if i < a.warmup:
        return None
    prev_c = bars[i - 1]["c"]
    gap = (bars[i]["o"] / prev_c - 1.0) * 100.0 if prev_c else 0.0
    if gap < a.ep_gap:
        return None
    avg_v = sum(b["v"] for b in bars[i - 20:i]) / 20.0
    if avg_v <= 0 or bars[i]["v"] < a.ep_rvol * avg_v:
        return None
    # not already run huge over the prior ~6 months (126d), so the gap is the catalyst
    c6 = bars[i - 126]["c"]
    if c6 and (prev_c / c6 - 1.0) * 100.0 > a.ep_max_prior:
        return None
    return {"stop": bars[i]["l"]}


def parabolic_long_signal(bars, i, a):
    """Parabolic LONG (bounce): a former parabolic that ran up then crashed
    ~50-60%+ in a few days, now making its first range-break to the upside.

    Daily-bar approximation of Qullamaggie's intraday 'first green candle /
    opening range high' entry -- here: today's close breaks the prior day's high,
    while price is still near the crash low (not chased). Stop = crash low."""
    lb = a.pl_lookback
    if i < a.warmup or i < lb + a.pl_runup_days + 1:
        return None
    # parabolic peak in the recent past (exclude today)
    hh_idx = max(range(i - lb, i), key=lambda k: bars[k]["h"])
    hh = bars[hh_idx]["h"]
    # crash low after the peak, through today
    ll_idx = min(range(hh_idx, i + 1), key=lambda k: bars[k]["l"])
    ll = bars[ll_idx]["l"]
    if hh <= 0 or ll <= 0 or ll_idx <= hh_idx:
        return None
    if (hh - ll) / hh * 100.0 < a.pl_drop:             # big enough crash
        return None
    if (ll_idx - hh_idx) > a.pl_drop_days:             # crash was fast
        return None
    ru0 = hh_idx - a.pl_runup_days                      # prior run-up into the peak
    if ru0 < 0 or not bars[ru0]["c"]:
        return None
    if (hh / bars[ru0]["c"] - 1.0) * 100.0 < a.pl_runup:
        return None
    if (i - ll_idx) > a.pl_bounce_within:              # bounce must be fresh
        return None
    if not (bars[i]["c"] > bars[i - 1]["h"]):          # range break to the upside today
        return None
    if bars[i]["c"] > ll * (1.0 + a.pl_max_bounce / 100.0):   # don't chase far off the low
        return None
    stop = min(bars[k]["l"] for k in range(ll_idx, i + 1))     # stop = crash low
    return {"stop": stop}


def pullback_signal(bars, i, sma10, sma20, sma50, a):
    """Qullamaggie MA-pullback / continuation: a strong leader (same quality universe as the
    breakout) in an established uptrend that pulls back to a RISING 10/20-day MA and then resumes.
    Lets us join leaders that already broke out (the late-entry gap) at a lower-risk entry.

    Mechanical daily-bar approximation:
      - uptrend + leader: close > sma20 > sma50, big 3-month move (same min/max as breakout)
      - the reference MA (10 by default) is RISING (established trend, not a first base)
      - within the last `pb_lookback` bars a bar's LOW tagged the MA (came within pb_near%)
      - today = resumption: a green bar that closes back above the PRIOR day's high (reclaim)
      - not chasing: entry close is within pb_max_ext% of the MA (buy near the MA, not after it ran)
      - stop = the pullback swing low (tight, just under the MA)."""
    if i < a.warmup or sma10[i] is None or sma20[i] is None or sma50[i] is None:
        return None
    c = bars[i]["c"]
    if not (c > sma20[i] > sma50[i]):                      # uptrend
        return None
    base_c = bars[i - 63]["c"]                             # big prior ~3-month move (leader)
    perf3m = (c / base_c - 1.0) * 100.0 if base_c else 0.0
    if perf3m < a.min_move or perf3m > a.max_move:
        return None
    ma = sma10 if a.pb_ma == 10 else sma20
    if ma[i] is None or ma[i - 5] is None or ma[i] <= ma[i - 5]:   # MA must be rising
        return None
    lb = a.pb_lookback
    tagged = any(ma[k] is not None and bars[k]["l"] <= ma[k] * (1.0 + a.pb_near / 100.0)
                 for k in range(i - lb, i))                # a recent low pulled back to the MA
    if not tagged:
        return None
    if not (bars[i]["c"] > bars[i - 1]["h"] and bars[i]["c"] > bars[i]["o"]):  # green reclaim today
        return None
    if (c / ma[i] - 1.0) * 100.0 > a.pb_max_ext:           # don't chase far above the MA
        return None
    adr = adr_pct_at(bars, i)
    if adr is not None and adr < a.min_adr:
        return None
    stop = min(bars[k]["l"] for k in range(i - lb, i + 1))  # pullback swing low
    return {"stop": stop}


def enabled_setups(name):
    if name == "both":
        return ("breakout", "ep")
    if name == "all":
        return ("breakout", "ep", "parabolic_long")
    if name == "bp":                                        # breakout + pullback (continuation)
        return ("breakout", "pullback")
    return (name,)


# ----------------------------------------------------------------------------
# Backtest one symbol
# ----------------------------------------------------------------------------
def backtest_symbol(sym, bars, a, equity_ref):
    closes = [b["c"] for b in bars]
    sma10 = sma_series(closes, 10)
    sma20 = sma_series(closes, 20)
    sma50 = sma_series(closes, 50)
    trail = sma_series(closes, a.trail_sma)
    n = len(bars)

    legs = []          # output rows
    pos = None
    tid = 0

    i = a.warmup
    while i < n - 1:
        if pos is None:
            sig, strat = None, None
            es = a._enabled
            if "breakout" in es:
                sig = breakout_signal(bars, i, sma20, sma50, a)
                strat = "qm_breakout"
            if sig is None and "ep" in es:
                sig = ep_signal(bars, i, sma50, a)
                strat = "qm_ep"
            if sig is None and "parabolic_long" in es:
                sig = parabolic_long_signal(bars, i, a)
                strat = "qm_parabolic_long"
            if sig is None and "pullback" in es:
                sig = pullback_signal(bars, i, sma10, sma20, sma50, a)
                strat = "qm_pullback"
            if sig:
                j = i + 1                      # fill next open (no lookahead)
                entry = bars[j]["o"]
                stop0 = apply_adr_stop(entry, sig["stop"], adr_pct_at(bars, i),   # cap at ~1 ADR (optional)
                                       getattr(a, "adr_stop", False), getattr(a, "adr_stop_mult", 1.0))
                risk = entry - stop0
                if risk > 0 and (risk / entry) <= a.max_risk_frac:
                    equity = equity_ref[0]
                    qty = int((equity * a.risk_pct / 100.0) / risk)
                    cap = int((equity * a.max_pos_pct / 100.0) / entry)
                    qty = max(0, min(qty, cap))
                    if qty >= 1:
                        tid += 1
                        pos = {"id": f"{sym}-{tid}", "strat": strat,
                               "entry": entry, "entry_d": bars[j]["d"],
                               "stop0": stop0, "stop": stop0, "risk": risk,
                               "qty": qty, "left": qty, "held": 0, "partial": False}
                        i = j                  # continue managing from fill day
                        i += 1
                        continue
            i += 1
            continue

        # ---- manage open position on day i ----
        b = bars[i]
        pos["held"] += 1
        exit_all = None  # (price, reason)

        # 1) stop breach (gap-through fills at open)
        if b["l"] <= pos["stop"]:
            exit_all = (min(b["o"], pos["stop"]) if b["o"] < pos["stop"] else pos["stop"],
                        "BE-Stop" if pos["partial"] else "Stop")

        # 2) partial — scale HALF out of a WINNER, then move to break-even. Qullamaggie sells "INTO
        #    STRENGTH": fire when the move is EXTENDED above the trail MA (a climax — can trigger early,
        #    day 1+), OR fall back to the time rule (held >= partial_days). Both require the position be
        #    up >= partial_min_r so we never scale out of a loser. partial_ext_adr=0 -> pure time rule.
        cur_r = (b["c"] - pos["entry"]) / pos["risk"] if pos["risk"] else 0
        min_r = getattr(a, "partial_min_r", 0.5)
        ext_adr = getattr(a, "partial_ext_adr", 0.0)
        ext_fire = False
        if ext_adr and trail[i] is not None and trail[i] > 0:
            adr_now = adr_pct_at(bars, i)
            if adr_now:
                adrs_above = ((b["c"] / trail[i] - 1.0) * 100.0) / adr_now   # ADRs above the trail MA
                ext_fire = adrs_above >= ext_adr
        time_fire = pos["held"] >= a.partial_days
        if (exit_all is None and (not pos["partial"]) and cur_r >= min_r and (ext_fire or time_fire)):
            half = pos["left"] // 2
            if half >= 1:
                _emit(legs, sym, pos, half, b["c"], b["d"], "Partial-Ext" if ext_fire else "Partial")
                pos["left"] -= half
                pos["partial"] = True
                # post-partial stop placement = entry + be_stop_r * risk. 0 = break-even (classic),
                # <0 = below entry (looser, fewer shakeouts), >0 = lock in profit (tighter). A sentinel
                # <= -90 means DON'T move the stop (keep the original, let the MA trail catch up).
                be_r = getattr(a, "be_stop_r", 0.0)
                if be_r is None or be_r > -90:
                    pos["stop"] = pos["entry"] + (be_r or 0.0) * pos["risk"]

        # 3) trail: first close below trail SMA exits the remainder
        if exit_all is None and trail[i] is not None and b["c"] < trail[i]:
            exit_all = (b["c"], "Trail")

        if exit_all is not None:
            _emit(legs, sym, pos, pos["left"], exit_all[0], b["d"], exit_all[1])
            equity_ref[0] += _trade_pnl(legs, pos["id"])  # realize into equity
            pos = None
        i += 1

    # force-close anything still open at last bar
    if pos is not None:
        b = bars[-1]
        _emit(legs, sym, pos, pos["left"], b["c"], b["d"], "EndOfData")
        equity_ref[0] += _trade_pnl(legs, pos["id"])

    return legs


def _emit(legs, sym, pos, qty, price, date, reason):
    r_pts = pos["risk"]
    r_mult = (price - pos["entry"]) / r_pts if r_pts else 0.0
    pnl = (price - pos["entry"]) * qty
    legs.append({
        "symbol": sym, "strat": pos["strat"], "entry_id": pos["id"], "side": "Long",
        "qty": qty, "entry_time_et": pos["entry_d"], "entry_price": round(pos["entry"], 4),
        "exit_time_et": date, "exit_price": round(price, 4), "reason": reason,
        "R_points": round(r_pts, 4), "R_result": f"{r_mult:+.2f}R", "pnl": round(pnl, 2),
    })


def _trade_pnl(legs, entry_id):
    return sum(l["pnl"] for l in legs if l["entry_id"] == entry_id)


# ----------------------------------------------------------------------------
# Stats
# ----------------------------------------------------------------------------
def summarize(all_legs):
    # aggregate to trade level by entry_id, preserving exit date order
    trades = {}
    for l in all_legs:
        t = trades.setdefault(l["entry_id"], {"pnl": 0.0, "r": 0.0, "exit": l["exit_time_et"],
                                              "risk": l["R_points"], "sym": l["symbol"]})
        t["pnl"] += l["pnl"]
        t["exit"] = max(t["exit"], l["exit_time_et"])
    for t in trades.values():
        t["r"] = t["pnl"] / t["risk"] if t["risk"] else 0.0  # weighted R over full size? approx
    tl = sorted(trades.values(), key=lambda x: x["exit"])
    n = len(tl)
    if not n:
        return None
    wins = [t for t in tl if t["pnl"] > 0]
    losses = [t for t in tl if t["pnl"] <= 0]
    gp = sum(t["pnl"] for t in wins)
    gl = -sum(t["pnl"] for t in losses)
    # equity curve / maxDD (start from same base used in run)
    eq, peak, mdd = 0.0, 0.0, 0.0
    for t in tl:
        eq += t["pnl"]
        peak = max(peak, eq)
        mdd = min(mdd, eq - peak)
    return {
        "trades": n, "win%": 100.0 * len(wins) / n,
        "net": sum(t["pnl"] for t in tl),
        "pf": (gp / gl) if gl else float("inf"),
        "avg_win": (gp / len(wins)) if wins else 0.0,
        "avg_loss": (-gl / len(losses)) if losses else 0.0,
        "maxdd": mdd,
    }


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def load_tickers(path):
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            s = line.strip().upper().split(",")[0].split()[0] if line.strip() else ""
            if s and not s.startswith("#"):
                out.append(s)
    return out


def main():
    p = argparse.ArgumentParser(description="Qullamaggie LONG-only backtest (no shorts)")
    p.add_argument("--tickers", help="file with one symbol per line (overrides --universe)")
    p.add_argument("--universe", choices=["builtin", "us"], default="builtin",
                   help="'us' = full US market via universe.py")
    p.add_argument("--min-cap-m", type=float, default=300.0, help="[us] min market cap $M")
    p.add_argument("--max-cap-m", type=float, default=0.0, help="[us] max market cap $M (0=none)")
    p.add_argument("--min-uni-price", type=float, default=10.0, help="[us] min price for universe")
    p.add_argument("--refresh", action="store_true", help="[us] force re-download of the list")
    p.add_argument("--max-symbols", type=int, default=0, help="cap number tested (0=all)")
    p.add_argument("--source", choices=["auto", "yahoo", "stooq"], default="auto")
    p.add_argument("--range", dest="rng", default="2y", help="Yahoo range: 1y,2y,5y,max")
    p.add_argument("--setup", choices=["breakout", "ep", "parabolic_long", "pullback", "both", "bp", "all"],
                   default="breakout", help="both=breakout+ep, all=+parabolic_long")
    # entry
    p.add_argument("--min-move", type=float, default=30.0, help="min 3-month %% gain")
    p.add_argument("--max-move", type=float, default=300.0, help="skip already-parabolic names")
    p.add_argument("--cons-days", type=int, default=10, help="base/consolidation lookback")
    p.add_argument("--max-base-range", type=float, default=20.0, help="max %% range of the base")
    p.add_argument("--min-adr", type=float, default=3.0)
    # EP
    p.add_argument("--ep-gap", type=float, default=10.0)
    p.add_argument("--ep-rvol", type=float, default=1.5)
    p.add_argument("--ep-max-prior", type=float, default=50.0, help="max prior 6m %% (not extended)")
    # Parabolic LONG (bounce after a crash of a former parabolic)
    p.add_argument("--pl-lookback", type=int, default=40, help="window to find the parabolic peak")
    p.add_argument("--pl-runup", type=float, default=50.0, help="min %% run-up into the peak")
    p.add_argument("--pl-runup-days", type=int, default=20, help="lookback for the run-up")
    p.add_argument("--pl-drop", type=float, default=50.0, help="min %% crash from peak to low")
    p.add_argument("--pl-drop-days", type=int, default=15, help="max days peak->low (fast crash)")
    p.add_argument("--pl-bounce-within", type=int, default=5, help="enter within N days of the low")
    p.add_argument("--pl-max-bounce", type=float, default=30.0, help="max %% above the low (no chase)")
    # exits / sizing
    p.add_argument("--pb-ma", type=int, default=10, choices=[10, 20], help="pullback reference MA")
    p.add_argument("--pb-lookback", type=int, default=8, help="bars to look back for a pullback tag/swing low")
    p.add_argument("--pb-near", type=float, default=2.0, help="a low within this %% of the MA counts as a pullback tag")
    p.add_argument("--pb-max-ext", type=float, default=5.0, help="skip if entry close is >this %% above the MA (no chase)")
    p.add_argument("--partial-days", type=int, default=5)
    p.add_argument("--partial-min-r", type=float, default=0.5, help="only take partial if position up >= this R")
    p.add_argument("--partial-ext-adr", type=float, default=0.0,
                   help="sell the partial INTO STRENGTH when close is >= this many ADRs above the trail MA "
                        "(0=off -> pure time rule). Still profit-gated by --partial-min-r; time rule is the fallback")
    p.add_argument("--be-stop-r", type=float, default=0.0,
                   help="post-partial stop = entry + this*risk (0=break-even, <0=below entry/looser, "
                        ">0=lock profit/tighter). Use -99 to NOT move the stop (keep original, trail-only)")
    p.add_argument("--trail-sma", type=int, default=20, help="trail on 10 or 20-day SMA")
    p.add_argument("--risk-pct", type=float, default=0.5, help="%% equity risked per trade")
    p.add_argument("--max-pos-pct", type=float, default=30.0)
    p.add_argument("--max-risk-frac", type=float, default=0.25, help="skip if stop>this frac of price")
    p.add_argument("--adr-stop", action="store_true", help="cap stop distance at adr_stop_mult x ADR (tighter)")
    p.add_argument("--adr-stop-mult", type=float, default=1.0, help="ADR multiple for the stop cap")
    p.add_argument("--max-ext-pct", type=float, default=0.0, help="skip breakout if close > this %% above 50-SMA (0=off)")
    p.add_argument("--equity", type=float, default=100000.0)
    p.add_argument("--warmup", type=int, default=150)
    p.add_argument("--workers", type=int, default=6)
    p.add_argument("--out", help="directory to write <SYM>_<strat>_trades.csv files")
    a = p.parse_args()
    a._enabled = enabled_setups(a.setup)

    if a.tickers:
        tickers = load_tickers(a.tickers)
    elif a.universe == "us":
        from universe import get_us_universe
        tickers = get_us_universe(min_cap_m=a.min_cap_m, max_cap_m=a.max_cap_m,
                                  min_price=a.min_uni_price, refresh=a.refresh)
    else:
        tickers = DEFAULT_UNIVERSE
    tickers = sorted(set(tickers))
    if a.max_symbols:
        tickers = tickers[: a.max_symbols]
    print(f"Backtesting {len(tickers)} symbols | setup={a.setup} | range={a.rng}", file=sys.stderr)

    equity_ref = [a.equity]     # shared, compounding across the merged timeline (approx)
    all_legs, failed = [], []

    def work(sym):
        b = fetch(sym, a.source, a.rng)
        if not b:
            return sym, None
        return sym, backtest_symbol(sym, b, a, equity_ref)

    # NOTE: fetch in parallel, but backtest sequentially so compounding equity is deterministic
    fetched = {}
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(fetch, s, a.source, a.rng): s for s in tickers}
        for fut in as_completed(futs):
            s = futs[fut]
            b = fut.result()
            if b:
                fetched[s] = b
            else:
                failed.append(s)

    for s in tickers:
        if s in fetched:
            legs = backtest_symbol(s, fetched[s], a, equity_ref)
            all_legs.extend(legs)

    # per-symbol CSVs
    if a.out:
        os.makedirs(a.out, exist_ok=True)
        cols = ["symbol", "strat", "entry_id", "side", "qty", "entry_time_et",
                "entry_price", "exit_time_et", "exit_price", "reason",
                "R_points", "R_result", "pnl"]
        bysym = {}
        for l in all_legs:
            bysym.setdefault((l["symbol"], l["strat"]), []).append(l)
        for (sym, strat), rows in bysym.items():
            path = os.path.join(a.out, f"{sym}_{strat}_trades.csv")
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=cols)
                w.writeheader()
                w.writerows(rows)
        print(f"Wrote {len(bysym)} CSV file(s) to {a.out}/")

    # summary
    s = summarize(all_legs)
    print("\n==== Qullamaggie LONG-only backtest ====")
    print(f"symbols fetched : {len(fetched)}  (failed: {len(failed)}"
          f"{': ' + ','.join(failed[:10]) if failed else ''})")
    if not s:
        print("No trades generated. Loosen filters (e.g. --min-move 20 --max-base-range 30).")
        return
    print(f"trades          : {s['trades']}")
    print(f"win rate        : {s['win%']:.1f}%   (low win-rate + big winners is expected)")
    print(f"net P&L         : ${s['net']:,.0f}   (start equity ${a.equity:,.0f})")
    print(f"profit factor   : {s['pf']:.2f}")
    print(f"avg win / loss  : ${s['avg_win']:,.0f} / ${s['avg_loss']:,.0f}")
    print(f"max drawdown    : ${s['maxdd']:,.0f}")
    print(f"final equity    : ${equity_ref[0]:,.0f}")
    print("\nSetups: LONG only [" + ", ".join(a._enabled) + "]. Parabolic SHORT NOT included.")
    print("Caveat: survivorship-biased universe + daily-bar approximation of an intraday-entry method.")


if __name__ == "__main__":
    t0 = time.time()
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
    print(f"[{datetime.now():%H:%M:%S}] done in {time.time()-t0:.1f}s", file=sys.stderr)
