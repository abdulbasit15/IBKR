"""
Qullamaggie LONG-ONLY swing bot for IBKR (ib_async).

Automates the LONG side of Kristjan "Qullamaggie" Kullamagi's method. NO SHORTS.
Trades the BREAKOUT setup (his primary long): a stock up big over ~1-3 months
that has pulled back into a TIGHT consolidation near its highs, then breaks out
of that base. The bot places a BUY-STOP at the base high so it only enters on the
actual breakout, with a protective SELL-STOP at the base low (native IB bracket,
so a filled position is never unprotected).

Your rules, baked in:
  * LONG only. The bot will never short.
  * Risk 1% of capital per ticker  (risk_per_trade_pct = 0.01).
  * At most 10 positions at once    (max_positions = 10).
  * Position size = floor( capital * 1% / (entry - stop) ), also capped so no
    single name exceeds max_position_pct (30%) of capital -- his overnight cap.

Exit management (his rules), run once/day near the close:
  * After partial_days (default 5) held: SELL partial_fraction (half) at market
    and move the protective stop to BREAK-EVEN.
  * Trail the remainder on the trail_sma (10 or 20-day): exit on the first daily
    CLOSE below it (close-based, not an intraday stop -- avoids wick-outs).
  * The initial hard stop (base low) always rests as a server-side bracket child.

Data: broad daily scan uses the sibling universe.py + qm_long_backtest fetch
(Yahoo/Stooq -- fast, free, no PyPI). Execution / positions / account equity use
IBKR via ib_async. Held-name management also uses the daily fetch for indicators.

=================================  SAFETY  =================================
 * paper=true  -> connects to the PAPER gateway (port 4002). LIVE requires BOTH
   paper=false in config AND the CLI flag  --i-understand-live .
 * dry_run=true (default) -> logs every order it WOULD place, places nothing.
   Set dry_run=false to actually transmit orders.
 * Long-only is enforced structurally; sells are clamped to the held quantity.
 * State persists to qm_bot_state.json; on startup the bot reconciles with the
   real IB positions so a restart never double-enters or orphans a stop.
 * PAPER-FIRST. Validate on paper for weeks. On a corporate/LPL account, get
   pre-clearance before pointing at anything live. This is not financial advice.
===========================================================================

Run:
  python qm_bot.py --check                 # validate config + imports, no network
  python qm_bot.py --scan-only             # offline: print today's breakout setups
  python qm_bot.py --once                  # connect, run one entry+manage cycle
  python qm_bot.py                          # run the scheduled loop
  python qm_bot.py --config qm_bot.json
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

# Module dir = where the .py / bundled modules live (temp _MEIxxx when frozen); used for imports.
_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
if _MODULE_DIR not in sys.path:
    sys.path.insert(0, _MODULE_DIR)

# App dir = where config / state / log live. When frozen by PyInstaller, __file__ points at the
# temp extraction dir, so anchor persistent files next to the EXE instead.
if getattr(sys, "frozen", False):
    _APP_DIR = os.path.dirname(sys.executable)
else:
    _APP_DIR = _MODULE_DIR

# Reuse the already-built + verified pieces (no duplication):
from universe import get_us_universe                       # noqa: E402
from qm_long_backtest import fetch, sma_series, adr_pct_at, apply_adr_stop, DEFAULT_UNIVERSE  # noqa: E402
import earnings                                            # noqa: E402  (EP catalyst feed; top-level so PyInstaller bundles it)

ET = ZoneInfo("America/New_York")
STATE_FILE = os.path.join(_APP_DIR, "qm_bot_state.json")
# Per-strategy logs live in logs/. Every line goes to the main lifecycle log
# (logs/qm_bot_<date>.log); setup-attributable lines (entries, manage, exits) ALSO go to that
# setup's own file (logs/qm_<setup>_<date>.log), so there is one log file per setup as well as the
# combined one — the setups run in a SINGLE process here (unlike supertrend's per-thread strategies),
# so they can't each own a separate root file, hence the shared main log + per-setup split.
LOG_DIR = os.path.join(_APP_DIR, "logs")
DEFAULT_CONFIG = os.path.join(_APP_DIR, "qm_bot.json")

# Trade-log columns — identical to the backtest / Backtest Journal format so the journal
# (python -m journal backtest) ingests the bot's live trades the same way. One row per exit leg;
# legs of one trade share entry_id (e.g. a PARTIAL leg + the final TRAIL/Stop leg).
TRADE_COLS = ["symbol", "strat", "entry_id", "side", "qty", "entry_time_et", "entry_price",
              "exit_time_et", "exit_price", "reason", "R_points", "R_result", "pnl"]


# ─────────────────────────────── utils ───────────────────────────────
def now_et() -> datetime:
    return datetime.now(ET)


def _log_path(setup: str = None) -> str:
    """Path of the log file for `setup` (per-setup, e.g. logs/qm_breakout_<date>.log) or the main
    combined lifecycle log (logs/qm_bot_<date>.log) when setup is None. Date-stamped daily."""
    stamp = now_et().strftime("%Y%m%d")
    name = f"qm_{setup}_{stamp}.log" if setup else f"qm_bot_{stamp}.log"
    return os.path.join(LOG_DIR, name)


def log(msg: str, setup: str = None):
    """Print + append a timestamped line. Always writes the main lifecycle log; when a `setup` is
    given (breakout / parabolic_long / ep) it ALSO appends to that setup's own per-strategy file, so
    each setup has its own log in logs/ in addition to the combined one."""
    line = f"[{now_et():%Y-%m-%d %H:%M:%S ET}] {msg}"
    try:
        print(line, flush=True)
    except UnicodeEncodeError:                   # Windows cp1252 console can't encode some chars
        print(line.encode("ascii", "replace").decode("ascii"), flush=True)
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
    except OSError:
        pass
    targets = [_log_path(None)]                 # always the combined lifecycle log
    if setup:
        targets.append(_log_path(setup))        # plus this setup's own per-strategy log
    for path in targets:
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass


def load_config(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            pass
    return {"positions": {}}


def save_state(state: dict):
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, STATE_FILE)


def round_cent(x: float) -> float:
    return round(x + 1e-9, 2)


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


# ─────────────────────────── quality scoring ───────────────────────────
# Weighted composite of the factors Qullamaggie emphasises for a breakout. Each factor is scaled so
# no single one dominates; weights are tunable via cfg["quality_weights"]. Higher score = better.
QUALITY_WEIGHTS = {
    "rs": 0.5,        # relative strength: 3-month return in EXCESS of SPY (leaders lead the market)
    "adr": 5.0,       # ADR% in a sweet spot (capped) — volatile enough to move, not junk
    "tight": 3.0,     # tighter base (smaller % range) = higher quality consolidation
    "voldry": 30.0,   # volume DRY-UP in the base vs the prior run (contraction = accumulation)
    "near": 3.0,      # proximity to the 52-week high (off_high is <=0)
    "trend": 20.0,    # full trend alignment bonus (price above the 200-day SMA)
    "hl": 10.0,       # orderly base: higher lows (base low above the pre-base low)
}
ADR_SWEET_CAP = 10.0  # ADR reward saturates here so the most volatile name doesn't auto-win


def _breakout_quality(price, perf3m, adr, base_range_pct, off_high, base_vol, ref_vol,
                      above_200, higher_lows, spy_perf3m, w, max_base_range_pct):
    rs = perf3m - (spy_perf3m or 0.0)                    # excess vs market
    adr_sweet = min(adr, ADR_SWEET_CAP)
    tight = max(0.0, max_base_range_pct - base_range_pct)
    voldry = _clamp((ref_vol / base_vol - 1.0) if base_vol > 0 else 0.0, 0.0, 2.0)
    comp = {
        "rs": w["rs"] * rs,
        "adr": w["adr"] * adr_sweet,
        "tight": w["tight"] * tight,
        "voldry": w["voldry"] * voldry,
        "near": w["near"] * off_high,                    # off_high<=0 -> closer to high scores higher
        "trend": w["trend"] if above_200 else 0.0,
        "hl": w["hl"] if higher_lows else 0.0,
    }
    return sum(comp.values()), comp


# ─────────────────────────── setup scanner ───────────────────────────
def analyze_breakout(sym: str, bars: list, p: SimpleNamespace):
    """Return a coiled-breakout candidate dict for `sym`, or None.

    A candidate is: strong prior move + tight base near highs + NOT yet broken
    out (so the breakout is still ahead and we can place a buy-stop at it).
    Ranked by a multi-factor QUALITY score (RS vs SPY, ADR sweet-spot, base
    tightness, volume dry-up, proximity to highs, trend alignment, higher lows)."""
    n = len(bars)
    if n < p.warmup:
        return None
    closes = [b["c"] for b in bars]
    highs = [b["h"] for b in bars]
    lows = [b["l"] for b in bars]
    vols = [b["v"] for b in bars]
    price = closes[-1]
    if price < p.min_price:
        return None

    sma20 = sum(closes[-20:]) / 20
    sma50 = sum(closes[-50:]) / 50
    if not (price > sma20 > sma50):                      # uptrend
        return None
    above_200 = n >= 200 and price > (sum(closes[-200:]) / 200)

    # EXTENSION filter: skip breakouts already too far above the 50-day SMA (late-stage / chasing)
    max_ext = getattr(p, "max_ext_pct", 0)
    if max_ext and sma50 and (price / sma50 - 1.0) * 100.0 > max_ext:
        return None

    base_c = closes[-1 - 63] if n > 63 else closes[0]
    perf3m = (price / base_c - 1.0) * 100.0 if base_c else 0.0
    if perf3m < p.min_move_pct or perf3m > p.max_move_pct:
        return None

    cons = p.cons_days
    base_hi = max(highs[-cons:])
    base_lo = min(lows[-cons:])
    if base_lo <= 0:
        return None
    base_range_pct = (base_hi / base_lo - 1.0) * 100.0
    if base_range_pct > p.max_base_range_pct:
        return None                                      # base not tight enough

    adr = adr_pct_at(bars, n - 1, 20)
    if adr is None or adr < p.min_adr_pct:
        return None

    hi_52 = max(highs[-252:])
    off_high = (price / hi_52 - 1.0) * 100.0             # <= 0
    if off_high < -p.near_high_pct:
        return None

    dollar_vol_m = (sum(b["c"] * b["v"] for b in bars[-20:]) / min(20, n)) / 1e6
    if dollar_vol_m < p.min_dollar_vol_m:
        return None

    trigger = round_cent(base_hi * (1.0 + p.breakout_buffer_pct / 100.0))
    if price > trigger:                                  # already broke out -> skip (chasing)
        return None
    stop = round_cent(apply_adr_stop(trigger, base_lo, adr,
                                     getattr(p, "adr_stop", False), getattr(p, "adr_stop_mult", 1.0)))
    rps = trigger - stop
    if rps <= 0 or (rps / trigger) > p.max_risk_frac:
        return None

    # ---- quality factors ----
    base_vol = sum(vols[-cons:]) / cons                                  # avg volume IN the base
    ref_slice = vols[-(cons + 50):-cons] if n >= cons + 50 else vols[:-cons] or vols
    ref_vol = (sum(ref_slice) / len(ref_slice)) if ref_slice else base_vol   # prior-run avg volume
    pre_base_low = min(lows[-(cons + 20):-cons]) if n >= cons + 20 else base_lo
    higher_lows = base_lo > pre_base_low                                 # base holding above prior lows
    score, comp = _breakout_quality(price, perf3m, adr, base_range_pct, off_high, base_vol, ref_vol,
                                    above_200, higher_lows, getattr(p, "spy_perf3m", 0.0),
                                    p.quality_weights, p.max_base_range_pct)

    return {
        "sym": sym, "setup": "breakout", "price": price, "trigger": trigger, "stop": stop,
        "rps": rps, "perf3m": perf3m, "adr": adr, "off_high": off_high,
        "rs": perf3m - (getattr(p, "spy_perf3m", 0.0) or 0.0),      # relative strength vs SPY
        "dollar_vol_m": dollar_vol_m, "base_range_pct": base_range_pct,
        "voldry": (ref_vol / base_vol) if base_vol else 0.0, "above_200": above_200,
        "higher_lows": higher_lows, "score": score, "score_parts": comp,
    }


def analyze_parabolic_long(sym: str, bars: list, p: SimpleNamespace):
    """Parabolic LONG (bounce): a former parabolic that ran up then crashed
    ~50-60%+ in a few days, now basing near the low and about to make its first
    range-break to the upside. We place a BUY-STOP at the recent swing high; the
    protective stop is the crash low. Daily-bar approximation of his intraday
    'first green candle / opening range high' entry."""
    n = len(bars)
    if n < p.warmup:
        return None
    closes = [b["c"] for b in bars]
    highs = [b["h"] for b in bars]
    lows = [b["l"] for b in bars]
    price = closes[-1]
    if price < p.min_price:
        return None
    i = n - 1
    lb = p.pl_lookback
    if i < lb + p.pl_runup_days + 1:
        return None
    hh_idx = max(range(i - lb, i), key=lambda k: highs[k])     # parabolic peak (past)
    hh = highs[hh_idx]
    ll_idx = min(range(hh_idx, i + 1), key=lambda k: lows[k])  # crash low after peak
    ll = lows[ll_idx]
    if hh <= 0 or ll <= 0 or ll_idx <= hh_idx:
        return None
    if (hh - ll) / hh * 100.0 < p.pl_drop:                     # big crash
        return None
    if (ll_idx - hh_idx) > p.pl_drop_days:                     # fast crash
        return None
    ru0 = hh_idx - p.pl_runup_days
    if ru0 < 0 or not closes[ru0]:
        return None
    if (hh / closes[ru0] - 1.0) * 100.0 < p.pl_runup:         # was parabolic
        return None
    if (i - ll_idx) > p.pl_bounce_within:                      # bounce still fresh
        return None
    if price > ll * (1.0 + p.pl_max_bounce / 100.0):          # not already chased off the low
        return None
    trigger = round_cent(max(highs[-2:]) * (1.0 + p.breakout_buffer_pct / 100.0))
    if price > trigger:                                        # already broke -> skip
        return None
    adr = adr_pct_at(bars, i, 20)
    stop = round_cent(apply_adr_stop(trigger, min(lows[ll_idx:]), adr,     # crash low, capped at ~1 ADR
                                     getattr(p, "adr_stop", False), getattr(p, "adr_stop_mult", 1.0)))
    rps = trigger - stop
    if rps <= 0 or (rps / trigger) > p.max_risk_frac:
        return None
    dollar_vol_m = (sum(b["c"] * b["v"] for b in bars[-20:]) / min(20, n)) / 1e6
    if dollar_vol_m < p.min_dollar_vol_m:
        return None
    drop = (hh - ll) / hh * 100.0
    freshness = max(0, p.pl_bounce_within - (i - ll_idx))      # nearer the low = fresher bounce
    return {
        "sym": sym, "setup": "parabolic_long", "price": price, "trigger": trigger, "stop": stop,
        "rps": rps, "perf3m": -drop, "adr": adr or 0.0, "off_high": (price / hh - 1.0) * 100.0,
        "dollar_vol_m": dollar_vol_m,
        # reward a bigger crash + ADR sweet-spot (capped) + a fresher bounce off the low
        "score": drop + 5.0 * min(adr or 0.0, ADR_SWEET_CAP) + 3.0 * freshness,
    }


def analyze_pullback(sym: str, bars: list, p: SimpleNamespace):
    """Qullamaggie MA-PULLBACK / continuation: a strong leader (same quality universe as the
    breakout) in an established uptrend that has pulled back to a RISING 10/20-day MA and is about
    to resume. We place a BUY-STOP at the PRIOR day's high (the reclaim trigger); the protective
    stop is the pullback swing low. This lets the bot join leaders it missed on the first breakout
    (the late-entry gap) at a lower-risk, higher-win-rate entry. Daily-bar approximation of his
    intraday 'buy the bounce off the 10/20MA' continuation entry. Scored on the same quality scale
    as the breakout so its floor/sleeve are directly comparable."""
    n = len(bars)
    if n < p.warmup:
        return None
    closes = [b["c"] for b in bars]
    highs = [b["h"] for b in bars]
    lows = [b["l"] for b in bars]
    vols = [b["v"] for b in bars]
    price = closes[-1]
    if price < p.min_price:
        return None

    sma20 = sum(closes[-20:]) / 20
    sma50 = sum(closes[-50:]) / 50
    if not (price > sma20 > sma50):                      # uptrend
        return None
    above_200 = n >= 200 and price > (sum(closes[-200:]) / 200)

    base_c = closes[-1 - 63] if n > 63 else closes[0]
    perf3m = (price / base_c - 1.0) * 100.0 if base_c else 0.0
    if perf3m < p.min_move_pct or perf3m > p.max_move_pct:   # same leader filter as breakout
        return None

    pb_ma = int(getattr(p, "pb_ma", 10))
    def ma_at(k):                                        # rolling mean of the reference MA at bar k
        return (sum(closes[k - pb_ma + 1:k + 1]) / pb_ma) if k >= pb_ma - 1 else None
    ma_now = ma_at(n - 1)
    ma_prev = ma_at(n - 6)
    if ma_now is None or ma_prev is None or ma_now <= ma_prev:   # the MA must be RISING
        return None

    lb = int(getattr(p, "pb_lookback", 8))
    near = getattr(p, "pb_near", 2.0)
    tagged = False                                       # a recent low pulled back to the MA
    for k in range(max(pb_ma - 1, n - 1 - lb), n - 1):   # exclude today
        m = ma_at(k)
        if m is not None and lows[k] <= m * (1.0 + near / 100.0):
            tagged = True
            break
    if not tagged:
        return None

    adr = adr_pct_at(bars, n - 1, 20)
    if adr is None or adr < p.min_adr_pct:
        return None

    hi_52 = max(highs[-252:])
    off_high = (price / hi_52 - 1.0) * 100.0
    if off_high < -p.near_high_pct:
        return None

    dollar_vol_m = (sum(b["c"] * b["v"] for b in bars[-20:]) / min(20, n)) / 1e6
    if dollar_vol_m < p.min_dollar_vol_m:
        return None

    # reclaim trigger = prior day's high (buy-stop) — the resumption must still be ahead (not already
    # reclaimed), and we don't chase if the trigger is already far above the MA.
    trigger = round_cent(highs[-1] * (1.0 + p.breakout_buffer_pct / 100.0))
    if price > trigger:
        return None
    if (trigger / ma_now - 1.0) * 100.0 > getattr(p, "pb_max_ext", 5.0):
        return None

    pb_low = min(lows[max(0, n - 1 - lb):n])             # pullback swing low
    stop = round_cent(apply_adr_stop(trigger, pb_low, adr,
                                     getattr(p, "adr_stop", False), getattr(p, "adr_stop_mult", 1.0)))
    rps = trigger - stop
    if rps <= 0 or (rps / trigger) > p.max_risk_frac:
        return None

    # ---- quality factors (same scale as breakout, computed over the cons-day window) ----
    cons = p.cons_days
    base_hi = max(highs[-cons:])
    base_lo = min(lows[-cons:])
    base_range_pct = (base_hi / base_lo - 1.0) * 100.0 if base_lo > 0 else 0.0
    base_vol = sum(vols[-cons:]) / cons
    ref_slice = vols[-(cons + 50):-cons] if n >= cons + 50 else vols[:-cons] or vols
    ref_vol = (sum(ref_slice) / len(ref_slice)) if ref_slice else base_vol
    pre_base_low = min(lows[-(cons + 20):-cons]) if n >= cons + 20 else base_lo
    higher_lows = base_lo > pre_base_low
    score, comp = _breakout_quality(price, perf3m, adr, base_range_pct, off_high, base_vol, ref_vol,
                                    above_200, higher_lows, getattr(p, "spy_perf3m", 0.0),
                                    p.quality_weights, p.max_base_range_pct)

    return {
        "sym": sym, "setup": "pullback", "price": price, "trigger": trigger, "stop": stop,
        "rps": rps, "perf3m": perf3m, "adr": adr, "off_high": off_high,
        "rs": perf3m - (getattr(p, "spy_perf3m", 0.0) or 0.0),
        "dollar_vol_m": dollar_vol_m, "base_range_pct": base_range_pct,
        "voldry": (ref_vol / base_vol) if base_vol else 0.0, "above_200": above_200,
        "higher_lows": higher_lows, "score": score, "score_parts": comp,
    }


ANALYZERS = {"breakout": analyze_breakout, "parabolic_long": analyze_parabolic_long,
             "pullback": analyze_pullback}


def market_regime(cfg: dict):
    """Qullamaggie's market filter: trend-following setups only work when the broad market is trending
    up. Rule: the index's short MA above its long MA = GOOD (take breakouts/EP); below = BAD (step aside,
    'breakouts don't exist in a falling market'). Returns (ok: bool, detail: str).

    cfg: regime_symbol (QQQ), regime_fast_ma (10), regime_slow_ma (20). Fail-open if data is missing."""
    sym = cfg.get("regime_symbol", "QQQ")
    fast_n = int(cfg.get("regime_fast_ma", 10))
    slow_n = int(cfg.get("regime_slow_ma", 20))
    bars = fetch(sym, cfg.get("data_source", "auto"), cfg.get("data_range", "1y"))
    if not bars or len(bars) < slow_n + 1:
        return True, f"{sym} regime unknown (no data) — not blocking"   # fail-open, don't freeze the bot
    closes = [b["c"] for b in bars]
    fast = sum(closes[-fast_n:]) / fast_n
    slow = sum(closes[-slow_n:]) / slow_n
    ok = fast > slow
    return ok, (f"{sym} {fast_n}MA {fast:.2f} {'>' if ok else '<='} {slow_n}MA {slow:.2f} "
                f"-> {'GOOD (uptrend)' if ok else 'BAD (step aside)'}")


def scan_setups(cfg: dict, limit: int = None):
    """Fetch the universe and return ranked coiled-breakout candidates."""
    p = SimpleNamespace(
        warmup=150, min_price=cfg["min_price"], min_move_pct=cfg["min_move_pct"],
        max_move_pct=cfg["max_move_pct"], cons_days=cfg["cons_days"],
        max_base_range_pct=cfg["max_base_range_pct"], min_adr_pct=cfg["min_adr_pct"],
        near_high_pct=cfg["near_high_pct"], min_dollar_vol_m=cfg["min_dollar_vol_m"],
        breakout_buffer_pct=cfg["breakout_buffer_pct"], max_risk_frac=cfg["max_risk_frac"],
        # parabolic-long params
        pl_lookback=cfg.get("pl_lookback", 40), pl_runup=cfg.get("pl_runup", 50.0),
        pl_runup_days=cfg.get("pl_runup_days", 20), pl_drop=cfg.get("pl_drop", 50.0),
        pl_drop_days=cfg.get("pl_drop_days", 15),
        pl_bounce_within=cfg.get("pl_bounce_within", 5),
        pl_max_bounce=cfg.get("pl_max_bounce", 30.0),
        # pullback / continuation params
        pb_ma=cfg.get("pb_ma", 10), pb_lookback=cfg.get("pb_lookback", 8),
        pb_near=cfg.get("pb_near", 2.0), pb_max_ext=cfg.get("pb_max_ext", 5.0),
        # quality-ranking weights (breakout); cfg override merges over the defaults
        quality_weights={**QUALITY_WEIGHTS, **(cfg.get("quality_weights") or {})},
        adr_stop=cfg.get("adr_stop", False), adr_stop_mult=cfg.get("adr_stop_mult", 1.0),
        max_ext_pct=cfg.get("max_ext_pct", 0),
    )
    # Relative strength benchmark: default to the index Qullamaggie actually watches — the Nasdaq
    # (QQQ), same as the regime filter — so breakout RS = stock 3m − benchmark 3m. Override via
    # rs_benchmark; falls back to regime_symbol (QQQ) for one consistent "market" gauge.
    bench = cfg.get("rs_benchmark") or cfg.get("regime_symbol", "QQQ")
    try:
        bb = fetch(bench, cfg["data_source"], cfg["data_range"])
        p.spy_perf3m = ((bb[-1]["c"] / bb[-1 - 63]["c"] - 1.0) * 100.0) if bb and len(bb) > 63 else 0.0
        log(f"RS benchmark: {bench} 3-month = {p.spy_perf3m:+.1f}%")
    except Exception:
        p.spy_perf3m = 0.0
    setups = cfg.get("setups") or ["breakout"]
    analyzers = [(s, ANALYZERS[s]) for s in setups if s in ANALYZERS]
    if cfg["universe"] == "us":
        tickers = get_us_universe(min_cap_m=cfg["min_cap_m"], max_cap_m=cfg["max_cap_m"],
                                  min_price=cfg["min_price"])
    else:
        tickers = list(DEFAULT_UNIVERSE)
    if cfg.get("max_symbols"):
        tickers = sorted(set(tickers))[: cfg["max_symbols"]]
    else:
        tickers = sorted(set(tickers))

    log(f"scanning {len(tickers)} symbols; setups={[s for s, _ in analyzers]} ...")
    from concurrent.futures import ThreadPoolExecutor, as_completed
    cands = []
    with ThreadPoolExecutor(max_workers=10) as ex:
        futs = {ex.submit(fetch, s, cfg["data_source"], cfg["data_range"]): s for s in tickers}
        for fut in as_completed(futs):
            s = futs[fut]
            try:
                bars = fut.result()
            except Exception:
                bars = None
            if not bars:
                continue
            best = None                             # one candidate per symbol (highest score)
            for _, fn in analyzers:
                c = fn(s, bars, p)
                if c and (best is None or c["score"] > best["score"]):
                    best = c
            if best:
                cands.append(best)
    cands.sort(key=lambda c: c["score"], reverse=True)
    return cands[:limit] if limit else cands


# ─────────────────────────── EP (Episodic Pivot) scan ───────────────────────────
def fetch_intraday_5m(sym: str, timeout: int = 15):
    """Today's 5-minute bars from Yahoo, plus prev close and last price. For the EP
    opening range. Returns {'bars':[{o,h,l,c,v}], 'prev_close':x, 'last':y} or None."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=1d&interval=5m"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (qm-bot)"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            j = json.loads(r.read().decode("utf-8", "replace"))
        res = j["chart"]["result"][0]
        q = res["indicators"]["quote"][0]
        ts = res.get("timestamp") or []
        bars = []
        for i in range(len(ts)):
            hi, lo, op, cl, vo = q["high"][i], q["low"][i], q["open"][i], q["close"][i], q["volume"][i]
            if None in (hi, lo, cl):
                continue
            bars.append({"o": op or cl, "h": hi, "l": lo, "c": cl, "v": vo or 0})
        meta = res.get("meta", {})
        return {"bars": bars, "prev_close": meta.get("chartPreviousClose"),
                "last": meta.get("regularMarketPrice")}
    except (urllib.error.URLError, urllib.error.HTTPError, KeyError, ValueError,
            json.JSONDecodeError, TimeoutError, IndexError):
        return None


