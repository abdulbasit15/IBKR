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
from qm_long_backtest import fetch, sma_series, adr_pct_at, DEFAULT_UNIVERSE  # noqa: E402
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
    print(line, flush=True)
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
    stop = round_cent(base_lo)
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
    stop = round_cent(min(lows[ll_idx:]))                      # protective stop = crash low
    rps = trigger - stop
    if rps <= 0 or (rps / trigger) > p.max_risk_frac:
        return None
    adr = adr_pct_at(bars, i, 20)
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


ANALYZERS = {"breakout": analyze_breakout, "parabolic_long": analyze_parabolic_long}


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
        # quality-ranking weights (breakout); cfg override merges over the defaults
        quality_weights={**QUALITY_WEIGHTS, **(cfg.get("quality_weights") or {})},
    )
    # Relative strength benchmark: SPY's 3-month return, so breakout RS = stock 3m − SPY 3m.
    try:
        spy = fetch("SPY", cfg["data_source"], cfg["data_range"])
        p.spy_perf3m = ((spy[-1]["c"] / spy[-1 - 63]["c"] - 1.0) * 100.0) if spy and len(spy) > 63 else 0.0
        log(f"RS benchmark: SPY 3-month = {p.spy_perf3m:+.1f}%")
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
        stop = round_cent(or_low)
        rps = trigger - stop
        if rps <= 0 or (rps / trigger) > p.max_risk_frac:
            continue
        last = intr.get("last") or price
        if last > trigger * (1.0 + p.max_risk_frac):        # already ran too far past the ORH
            continue
        adr = adr_pct_at(daily, len(daily) - 1, 20) or 0.0
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
        # errorEvent carries IB 1100/1101/1102 connectivity notices even while the local API
        # socket stays up (a competing login bumps the Gateway's UPSTREAM link, not our socket).
        # disconnectedEvent fires on a real socket drop (e.g. the Gateway's daily restart).
        for hook, fn in (("errorEvent", self._on_error), ("disconnectedEvent", self._on_disconnected)):
            try:
                getattr(self.ib, hook).__iadd__(fn)
            except Exception:
                pass

    def _on_error(self, *args):
        code = args[1] if len(args) > 1 else None
        if code == 1100:                         # connectivity between IB and TWS/Gateway lost
            self._conn_ok = False
            log("IB error 1100: connectivity to IB LOST — data/orders will fail until restored")
        elif code in (1101, 1102):               # restored (1101 = with data loss, 1102 = maintained)
            self._conn_ok = True
            log(f"IB error {code}: connectivity RESTORED — resuming")

    def _on_disconnected(self):
        log("API socket disconnected — will reconnect on next tick")

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
        if slots <= 0:
            log(f"{setup}: strategy full ({used}/{self.cfg['max_positions']} held/pending) — skipping",
                setup=setup)
            return
        cap = self.capital()
        if cap <= 0:
            log(f"{setup}: capital is 0 (no NetLiquidation / override) — skipping", setup=setup)
            return
        fresh = [c for c in cands if c["sym"] not in held_syms]
        log(f"{setup}: {len(fresh)} new candidate(s); {slots} slot(s) free "
            f"({used}/{self.cfg['max_positions']} used); capital=${cap:,.0f}", setup=setup)
        placed = 0
        for c in fresh:
            if placed >= slots:
                break
            risk_dollars = cap * self.cfg["risk_per_trade_pct"]
            qty = math.floor(risk_dollars / c["rps"])
            cap_qty = math.floor((cap * self.cfg["max_position_pct"]) / c["trigger"])
            qty = max(0, min(qty, cap_qty))
            if qty < 1:
                continue
            self.place_entry(c, qty)
            placed += 1
        if placed == 0:
            log(f"{setup}: no entries placed this cycle", setup=setup)

    def run_entries(self):
        """Daily scan for the enabled daily setups (breakout / parabolic_long). Each is placed
        SEPARATELY so it gets its own independent cap of max_positions."""
        setups = [s for s in (self.cfg.get("setups") or []) if s in ANALYZERS]
        if not setups:
            return
        cands = scan_setups(self.cfg)                 # ranked, best-per-symbol, all daily setups
        for setup in setups:                          # place each strategy against its own cap
            self._place_candidates(cands, setup)

    def run_ep_entries(self):
        """Episodic Pivot open-time scan (only if 'ep' is in `setups`). Own cap of max_positions."""
        if "ep" not in (self.cfg.get("setups") or []):
            return
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
            "trail_sma": self.cfg["trail_sma"], "adopted": False,
        }
        save_state(self.state)
        log("ARMED " + msg, setup=setup)

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
            trail = sma_series(closes, pos.get("trail_sma", self.cfg["trail_sma"]))[-1]

            # 1) PARTIAL + move to break-even
            if (not pos.get("partial_done")) and days_held >= self.cfg["partial_days"]:
                half = int(held * self.cfg["partial_fraction"])
                if half >= 1:
                    self._sell(sym, half, "PARTIAL", ref_price=price)
                    pos["partial_done"] = True
                    held -= half
                    pos["shares_left"] = held           # so the BE stop resizes to the remainder
                    if pos.get("entry_price"):
                        self._move_stop(sym, pos, round_cent(pos["entry_price"]))
                    save_state(self.state)

            # 2) TRAIL: first close below the trail SMA exits the remainder
            if trail is not None and price < trail and held > 0:
                self._sell(sym, held, f"TRAIL<SMA{pos.get('trail_sma')}", ref_price=price)
                self._cancel_stop(sym, pos)
                del st[sym]
                save_state(self.state)
                continue

            log(f"HOLD {sym}: {held}sh held={days_held}d price={price:.2f} "
                f"trailSMA={trail:.2f} partial={'Y' if pos.get('partial_done') else 'N'}", setup=setup)
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

    def _move_stop(self, sym: str, pos: dict, new_stop: float):
        msg = f"MOVE STOP {sym} -> {new_stop:.2f} (break-even)"
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
        did_ep_on = did_entry_on = did_manage_on = None
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
        log(f"loop started; ep@{et_ep if ep_on else 'off'} entry@{et_entry} "
            f"entry_window=[{ew_start},{ew_end}] manage@{et_manage} poll={self.cfg['poll_seconds']}s")
        import asyncio
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
        self.run_ep_entries()
        self.run_entries()
        self.run_manage()


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