def scan_ep(cfg: dict):
    """Episodic Pivot LONG (faithful): confirm an EARNINGS catalyst (Nasdaq calendar),
    require a >= ep_gap% opening gap in a not-already-extended name, and enter the OPENING
    RANGE high (from 5-min intraday). Stop = opening range low. Runs near the open."""
    E = earnings
    p = SimpleNamespace(
        min_price=cfg["min_price"], min_dollar_vol_m=cfg["min_dollar_vol_m"],
        breakout_buffer_pct=cfg["breakout_buffer_pct"], max_risk_frac=cfg["max_risk_frac"],
        ep_gap=cfg.get("ep_gap", 10.0), ep_max_prior=cfg.get("ep_max_prior", 50.0),
        ep_or_bars=max(1, cfg.get("ep_or_bars", 1)),
        ep_min_vol_frac=cfg.get("ep_min_vol_frac", 0.05),
        ep_min_surprise=cfg.get("ep_min_surprise", 0.0),
        adr_stop=cfg.get("adr_stop", False), adr_stop_mult=cfg.get("adr_stop_mult", 1.0),
    )
    recent = E.recent_earnings()
    if not recent:
        log("EP: no earnings names for today / prev trading day")
        return []
    log(f"EP: {len(recent)} earnings names; checking gaps + opening ranges ...")
    cands = []
    for sym, info in recent.items():
        # optional earnings-beat filter
        if p.ep_min_surprise and (info.get("surprise") is None or info["surprise"] < p.ep_min_surprise):
            continue
        daily = fetch(sym, cfg["data_source"], cfg["data_range"])
        if not daily or len(daily) < 130:
            continue
        prev_close = daily[-2]["c"]
        today_open = daily[-1]["o"]
        if not prev_close:
            continue
        gap = (today_open / prev_close - 1.0) * 100.0
        if gap < p.ep_gap:                                  # must gap up enough
            continue
        c6 = daily[-1 - 126]["c"]                           # not already run huge (catalyst is fresh)
        if c6 and (prev_close / c6 - 1.0) * 100.0 > p.ep_max_prior:
            continue
        price = daily[-1]["c"]
        if price < p.min_price:
            continue
        dollar_vol_m = (sum(b["c"] * b["v"] for b in daily[-20:]) / min(20, len(daily))) / 1e6
        if dollar_vol_m < p.min_dollar_vol_m:
            continue
        intr = fetch_intraday_5m(sym)                       # opening range from 5-min bars
        if not intr or not intr["bars"]:
            continue
        orb = intr["bars"][: p.ep_or_bars]
        or_high = max(b["h"] for b in orb)
        or_low = min(b["l"] for b in orb)
        avgvol = sum(b["v"] for b in daily[-20:]) / min(20, len(daily))
        volsofar = sum(b["v"] for b in intr["bars"])
        if avgvol > 0 and volsofar < p.ep_min_vol_frac * avgvol:   # volume surge sanity
            continue
        trigger = round_cent(or_high * (1.0 + p.breakout_buffer_pct / 100.0))
        adr = adr_pct_at(daily, len(daily) - 1, 20) or 0.0
        stop = round_cent(apply_adr_stop(trigger, or_low, adr,          # OR low, capped at ~1 ADR
                                         p.adr_stop, p.adr_stop_mult))
        rps = trigger - stop
        if rps <= 0 or (rps / trigger) > p.max_risk_frac:
            continue
        last = intr.get("last") or price
        if last > trigger * (1.0 + p.max_risk_frac):        # already ran too far past the ORH
            continue
        rvol = (volsofar / avgvol) if avgvol > 0 else 0.0   # opening relative volume (conviction)
        cands.append({
            "sym": sym, "setup": "ep", "price": price, "trigger": trigger, "stop": stop,
            "rps": rps, "perf3m": gap, "adr": adr, "off_high": 0.0,
            "dollar_vol_m": dollar_vol_m, "surprise": info.get("surprise"), "rvol": rvol,
            # reward a bigger gap + earnings beat + opening relative-volume + ADR sweet-spot
            "score": gap + (info.get("surprise") or 0.0) + 5.0 * _clamp(rvol, 0.0, 5.0)
                     + 2.0 * min(adr, ADR_SWEET_CAP),
        })
    cands.sort(key=lambda c: c["score"], reverse=True)
    log(f"EP: {len(cands)} gap-up earnings setups")
    return cands


# ─────────────────────────────── the bot ───────────────────────────────
class QMBot:
    def __init__(self, cfg: dict, allow_live: bool):
        self.cfg = cfg
        self.paper = bool(cfg.get("paper", True))
        self.dry = bool(cfg.get("dry_run", True))
        self.allow_live = allow_live
        self.state = load_state()
        self.ib = None
        # Per-setup trades CSV in the app root: the configured trade_log_csv is a BASE name and the
        # setup is inserted, e.g. "qm_trades.csv" -> qm_trades_breakout.csv / qm_trades_ep.csv
        # (mirrors supertrend's supertrend_trades_<name>.csv). Created on first close, appended after.
        self.trades_csv_base = os.path.join(_APP_DIR, cfg.get("trade_log_csv", "qm_trades.csv"))
        if not self.paper and not allow_live:
            raise SystemExit("REFUSING: config paper=false but --i-understand-live not passed. "
                             "Aborting to protect a live account.")

    # ---- IB connection (resilient — mirrors supertrend_bot) ----
    def _wire_events(self):
        # errorEvent carries IB 1100/1101/1102 connectivity notices + order reject/cancel reasons.
        # execDetailsEvent = real fills (time/price/qty). orderStatusEvent = status changes
        # (Filled / Cancelled). disconnectedEvent = a real socket drop (Gateway daily restart).
        self._order_status_seen = {}             # orderId -> last status (dedupe status spam)
        for hook, fn in (("errorEvent", self._on_error),
                         ("disconnectedEvent", self._on_disconnected),
                         ("execDetailsEvent", self._on_exec),
                         ("orderStatusEvent", self._on_order_status)):
            try:
                getattr(self.ib, hook).__iadd__(fn)
            except Exception:
                pass

    def _setup_for(self, sym: str) -> str:
        return self.state["positions"].get(sym, {}).get("setup", "breakout")

    def _trail_sma_for(self, setup: str) -> int:
        """Per-setup moving average (trail length, or 1st take-profit MA for parabolic). His defaults:
        breakout 20, EP 50, parabolic 10. Override via cfg['trail_sma_by_setup']."""
        defaults = {"breakout": 20, "ep": 50, "parabolic_long": 10, "pullback": 20}
        m = self.cfg.get("trail_sma_by_setup") or {}
        return int(m.get(setup, defaults.get(setup, self.cfg.get("trail_sma", 20))))

    def _exit_mode_for(self, setup: str) -> str:
        """'trail' = trend trail (breakout/ep); 'target_ma' = take-profit into the MA (parabolic)."""
        m = self.cfg.get("exit_mode_by_setup") or {}
        return m.get(setup, "target_ma" if setup == "parabolic_long" else "trail")

    # Benign data-farm status notices — not errors, don't spam the log with them.
    _BENIGN_CODES = {2104, 2106, 2107, 2108, 2119, 2158, 2100, 2150}

    def _on_error(self, *args):
        # ib_async: (reqId, errorCode, errorString, contract, ...)
        reqId = args[0] if len(args) > 0 else None
        code = args[1] if len(args) > 1 else None
        msg = args[2] if len(args) > 2 else ""
        contract = args[3] if len(args) > 3 else None
        if code == 1100:
            self._conn_ok = False
            log("IB error 1100: connectivity to IB LOST — data/orders will fail until restored")
        elif code in (1101, 1102):
            self._conn_ok = True
            log(f"IB error {code}: connectivity RESTORED — resuming")
        elif code in self._BENIGN_CODES:
            return                               # data-farm OK notices — ignore
        else:
            # Everything else: order rejects/cancels (201/202/203/10147/10148…) + warnings. These carry
            # the CANCEL/REJECT REASON. Tag the symbol/order when we can.
            sym = getattr(contract, "symbol", None)
            where = f" {sym}" if sym else ""
            log(f"IB msg code={code} order/req={reqId}{where}: {msg}",
                setup=self._setup_for(sym) if sym else None)

    def _on_exec(self, trade, fill):
        """Real fill — log time/price/qty. On an ENTRY (BOT) fill, stamp the actual fill into state."""
        try:
            ex = fill.execution
            sym = trade.contract.symbol
            setup = self._setup_for(sym)
            side = "BUY" if ex.side == "BOT" else "SELL"
            kind = "ENTRY FILLED" if ex.side == "BOT" else "EXIT FILLED"
            log(f"{kind}: {side} {int(ex.shares)} {sym} @ {ex.price:.2f}  "
                f"time={ex.time}  order={ex.orderId}  cum={int(ex.cumQty)}", setup=setup)
            if ex.side == "BOT":                 # entry hit -> record actual open date/price in state
                pos = self.state["positions"].get(sym)
                if pos is not None:
                    first_fill = pos.get("entry_date") is None
                    if first_fill:
                        pos["entry_date"] = now_et().strftime("%Y-%m-%d")
                    pos["fill_price"] = ex.price
                    save_state(self.state)
                    if first_fill and not pos.get("entry_logged"):
                        self._record_entry(sym, pos, ex.price)   # write ENTRY row w/ quality factors
                        pos["entry_logged"] = True
                        save_state(self.state)
        except Exception as e:
            log(f"exec-log error: {e}")

    def _on_order_status(self, trade):
        """Log meaningful order-status transitions (Filled / Cancelled / Inactive), once each."""
        try:
            oid = trade.order.orderId
            status = trade.orderStatus.status
            if self._order_status_seen.get(oid) == status:
                return
            self._order_status_seen[oid] = status
            if status in ("Cancelled", "ApiCancelled", "Inactive", "PendingCancel"):
                sym = trade.contract.symbol
                o = trade.order
                log(f"ORDER {status}: {o.action} {int(o.totalQuantity)} {sym} "
                    f"{o.orderType}@{o.auxPrice or o.lmtPrice or 0} id={oid} "
                    f"(reason in the IB msg line above, if any)", setup=self._setup_for(sym))
        except Exception as e:
            log(f"order-status-log error: {e}")

    def _on_disconnected(self):
        log("API socket disconnected — will reconnect on next tick")

    def log_status(self):
        """Periodic snapshot of resting open orders + positions. To avoid log spam (this fires hourly)
        the DETAIL lines print only when the book CHANGES vs the last snapshot; otherwise a single
        compact line. Order fills/cancels are logged in real time regardless."""
        try:
            trades = self.ib.openTrades()
        except Exception as e:
            log(f"status: openTrades error {e}")
            return
        oo = [t for t in trades if t.orderStatus.status in ("PreSubmitted", "Submitted")]
        pos = self.ib_positions()
        # signature of the current book; detail only when it changes
        sig = "|".join(sorted(f"{t.order.action}{int(t.order.totalQuantity)}{t.contract.symbol}"
                              f"@{t.order.auxPrice or t.order.lmtPrice or 0}" for t in oo)) \
            + "##" + "|".join(f"{s}:{q}" for s, q in sorted(pos.items()))
        if sig == getattr(self, "_status_sig", None):
            log(f"STATUS: {len(oo)} open order(s), {len(pos)} position(s) (unchanged)")
            return
        self._status_sig = sig
        log(f"STATUS: {len(oo)} open order(s), {len(pos)} position(s) [changed — detail below]")
        for t in oo:
            o, c = t.order, t.contract
            px = o.auxPrice or o.lmtPrice or 0
            log(f"  OPEN {o.action} {int(o.totalQuantity)} {c.symbol} {o.orderType}@{px} "
                f"[{t.orderStatus.status}] filled={int(t.orderStatus.filled)} id={o.orderId}")
        for sym, sh in pos.items():
            st = self.state["positions"].get(sym, {})
            ep = st.get("fill_price") or st.get("entry_price")
            log(f"  POS {sym} x{sh}" + (f" entry~{ep:.2f}" if ep else "")
                + (f" stop {st.get('stop'):.2f}" if st.get("stop") else ""))

    def _connect_once(self):
        """(Re)open a FRESH IB client and connect. A new IB() per attempt is deliberate:
        reconnecting on the object whose socket was just dropped often fails with
        clientId-in-use / dead-transport errors (the reconnect-doesn't-work bug)."""
        from ib_async import IB
        try:
            if self.ib is not None and self.ib.isConnected():
                self.ib.disconnect()
        except Exception:
            pass
        self.ib = IB()                           # fresh client bound to this loop
        self._wire_events()
        host, cid = self.cfg["host"], int(self.cfg["client_id"])
        self.ib.connect(host, int(self.cfg["port"]), clientId=cid,
                        account=self.cfg.get("account", "") or "")
        # adopt the sole managed account if the configured one isn't managed by this login
        try:
            mgd = list(self.ib.managedAccounts() or [])
            acct = self.cfg.get("account", "") or ""
            if mgd and acct not in mgd and len(mgd) == 1:
                log(f"account '{acct or '(none)'}' not managed by this login; using {mgd[0]}")
                self.cfg["account"] = mgd[0]
        except Exception:
            pass
        try:
            self.ib.reqPositions()               # keep positions() cache populated
        except Exception:
            pass
        self._conn_ok = True

    def connect(self):
        import asyncio
        self._conn_ok = True
        try:                                     # dedicated loop, mirrors supertrend
            asyncio.set_event_loop(asyncio.new_event_loop())
        except Exception:
            pass
        mode = "PAPER" if self.paper else "LIVE"
        log(f"connecting to IB {self.cfg['host']}:{self.cfg['port']} "
            f"clientId={self.cfg['client_id']} [{mode}] {'DRY-RUN' if self.dry else 'ARMED'}")
        self._connect_once()
        self.ib.sleep(1.0)
        log(f"connected clientId={self.cfg['client_id']} account={self.cfg.get('account') or '(auto)'}")

    def ensure_connected(self) -> bool:
        """True once connected. If the socket dropped (Gateway restart / a competing login bumped
        our API client), keep retrying indefinitely — fast at first (clientId usually frees within
        seconds), then every `reconnect_backoff_sec` (default 60s). On a successful reconnect it
        re-subscribes positions and reconciles state so nothing is double-entered/orphaned. This is
        a swing bot with no daily exit, so it never gives up (positions rest on server-side stops)."""
        if self.ib and self.ib.isConnected():
            if not self._conn_ok:                # socket alive but IB signalled 1100 -> wait for 1102
                log("IB connectivity lost (1100); socket alive, waiting for restore (1102)...")
                while self.ib.isConnected() and not self._conn_ok:
                    self._safe_sleep(2)
                if self.ib.isConnected():
                    return True
            else:
                return True
        steady = int(self.cfg.get("reconnect_backoff_sec", 60))
        log(f"socket down (Gateway restart or a competing login may have bumped the session); "
            f"retrying until reconnected — fast, then every {steady}s...")
        attempt = 0
        while True:
            attempt += 1
            try:
                self._connect_once()
                log(f"reconnected (attempt {attempt})")
                try:
                    self.reconcile()             # re-adopt live positions; drop closed ones
                except Exception as e:
                    log(f"post-reconnect reconcile error: {e}")
                return True
            except Exception as e:
                wait = 5 if attempt <= 3 else steady   # quick retries first, then ~every minute
                log(f"reconnect attempt {attempt} failed: {e}; retrying in {wait}s "
                    f"(is IB Gateway logged in? enable Gateway auto-restart so it relogs in)")
                self._safe_sleep(wait)

    def _safe_sleep(self, secs):
        """Sleep WITHOUT letting a dropped-socket error escape. `ib.sleep()` pumps the asyncio
        loop, which raises ConnectionError / asyncio.CancelledError the moment the peer closes the
        socket (e.g. the Gateway's daily restart). If that propagated out of run_loop the bot would
        die and never reconnect. So pump events while the socket is up, else a plain thread sleep;
        on ANY error (incl. the BaseException CancelledError) fall back to a plain sleep."""
        import asyncio
        import time as _t
        try:
            if self.ib is not None and self.ib.isConnected():
                self.ib.sleep(secs)
            else:
                _t.sleep(secs)
        except (asyncio.CancelledError, Exception):
            _t.sleep(secs)

    def disconnect(self):
        try:
            if self.ib and self.ib.isConnected():
                self.ib.disconnect()
        except Exception:
            pass

    # ---- account / positions ----
    def _capital_for(self, setup: str) -> float:
        """Capital SLEEVE for a strategy. Each setup sizes off its own allocation (e.g. $100k for
        breakout / ep / parabolic_long) via `strategy_capital_by_setup`; falls back to a flat
        `strategy_capital`, else the live NetLiquidation/override. Risk-per-trade and the position
        notional cap are both computed off THIS sleeve, so the three strategies are independent."""
        m = self.cfg.get("strategy_capital_by_setup") or {}
        if setup in m:
            return float(m[setup])
        if self.cfg.get("strategy_capital"):
            return float(self.cfg["strategy_capital"])
        return self.capital()

    def capital(self) -> float:
        if self.cfg.get("capital_override"):
            return float(self.cfg["capital_override"])
        try:
            for v in self.ib.accountSummary():
                if v.tag == "NetLiquidation":
                    return float(v.value)
        except Exception:
            pass
        return 0.0

    def ib_positions(self) -> dict:
        """symbol -> shares held (long, from IB)."""
        out = {}
        for pos in self.ib.positions():
            if pos.contract.secType == "STK" and pos.position:
                out[pos.contract.symbol] = out.get(pos.contract.symbol, 0) + int(pos.position)
        return out

    def open_entry_symbols(self) -> set:
        """Symbols with a live (unfilled) BUY-STOP entry order resting."""
        syms = set()
        for t in self.ib.openTrades():
            o, c = t.order, t.contract
            if (c.secType == "STK" and o.action == "BUY"
                    and t.orderStatus.status in ("PreSubmitted", "Submitted")):
                syms.add(c.symbol)
        return syms

    def cancel_stale_entries(self):
        """Cancel every still-resting BUY (entry) order and drop its pending state, so each morning
        re-arms from a CLEAN slate using the fresh quality ranking + today's levels. This makes the
        bot correct even if entry_tif is GTC (DAY orders already expire at the close, but this also
        clears any that lingered — e.g. placed after-hours, or carried across a Gateway restart).
        A child protective SELL stop is left alone: it only activates once its parent entry FILLED,
        i.e. it belongs to a real position, not to an unfilled entry."""
        if self.dry:
            return
        cancelled = 0
        for t in self.ib.openTrades():
            o, c = t.order, t.contract
            if (c.secType == "STK" and o.action == "BUY"
                    and t.orderStatus.status in ("PreSubmitted", "Submitted")):
                sym = c.symbol
                try:
                    self.ib.cancelOrder(o)
                    cancelled += 1
                    log(f"cancel-refresh: cancelled leftover entry order {sym} "
                        f"{o.orderType}@{o.auxPrice or o.lmtPrice or 0} id={o.orderId}",
                        setup=self._setup_for(sym))
                except Exception as e:
                    log(f"cancel-refresh: failed to cancel {sym} id={o.orderId}: {e}")
                # drop the pending (unfilled) state entry so the slot frees for the fresh scan
                pos = self.state["positions"].get(sym)
                if pos is not None and pos.get("entry_date") is None and not pos.get("adopted"):
                    del self.state["positions"][sym]
        if cancelled:
            self.ib.sleep(0.5)
            save_state(self.state)
            log(f"cancel-refresh: cleared {cancelled} unfilled entry order(s) before re-scan")

    def _stk(self, sym: str):
        from ib_async import Stock
        c = Stock(sym, "SMART", "USD")
        self.ib.qualifyContracts(c)
        return c

    # ---- startup reconciliation ----
    def reconcile(self):
        live = self.ib_positions()
        try:
            pending = self.open_entry_symbols()   # symbols with a resting (unfilled) BUY-STOP entry
        except Exception:
            pending = set()
        st = self.state["positions"]
        for sym in list(st.keys()):
            pos = st[sym]
            if sym in live:                        # a real position -> trust IB's share count
                st[sym]["shares_left"] = live[sym]
                continue
            if sym in pending:                     # entry buy-stop still working -> KEEP (not filled yet)
                continue
            if pos.get("entry_date") is None and not pos.get("adopted"):
                # entry order never filled and is no longer resting (expired / cancelled) -> drop cleanly
                log(f"reconcile: {sym} entry order gone unfilled -> clearing pending state")
                del st[sym]
                continue
            # was a FILLED position, now flat -> the protective stop hit. Log the closing leg to the
            # trades CSV BEFORE dropping it (reconcile runs before run_manage, so do it here).
            left = pos.get("shares_left", 0)
            if left and left >= 1:
                fill = self._last_sell_fill(sym) or pos.get("stop")
                reason = "BE-Stop" if pos.get("partial_done") else "Stop"
                self._record_leg(sym, pos, left, fill, reason)
            log(f"reconcile: {sym} no longer held (protective stop hit) -> clearing state")
            del st[sym]
        # adopt untracked live positions (manual or pre-existing) so we manage/exit them
        for sym, sh in live.items():
            if sym not in st:
                log(f"reconcile: adopting untracked live position {sym} x{sh} "
                    f"(no entry data; will trail-manage only)")
                st[sym] = {"id": f"{sym}-adopted-{now_et():%Y%m%d-%H%M%S}",
                           "shares": sh, "shares_left": sh, "entry_price": None,
                           "entry_date": now_et().strftime("%Y-%m-%d"), "stop": None,
                           "setup": "adopted", "partial_done": True, "adopted": True}
            else:
                st[sym]["shares_left"] = sh  # trust IB for the live count
        save_state(self.state)

    # ---- ENTRY cycle ----
    def _log_ranked(self, setup: str, cands: list, fresh: list, slots: int, held_syms: set, floor: float):
        """Log every ranked candidate with its quality factors and an ACCURATE per-row status:
        PICK (will be entered) · held (a real position / resting order) · <floor (below quality floor,
        NOT held) · eligible (passed floor, not held, but no free slot). `fresh` = passed floor & not held."""
        fresh_syms = {c["sym"] for c in fresh}
        sel = {c["sym"] for c in fresh[:slots]}         # the ones that will actually be entered
        held_n = sum(1 for c in cands if c["sym"] in held_syms)
        low_n = sum(1 for c in cands if c["sym"] not in held_syms and floor and c.get("score", 0) < floor)
        log(f"{setup}: {len(cands)} passed filters | {len(fresh)} eligible (score>={floor:g} & not held) "
            f"| {held_n} held/pending | {low_n} below floor | entering {len(sel)} into {slots} free slot(s)",
            setup=setup)
        log(f"{setup}: {'RANK':>4} {'SYM':<6} {'SCORE':>7} {'3M%':>6} {'RS%':>6} {'ADR%':>5} "
            f"{'BASE%':>6} {'VDRY':>5} {'OFFHI':>6} {'>200':>4} {'HL':>3}  STATUS", setup=setup)
        for i, c in enumerate(cands, 1):
            sym = c["sym"]
            if sym in sel:
                mark = "PICK"
            elif sym in held_syms:
                mark = "held"
            elif floor and c.get("score", 0) < floor:
                mark = "<floor"
            elif sym in fresh_syms:
                mark = "eligible"            # passed floor, not held, but beyond the free slots
            else:
                mark = "-"
            log(f"{setup}: {i:>4} {sym:<6} {c.get('score',0):>7.0f} "
                f"{c.get('perf3m',0):>6.0f} {c.get('rs',0):>6.0f} {c.get('adr',0):>5.1f} "
                f"{c.get('base_range_pct',0):>6.1f} {c.get('voldry',0):>5.2f} "
                f"{c.get('off_high',0):>6.1f} {('Y' if c.get('above_200') else 'n'):>4} "
                f"{('Y' if c.get('higher_lows') else 'n'):>3}  {mark}", setup=setup)

    def _place_candidates(self, cands: list, setup: str):
        """Place a SINGLE strategy's ranked candidates. Each strategy has its OWN cap of
        `max_positions` (10) — breakout / ep / parabolic_long are independent, 1% risk each.
        A symbol already held/pending in ANY strategy is skipped (never two orders on one name)."""
        cands = [c for c in cands if c.get("setup") == setup]
        if not cands:
            log(f"{setup}: no candidates — skipping", setup=setup)   # empty scan -> skip cleanly
            return
        st = self.state["positions"]
        live = self.ib_positions()
        pending = self.open_entry_symbols()
        held_syms = set(live) | set(st) | pending                    # dedupe across ALL strategies
        used = sum(1 for pos in st.values() if pos.get("setup") == setup)  # THIS strategy's count
        slots = self.cfg["max_positions"] - used
        cap = self._capital_for(setup)           # per-strategy capital sleeve (e.g. $100k each)
        fresh = [c for c in cands if c["sym"] not in held_syms]
        # QUALITY FLOOR: only take setups whose score clears the bar (quality-driven; max_positions is
        # just the ceiling). On a weak day far fewer than the cap qualify — concentration over count.
        floor = self._min_score_for(setup)
        if floor:
            before = len(fresh)
            fresh = [c for c in fresh if c.get("score", 0) >= floor]
            log(f"{setup}: quality floor {floor}: {len(fresh)}/{before} candidate(s) clear the bar",
                setup=setup)
        # Full ranked list with quality factors + accurate per-row status.
        self._log_ranked(setup, cands, fresh, max(0, slots), held_syms, floor)
        if slots <= 0:
            log(f"{setup}: strategy full ({used}/{self.cfg['max_positions']} held/pending) — skipping",
                setup=setup)
            return
        if cap <= 0:
            log(f"{setup}: capital is 0 (no sleeve / NetLiquidation / override) — skipping", setup=setup)
            return
        risk_dollars = cap * self.cfg["risk_per_trade_pct"]
        log(f"{setup}: {len(fresh)} new candidate(s); {slots} slot(s) free "
            f"({used}/{self.cfg['max_positions']} used); sleeve=${cap:,.0f} "
            f"risk/trade=${risk_dollars:,.0f}", setup=setup)
        placed = 0
        for c in fresh:
            if placed >= slots:
                break
            qty = math.floor(risk_dollars / c["rps"])                 # 1% of the sleeve / per-share risk
            cap_qty = math.floor((cap * self.cfg["max_position_pct"]) / c["trigger"])  # notional cap of sleeve
            qty = max(0, min(qty, cap_qty))
            if qty < 1:
                continue
            self.place_entry(c, qty)
            placed += 1
        if placed == 0:
            log(f"{setup}: no entries placed this cycle", setup=setup)

    def _min_score_for(self, setup: str) -> float:
        """Minimum quality score a candidate must clear to be entered (0 = off). Per-setup because the
        score scales differ (breakout vs ep vs parabolic). cfg: min_quality_score_by_setup {} overrides
        the flat min_quality_score. Calibrate from the ranked-candidate logs / qm_entries_*.csv."""
        m = self.cfg.get("min_quality_score_by_setup") or {}
        if setup in m:
            return float(m[setup])
        return float(self.cfg.get("min_quality_score", 0) or 0)

    def _regime_ok(self, setup: str):
        """(ok_to_enter, detail). Trend setups (breakout/ep) are BLOCKED in a bad market regime;
        counter-trend setups in `regime_exempt_setups` (parabolic_long) are always allowed."""
        if not self.cfg.get("regime_filter", True):
            return True, "regime filter off"
        if setup in set(self.cfg.get("regime_exempt_setups", ["parabolic_long"])):
            return True, "exempt (counter-trend)"
        return market_regime(self.cfg)

    def circuit_breaker_tripped(self):
        """(tripped, detail). Daily-loss circuit breaker: if the ACCOUNT equity (NetLiquidation) is
        down >= daily_loss_limit_pct from the START-OF-DAY equity, halt ALL new entries for the day.
        Exits/management always continue. Disabled when daily_loss_limit_pct = 0."""
        lim = float(self.cfg.get("daily_loss_limit_pct", 0) or 0)
        if lim <= 0:
            return False, "breaker off"
        sod = self.state.get("equity_sod")
        nlv = self.capital()                           # actual account equity (NetLiq/override)
        if not sod or nlv <= 0:
            return False, "no equity reference yet"
        loss = (sod - nlv) / sod
        if loss >= lim:
            return True, f"day loss {loss*100:.2f}% >= limit {lim*100:.1f}% (SOD ${sod:,.0f} -> ${nlv:,.0f})"
        return False, f"day loss {loss*100:.2f}% < limit {lim*100:.1f}%"

    def run_entries(self):
        """Daily scan for the enabled daily setups (breakout / parabolic_long). Each is placed
        SEPARATELY so it gets its own independent cap of max_positions. Trend setups are skipped
        entirely when the market regime is bad (his rule: index short-MA below long-MA)."""
        setups = [s for s in (self.cfg.get("setups") or []) if s in ANALYZERS]
        if not setups:
            return
        trip, d = self.circuit_breaker_tripped()
        if trip:
            log(f"CIRCUIT BREAKER: {d} — NO new entries today")
            return
        cands = scan_setups(self.cfg)                 # ranked, best-per-symbol, all daily setups
        for setup in setups:
            ok, detail = self._regime_ok(setup)
            if not ok:
                log(f"{setup}: market regime BAD ({detail}) — NO new entries today", setup=setup)
                continue
            if self.cfg.get("regime_filter", True) and setup not in \
                    set(self.cfg.get("regime_exempt_setups", ["parabolic_long"])):
                log(f"{setup}: regime OK ({detail})", setup=setup)
            self._place_candidates(cands, setup)

    def run_ep_entries(self):
        """Episodic Pivot open-time scan (only if 'ep' is in `setups`). Own cap of max_positions.
        Blocked when the market regime is bad (EP is a trend/continuation setup)."""
        if "ep" not in (self.cfg.get("setups") or []):
            return
        trip, d = self.circuit_breaker_tripped()
        if trip:
            log(f"ep: CIRCUIT BREAKER: {d} — NO new entries today", setup="ep")
            return
        ok, detail = self._regime_ok("ep")
        if not ok:
            log(f"ep: market regime BAD ({detail}) — NO new entries today", setup="ep")
            return
        log(f"ep: regime OK ({detail})", setup="ep")
        self._place_candidates(scan_ep(self.cfg), "ep")

    def place_entry(self, c: dict, qty: int):
        sym, trig, stop = c["sym"], c["trigger"], c["stop"]
        setup = c.get("setup", "breakout")
        risk = qty * c["rps"]
        msg = (f"ENTRY [{setup}] {sym}: BUY-STOP {qty} @ {trig:.2f}  "
               f"protective SELL-STOP @ {stop:.2f}  "
               f"risk=${risk:,.0f} ({self.cfg['risk_per_trade_pct']*100:.2f}%)  "
               f"perf3m={c['perf3m']:.0f}% ADR={c['adr']:.1f}%")
        if self.dry:
            log("[DRY] " + msg, setup=setup)
            return
        from ib_async import StopOrder
        contract = self._stk(sym)
        parent = StopOrder("BUY", qty, trig)
        parent.orderId = self.ib.client.getReqId()
        parent.transmit = False
        parent.tif = self.cfg.get("entry_tif", "DAY")
        child = StopOrder("SELL", qty, stop)
        child.orderId = self.ib.client.getReqId()
        child.parentId = parent.orderId
        child.transmit = True
        child.tif = "GTC"
        self.ib.placeOrder(contract, parent)
        self.ib.placeOrder(contract, child)
        self.ib.sleep(0.5)
        self.state["positions"][sym] = {
            "id": f"{sym}-{now_et():%Y%m%d-%H%M%S}",     # unique per entry (for entry_id in the CSV)
            "shares": qty, "shares_left": qty, "entry_price": trig, "entry_date": None,
            "stop": stop, "initial_stop": stop, "rps": c["rps"], "trigger": trig,
            "setup": setup,
            "partial_done": False, "parent_id": parent.orderId, "stop_id": child.orderId,
            # per-setup exits: trail length / 1st TP MA, exit mode, and the 2nd TP MA (parabolic)
            "trail_sma": self._trail_sma_for(setup), "exit_mode": self._exit_mode_for(setup),
            "target_ma2": int(self.cfg.get("target_ma2", 20)), "adopted": False,
            # quality factors at entry — persisted so closed trades + snapshots carry their context
            "q": {"score": round(c.get("score", 0), 1), "perf3m": round(c.get("perf3m", 0), 1),
                  "rs": round(c.get("rs", 0), 1), "adr": round(c.get("adr", 0), 2),
                  "base_range_pct": round(c.get("base_range_pct", 0), 1),
                  "voldry": round(c.get("voldry", 0), 2), "off_high": round(c.get("off_high", 0), 1)},
        }
        save_state(self.state)
        log("ARMED " + msg + f"  [order {parent.orderId}/{child.orderId} placed {now_et():%H:%M:%S}]",
            setup=setup)

    # ---- MANAGE cycle ----
    def run_manage(self):
        st = self.state["positions"]
        live = self.ib_positions()
        for sym in list(st.keys()):
            pos = st[sym]
            setup = pos.get("setup", "breakout")
            held = live.get(sym, 0)
            if held <= 0:
                if pos.get("entry_date") is not None:   # was filled, now flat -> closed out (stop hit)
                    left = pos.get("shares_left", 0)
                    if left and left >= 1:              # record the stop-out leg to the trades CSV
                        fill = self._last_sell_fill(sym) or pos.get("stop")
                        reason = "BE-Stop" if pos.get("partial_done") else "Stop"
                        self._record_leg(sym, pos, left, fill, reason)
                    log(f"{sym}: no longer held (protective stop hit) -> clearing", setup=setup)
                    del st[sym]
                    save_state(self.state)
                continue
            # position is live; mark entry_date on first observation of a fill
            if pos.get("entry_date") is None:
                pos["entry_date"] = now_et().strftime("%Y-%m-%d")
            pos["shares_left"] = held

            bars = fetch(sym, self.cfg["data_source"], self.cfg["data_range"])
            if not bars:
                log(f"{sym}: no data to manage this cycle", setup=setup)
                continue
            closes = [b["c"] for b in bars]
            price = closes[-1]
            days_held = self._days_held(bars, pos["entry_date"])
            exit_mode = pos.get("exit_mode", self._exit_mode_for(setup))
            ma_n = int(pos.get("trail_sma", self._trail_sma_for(setup)))
            ma = sma_series(closes, ma_n)[-1]

            if exit_mode == "target_ma":
                # ---- PARABOLIC bounce: TAKE PROFIT into the moving averages (sell into strength) ----
                # These mean-revert, so he targets the 10- then 20-day MA rather than trailing for weeks.
                # The crash-low hard stop (server-side) still guards the downside throughout.
                ma2_n = int(pos.get("target_ma2", self.cfg.get("target_ma2", 20)))
                ma2 = sma_series(closes, ma2_n)[-1]
                max_days = int(self.cfg.get("target_max_days", 15))
                # 1) first target: sell half into SMA(ma_n), move stop to break-even
                if (not pos.get("partial_done")) and ma is not None and price >= ma and held > 0:
                    half = int(held * self.cfg["partial_fraction"])
                    if half >= 1:
                        self._sell(sym, half, f"TP1>=SMA{ma_n}", ref_price=price)
                        pos["partial_done"] = True
                        held -= half
                        pos["shares_left"] = held
                        if pos.get("entry_price"):   # parabolic: BE after TP1 (mean-reverting; be_stop_r not applied here)
                            self._move_stop(sym, pos, round_cent(pos["entry_price"]), note="(break-even)")
                        save_state(self.state)
                # 2) second target: sell the remainder into SMA(ma2_n)
                if pos.get("partial_done") and ma2 is not None and price >= ma2 and held > 0:
                    self._sell(sym, held, f"TP2>=SMA{ma2_n}", ref_price=price)
                    self._cancel_stop(sym, pos)
                    del st[sym]
                    save_state(self.state)
                    continue
                # 3) time cap: a bounce that stalls (never reaches the MA) is exited
                if days_held >= max_days and held > 0:
                    self._sell(sym, held, f"TIME>{max_days}d", ref_price=price)
                    self._cancel_stop(sym, pos)
                    del st[sym]
                    save_state(self.state)
                    continue
                log(f"HOLD {sym} [parabolic]: {held}sh held={days_held}d price={price:.2f} "
                    f"TP@SMA{ma_n}={ma:.2f}/SMA{ma2_n}={ma2:.2f} "
                    f"partial={'Y' if pos.get('partial_done') else 'N'}", setup=setup)
                save_state(self.state)
            else:
                # ---- TREND TRAIL (breakout / ep): partial after N days -> break-even -> trail an MA ----
                # 1) PARTIAL (profit-gated) + move to break-even. Only scale out of a WINNER that's up
                # >= partial_min_r (R). This is true profit-taking (matches Qullamaggie) AND avoids the
                # break-even-above-market bug: a loser is never partialed, so its BE stop is never set
                # above the current price. Losers keep their original stop and trail/stop normally.
                epx = pos.get("fill_price") or pos.get("entry_price")
                rps = pos.get("rps")
                cur_r = ((price - epx) / rps) if (epx and rps) else None
                min_r = self.cfg.get("partial_min_r", 0.5)
                # Qullamaggie sells INTO STRENGTH: fire the partial when price is EXTENDED >= partial_ext_adr
                # ADRs above the trail MA (a climax — can trigger EARLY, catching fast rippers), OR fall back
                # to the time rule (days_held >= partial_days). Both still require up >= partial_min_r, so a
                # loser is never scaled. partial_ext_adr=0 -> pure time rule (unchanged behaviour).
                ext_adr = float(self.cfg.get("partial_ext_adr", 0) or 0)
                adr_now = adr_pct_at(bars, len(bars) - 1, 20)
                ext_fire = bool(ext_adr and ma and adr_now and
                                ((price / ma - 1.0) * 100.0) / adr_now >= ext_adr)
                time_fire = days_held >= self.cfg["partial_days"]
                if (not pos.get("partial_done")) and cur_r is not None and cur_r >= min_r \
                        and (ext_fire or time_fire):
                    half = int(held * self.cfg["partial_fraction"])
                    if half >= 1:
                        self._sell(sym, half, "PARTIAL-EXT" if ext_fire else "PARTIAL", ref_price=price)
                        pos["partial_done"] = True
                        held -= half
                        pos["shares_left"] = held       # the protective stop must resize to the remainder
                        # POST-PARTIAL STOP placement, config-driven via `be_stop_r` (entry + be_stop_r*R):
                        #   <= -90 (e.g. -99) -> DON'T reprice (trail-only: keep the original setup stop and
                        #     let the MA trail catch up — best in backtest), 0 -> break-even, >0 -> lock profit.
                        # We ALWAYS call _move_stop so the resting child stop is resized to `held`; only the
                        # PRICE differs. See backtest_results.html §3 + configuration.html.
                        be_r = self.cfg.get("be_stop_r", 0)
                        epx2 = pos.get("entry_price")
                        rps2 = pos.get("rps") or 0
                        if be_r is not None and be_r > -90 and epx2:
                            new_stop = round_cent(epx2 + (be_r or 0) * rps2)
                            note = "(break-even)" if not be_r else f"(lock {be_r:+g}R)"
                        else:
                            new_stop = pos.get("initial_stop") or pos.get("stop")   # trail-only: keep level
                            note = "(trail-only: keep original stop, resized)"
                        if new_stop:
                            self._move_stop(sym, pos, round_cent(new_stop), note=note)
                        save_state(self.state)
                # 2) TRAIL: first close below the per-setup trail SMA exits the remainder
                if ma is not None and price < ma and held > 0:
                    self._sell(sym, held, f"TRAIL<SMA{ma_n}", ref_price=price)
                    self._cancel_stop(sym, pos)
                    del st[sym]
                    save_state(self.state)
                    continue
                adrs_above = (((price / ma - 1.0) * 100.0) / adr_now) if (ma and adr_now) else None
                log(f"HOLD {sym}: {held}sh held={days_held}d price={price:.2f} "
                    f"trailSMA{ma_n}={ma:.2f} ext={adrs_above:.1f}ADR "
                    f"partial={'Y' if pos.get('partial_done') else 'N'}"
                    if adrs_above is not None else
                    f"HOLD {sym}: {held}sh held={days_held}d price={price:.2f} "
                    f"trailSMA{ma_n}={ma:.2f} partial={'Y' if pos.get('partial_done') else 'N'}",
                    setup=setup)
                save_state(self.state)

    def _days_held(self, bars, entry_date: str) -> int:
        dates = [b["d"] for b in bars]
        if entry_date in dates:
            return (len(dates) - 1) - dates.index(entry_date)
        # entry_date not a bar (weekend/holiday mark) -> count bars strictly after it
        return sum(1 for d in dates if d > entry_date)

    def _sell(self, sym: str, qty: int, reason: str, ref_price: float = None):
        """Market-sell `qty` (clamped to held), then RECORD the closed leg to the trades CSV.
        Returns the fill price used for the log (actual avg fill when live, else ref_price)."""
        pos = self.state["positions"].get(sym, {})
        setup = pos.get("setup", "breakout")
        held = pos.get("shares_left", qty)
        qty = max(0, min(int(qty), int(held)))           # LONG-ONLY clamp: never sell more than held
        if qty < 1:
            return None
        msg = f"SELL {qty} {sym} @ MKT ({reason})"
        fill = ref_price
        if self.dry:
            log("[DRY] " + msg, setup=setup)
        else:
            from ib_async import MarketOrder
            contract = self._stk(sym)
            trade = self.ib.placeOrder(contract, MarketOrder("SELL", qty))
            self.ib.sleep(1.0)
            avg = getattr(trade.orderStatus, "avgFillPrice", 0) or self._last_sell_fill(sym)
            if avg:
                fill = avg
            log(msg + (f" filled @ {fill:.2f}" if fill else ""), setup=setup)
        self._record_leg(sym, pos, qty, fill, reason)
        return fill

    def _last_sell_fill(self, sym: str):
        """Most recent SELL fill price for `sym` from IB (for stop-outs filled server-side)."""
        try:
            sells = [f for f in self.ib.fills()
                     if f.contract.symbol == sym and f.execution.side == "SLD"]
            if sells:
                ex = sells[-1].execution
                return ex.avgPrice or ex.price
        except Exception:
            pass
        return None

    def _trades_csv_for(self, setup: str) -> str:
        """Per-setup trades CSV path (base name + _<setup>), e.g. qm_trades_breakout.csv."""
        base, ext = os.path.splitext(self.trades_csv_base)
        return f"{base}_{setup}{ext or '.csv'}"

    def _sibling_csv(self, kind: str, setup: str = None) -> str:
        """Derive a sibling CSV from trades_csv_base, e.g. qm_trades.csv -> qm_entries_<setup>.csv
        or qm_positions.csv (live: qm_live_trades.csv -> qm_live_entries_* / qm_live_positions.csv)."""
        d = os.path.dirname(self.trades_csv_base)
        name = os.path.basename(self.trades_csv_base)                  # qm_trades.csv / qm_live_trades.csv
        prefix = name[:-len("trades.csv")] if name.endswith("trades.csv") else "qm_"
        fname = f"{prefix}{kind}_{setup}.csv" if setup else f"{prefix}{kind}.csv"
        return os.path.join(d, fname)

    def _record_entry(self, sym: str, pos: dict, fill_price: float):
        """Append an ENTRY row (with the entry's quality factors) to qm_entries_<setup>.csv when a
        buy-stop fills — so every trade, open or closed, is on disk with its entry context."""
        setup = pos.get("setup", "breakout")
        q = pos.get("q", {})
        entry = pos.get("entry_price") or fill_price
        rps = pos.get("rps") or 0
        shares = pos.get("shares", 0)
        cols = ["date", "time", "symbol", "setup", "entry_id", "shares", "trigger", "fill",
                "stop", "rps", "risk_$", "notional_$", "score", "perf3m", "rs", "adr",
                "base_range_pct", "voldry", "off_high"]
        row = {
            "date": now_et().strftime("%Y-%m-%d"), "time": now_et().strftime("%H:%M:%S"),
            "symbol": sym, "setup": setup, "entry_id": pos.get("id", sym), "shares": int(shares),
            "trigger": round(pos.get("trigger", entry), 4), "fill": round(fill_price, 4),
            "stop": round(pos.get("stop", 0), 4), "rps": round(rps, 4),
            "risk_$": round(rps * shares, 2), "notional_$": round(fill_price * shares, 2),
            "score": q.get("score", ""), "perf3m": q.get("perf3m", ""), "rs": q.get("rs", ""),
            "adr": q.get("adr", ""), "base_range_pct": q.get("base_range_pct", ""),
            "voldry": q.get("voldry", ""), "off_high": q.get("off_high", ""),
        }
        path = self._sibling_csv("entries", setup)
        try:
            new = not os.path.exists(path)
            with open(path, "a", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=cols)
                if new:
                    w.writeheader()
                w.writerow(row)
            log(f"ENTRY-CSV += {sym} {int(shares)}sh @ {fill_price:.2f} score={q.get('score','?')}",
                setup=setup)
        except OSError as e:
            log(f"entry-csv write failed for {sym}: {e}", setup=setup)

    def snapshot_positions(self):
        """Daily mark-to-market snapshot of EVERY open position -> qm_positions.csv (appends one row
        per position per call, with a date). Gives an equity/book time series + a direct diff vs the
        backtest's open book. Uses daily bars for last price + the trail MA."""
        st = self.state["positions"]
        if not st:
            return
        cols = ["date", "symbol", "setup", "entry_date", "days_held", "shares", "entry", "last",
                "stop", "trail_ma", "unreal_$", "R", "score", "perf3m", "rs", "adr"]
        snap_date = now_et().strftime("%Y-%m-%d")
        path = self._sibling_csv("positions")
        rows, tot = [], 0.0
        for sym, pos in st.items():
            bars = fetch(sym, self.cfg["data_source"], self.cfg["data_range"])
            if not bars:
                continue
            closes = [b["c"] for b in bars]
            last = closes[-1]
            ma = sma_series(closes, int(pos.get("trail_sma", self.cfg["trail_sma"])))[-1]
            entry = pos.get("fill_price") or pos.get("entry_price")
            sh = pos.get("shares_left", pos.get("shares", 0))
            rps = pos.get("rps")
            days = self._days_held(bars, pos.get("entry_date")) if pos.get("entry_date") else 0
            q = pos.get("q", {})
            unreal = (last - entry) * sh if entry else ""
            R = ((last - entry) / rps) if (entry and rps) else ""
            if isinstance(unreal, (int, float)):
                tot += unreal
            rows.append({
                "date": snap_date, "symbol": sym, "setup": pos.get("setup", ""),
                "entry_date": pos.get("entry_date") or "", "days_held": days, "shares": int(sh),
                "entry": round(entry, 4) if entry else "", "last": round(last, 2),
                "stop": round(pos.get("stop"), 2) if pos.get("stop") else "",
                "trail_ma": round(ma, 2) if ma is not None else "",
                "unreal_$": round(unreal, 2) if isinstance(unreal, (int, float)) else "",
                "R": round(R, 2) if isinstance(R, (int, float)) else "",
                "score": q.get("score", ""), "perf3m": q.get("perf3m", ""),
                "rs": q.get("rs", ""), "adr": q.get("adr", ""),
            })
        try:
            new = not os.path.exists(path)
            with open(path, "a", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=cols)
                if new:
                    w.writeheader()
                w.writerows(rows)
            log(f"POSITIONS-CSV += {len(rows)} position(s) for {snap_date}; "
                f"total unrealized ${tot:,.0f}")
        except OSError as e:
            log(f"positions-csv write failed: {e}")

    def _record_leg(self, sym: str, pos: dict, qty: int, exit_price, reason: str,
                    exit_date: str = None):
        """Append one closed-leg row to THIS setup's trades CSV (Backtest Journal format).
        Written after EVERY partial / trail / stop exit, so the CSV is always current."""
        setup = pos.get("setup", "breakout")
        entry = pos.get("entry_price")
        rps = pos.get("rps")
        exit_date = exit_date or now_et().strftime("%Y-%m-%d")
        row = {c: "" for c in TRADE_COLS}
        row.update({
            "symbol": sym, "strat": "qm_" + setup,
            "entry_id": pos.get("id", sym), "side": "Long", "qty": int(qty),
            "entry_time_et": pos.get("entry_date") or "", "exit_time_et": exit_date,
            "reason": reason,
        })
        if entry:
            row["entry_price"] = round(entry, 4)
        if exit_price:
            row["exit_price"] = round(exit_price, 4)
        if entry and rps and exit_price:                 # compute R + pnl when we have everything
            r_mult = (exit_price - entry) / rps
            row["R_points"] = round(rps, 4)
            row["R_result"] = f"{r_mult:+.2f}R"
            row["pnl"] = round((exit_price - entry) * qty, 2)
        csv_path = self._trades_csv_for(setup)
        try:
            new = not os.path.exists(csv_path)
            with open(csv_path, "a", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=TRADE_COLS)
                if new:
                    w.writeheader()
                w.writerow(row)
            log(f"TRADE-CSV += {sym} {reason} qty={qty} "
                f"{('pnl=$%.2f' % row['pnl']) if row['pnl'] != '' else '(no entry price)'}",
                setup=setup)
        except OSError as e:
            log(f"trade-csv write failed for {sym}: {e}", setup=setup)

    def _move_stop(self, sym: str, pos: dict, new_stop: float, note: str = ""):
        msg = f"MOVE STOP {sym} -> {new_stop:.2f}{(' ' + note) if note else ''}"
        if self.dry:
            log("[DRY] " + msg)
            pos["stop"] = new_stop
            return
        self._cancel_stop(sym, pos)
        from ib_async import StopOrder
        contract = self._stk(sym)
        left = pos.get("shares_left", 0)
        if left >= 1:
            o = StopOrder("SELL", int(left), round_cent(new_stop))
            o.orderId = self.ib.client.getReqId()
            o.tif = "GTC"
            o.transmit = True
            self.ib.placeOrder(contract, o)
            pos["stop_id"] = o.orderId
            pos["stop"] = new_stop
            self.ib.sleep(0.3)
        log(msg)

    def _cancel_stop(self, sym: str, pos: dict):
        sid = pos.get("stop_id")
        if not sid or self.dry:
            return
        for t in self.ib.openTrades():
            if t.order.orderId == sid:
                self.ib.cancelOrder(t.order)
                self.ib.sleep(0.2)
                return

    # ---- scheduling ----
    def run_loop(self):
        did_refresh_on = did_ep_on = did_entry_on = did_manage_on = None
        setups = self.cfg.get("setups") or []
        ep_on = "ep" in setups
        et_ep = self.cfg.get("ep_entry_time", "09:40")
        et_entry = self.cfg["entry_time"]
        et_manage = self.cfg["manage_time"]
        # Entry window: entries/EP only fire between these ET times, so the bot can run 24/7 and
        # starting it after hours (or mid-afternoon) won't place late/after-hours entry orders — it
        # just waits for the next window. Management + reconnect stay always-on. Default end 11:00.
        ew = self.cfg.get("entry_window") or [et_entry, "11:00"]
        ew_start, ew_end = ew[0], ew[1]
        status_every = max(60, int(self.cfg.get("status_every_min", 60)) * 60)   # hourly snapshot
        last_status = 0.0
        log(f"loop started; ep@{et_ep if ep_on else 'off'} entry@{et_entry} "
            f"entry_window=[{ew_start},{ew_end}] manage@{et_manage} "
            f"status_every={status_every//60}m poll={self.cfg['poll_seconds']}s")
        import asyncio
        import time as _t
        while True:
            try:
                # Reconnect if the Gateway restarted / a competing login bumped us. Never gives up
                # (swing bot); positions are protected by the resting server-side stops meanwhile.
                self.ensure_connected()

                n = now_et()
                today = n.strftime("%Y-%m-%d")
                hhmm = n.strftime("%H:%M")
                weekday = n.weekday() < 5
                in_entry_window = ew_start <= hhmm <= ew_end   # entries only inside the window

                # Record start-of-day equity once per day for the daily-loss circuit breaker.
                if self.cfg.get("daily_loss_limit_pct", 0) and self.state.get("sod_date") != today:
                    nlv = self.capital()
                    if nlv > 0:
                        self.state["sod_date"] = today
                        self.state["equity_sod"] = nlv
                        save_state(self.state)
                        log(f"start-of-day equity = ${nlv:,.0f} (circuit breaker reference)")

                # Hourly status snapshot: open orders + positions (fills/cancels log in real time).
                if _t.time() - last_status >= status_every:
                    self.log_status()
                    last_status = _t.time()
                # Once at the start of the window: cancel any leftover unfilled entry orders so the
                # day re-arms from a clean slate on the fresh ranking (works even if entry_tif=GTC).
                if weekday and in_entry_window and did_refresh_on != today:
                    self.reconcile()
                    self.cancel_stale_entries()
                    did_refresh_on = today
                # EP first — it must act right at the open (opening-range breakout on earnings)
                if weekday and ep_on and in_entry_window and did_ep_on != today:
                    self.reconcile()
                    self.run_ep_entries()
                    did_ep_on = today
                if weekday and in_entry_window and did_entry_on != today:
                    self.reconcile()
                    self.run_entries()
                    did_entry_on = today
                if weekday and hhmm >= et_manage and did_manage_on != today:
                    self.reconcile()
                    self.run_manage()
                    self.snapshot_positions()       # daily mark-to-market book snapshot CSV
                    did_manage_on = today
                self._safe_sleep(self.cfg["poll_seconds"])
            except KeyboardInterrupt:
                raise                            # let main() handle a clean Ctrl+C shutdown
            except (asyncio.CancelledError, Exception) as e:
                # A Gateway restart / socket drop surfaces HERE (ConnectionError "Socket disconnect",
                # or asyncio.CancelledError — a BaseException that `except Exception` misses) via any
                # ib.sleep/request. Log it, tear down the dead client, pause, and let the next
                # iteration's ensure_connected() do a FRESH reconnect + reconcile. This is what makes
                # the bot survive the Gateway's daily restart instead of dying.
                log(f"loop: {type(e).__name__}: {e} — tearing down client, reconnecting next tick")
                try:
                    self.ib.disconnect()
                except Exception:
                    pass
                self._safe_sleep(3)

    def run_once(self):
        self.reconcile()
        self.cancel_stale_entries()        # clean slate before placing fresh orders
        self.run_ep_entries()
        self.run_entries()
        self.run_manage()
        self.snapshot_positions()          # daily mark-to-market book snapshot CSV


# ─────────────────────────────── entry point ───────────────────────────────
def cmd_check(cfg):
    req = ["paper", "port", "risk_per_trade_pct", "max_positions", "trail_sma", "partial_days"]
    miss = [k for k in req if k not in cfg]
    print("config keys OK" if not miss else f"MISSING config keys: {miss}")
    print(f"paper={cfg['paper']} dry_run={cfg.get('dry_run')} port={cfg['port']} "
          f"risk={cfg['risk_per_trade_pct']*100:.2f}% max_pos={cfg['max_positions']} "
          f"trail_sma={cfg['trail_sma']} partial_days={cfg['partial_days']}")
    try:
        import ib_async  # noqa: F401
        print(f"ib_async import OK ({ib_async.__version__})")
    except Exception as e:
        print(f"ib_async import FAILED: {e}")
    print("universe.py + qm_long_backtest import OK")
    print("check complete (no network / no IB connection performed).")


def cmd_scan(cfg):
    cands = scan_setups(cfg)
    if "ep" in (cfg.get("setups") or []):
        cands = cands + scan_ep(cfg)                     # EP uses earnings + intraday, added separately
        cands.sort(key=lambda c: c["score"], reverse=True)
    print(f"\n{'#':>2} {'SYM':<6} {'SETUP':<14} {'PRICE':>8} {'TRIGGER':>8} {'STOP':>8} "
          f"{'RISK%':>6} {'MOVE%':>6} {'ADR%':>6} {'OFFHI%':>7} {'$VOLM':>7}")
    print("-" * 96)
    for i, c in enumerate(cands[:40], 1):
        print(f"{i:>2} {c['sym']:<6} {c.get('setup','breakout'):<14} {c['price']:>8.2f} "
              f"{c['trigger']:>8.2f} {c['stop']:>8.2f} {100*c['rps']/c['trigger']:>6.1f} "
              f"{c['perf3m']:>6.0f} {c['adr']:>6.1f} {c['off_high']:>7.1f} {c['dollar_vol_m']:>7.1f}")
    print(f"\n{len(cands)} setups found (setups={cfg.get('setups', ['breakout'])}). "
          f"BUY-STOP at the trigger, protective stop below. LONG only. "
          f"(MOVE% = 3M gain for breakout · crash-depth for parabolic_long · opening gap%% for ep.)")


def main():
    ap = argparse.ArgumentParser(description="Qullamaggie LONG-only IBKR bot")
    ap.add_argument("--config", default=DEFAULT_CONFIG)
    ap.add_argument("--check", action="store_true", help="validate config + imports (no network)")
    ap.add_argument("--scan-only", action="store_true", help="print today's setups (no IB)")
    ap.add_argument("--once", action="store_true", help="run one entry+manage cycle then exit")
    ap.add_argument("--i-understand-live", action="store_true",
                    help="required to connect to a LIVE (non-paper) account")
    a = ap.parse_args()
    cfg = load_config(a.config)
    # Optional per-config overrides so a live config keeps its state/logs separate from paper
    # (no auto-namespacing — just explicit paths when you want them).
    global STATE_FILE, LOG_DIR
    if cfg.get("state_file"):
        STATE_FILE = os.path.join(_APP_DIR, cfg["state_file"])
    if cfg.get("log_dir"):
        LOG_DIR = os.path.join(_APP_DIR, cfg["log_dir"])

    if a.check:
        return cmd_check(cfg)
    if a.scan_only:
        return cmd_scan(cfg)

    bot = QMBot(cfg, allow_live=a.i_understand_live)
    try:
        bot.connect()
        if a.once:
            bot.run_once()
        else:
            bot.run_loop()
    except KeyboardInterrupt:
        log("interrupted — shutting down")
    finally:
        bot.disconnect()


if __name__ == "__main__":
    main()
