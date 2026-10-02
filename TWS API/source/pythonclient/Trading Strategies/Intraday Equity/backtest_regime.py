"""Regime-segmented OFFLINE backtest of the Intraday-Equity strategies.

Reuses the EXACT entry/management logic from backtest.py (bt_orb / bt_pdh / bt_nr7 /
bt_vwap -> same VWAP-from-bars, volume/gap/RVOL gates, breakeven+trail, slippage+comm),
but instead of pulling from IBKR it loads the CSVs persisted by
    Historical Data/scripts/download_equity_intraday.py
and buckets every trade by the MARKET REGIME of the day it was taken.

Regime = per-session SPY classification (no look-ahead beyond the classified day's close):
    close > SMA50 & SMA50 rising & ADX>=20 & close>SMA20  -> UPTREND
    close < SMA50 & SMA50 falling & ADX>=20 & close<SMA20 -> DOWNTREND
    otherwise (incl. low-ADX / mixed)                     -> CHOPPY

Only strategies listed in equity.json "active_strategies" are run, so turning a strategy
off there also removes it here. Output: console table + a summary txt and per-bucket trade
CSVs under Historical Data/Intraday Equity/results/.

Run:  .venv/Scripts/python.exe backtest_regime.py
"""
from __future__ import annotations
import csv
import os
import sys
from collections import defaultdict
from datetime import datetime
from types import SimpleNamespace

import numpy as np

BASE = os.path.dirname(os.path.abspath(__file__))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

# Make backtest.sessions() return ALL completed sessions (not just the last N) before import.
os.environ.setdefault("BT_DAYS", "100000")
import backtest as BT  # noqa: E402  (reuses CFG, SR, RUN, bt_* handlers, summarize helpers)

HIST_ROOT = os.path.normpath(os.path.join(BASE, "..", "Historical Data"))
EQ_DATA = os.path.join(HIST_ROOT, "data", "equity")
RESULTS = os.path.join(HIST_ROOT, "Intraday Equity", "results")
UNIVERSE_CAP = BT.UNIVERSE_CAP
REGIMES = ("UPTREND", "DOWNTREND", "CHOPPY")


# ----------------------------------------------------------------- CSV loading
def _parse_dt(s: str) -> datetime:
    s = s.strip()
    return datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S") if len(s) > 10 \
        else datetime.strptime(s, "%Y-%m-%d")


def _load_csv(path):
    if not os.path.exists(path):
        return []
    out = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            try:
                out.append(SimpleNamespace(
                    date=_parse_dt(row["date"]),
                    open=float(row["open"]), high=float(row["high"]),
                    low=float(row["low"]), close=float(row["close"]),
                    volume=float(row["volume"] or 0)))
            except (ValueError, KeyError):
                continue
    out.sort(key=lambda b: b.date)
    return out


def _by_day(bars):
    d = defaultdict(list)
    for b in bars:
        d[b.date.date()].append(b)
    for k in d:
        d[k].sort(key=lambda b: b.date)
    return d


def load_symbol(sym):
    """Assemble the same {daily, m5, m1, pmvol} dict backtest.get_data() produces."""
    daily = _load_csv(os.path.join(EQ_DATA, f"{sym}_1day.csv"))
    m5 = _by_day(_load_csv(os.path.join(EQ_DATA, f"{sym}_5min.csv")))
    m1 = _by_day(_load_csv(os.path.join(EQ_DATA, f"{sym}_1min.csv")))
    pmvol = {}
    for b in _load_csv(os.path.join(EQ_DATA, f"{sym}_5min_pm.csv")):
        t = b.date
        if t.hour * 60 + t.minute < 9 * 60 + 30:          # pre-market portion only
            pmvol[t.date()] = pmvol.get(t.date(), 0.0) + b.volume
    if not daily and not m5 and not m1:
        return None
    return {"daily": daily, "m5": m5, "m1": m1, "pmvol": pmvol}


# ----------------------------------------------------------------- regime model
def _sma(x, n):
    x = np.asarray(x, float)
    out = np.full(len(x), np.nan)
    if len(x) >= n:
        c = np.cumsum(np.insert(x, 0, 0.0))
        out[n - 1:] = (c[n:] - c[:-n]) / n
    return out


def _wilder_adx(h, l, c, period=14):
    h, l, c = map(lambda a: np.asarray(a, float), (h, l, c))
    n = len(c)
    adx = np.full(n, np.nan)
    if n < 2 * period + 2:
        return adx
    up = h[1:] - h[:-1]
    dn = l[:-1] - l[1:]
    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = np.maximum.reduce([h[1:] - l[1:], np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])])

    def smooth(x):
        s = np.full(len(x), np.nan)
        if len(x) < period:
            return s
        s[period - 1] = x[:period].sum()
        for i in range(period, len(x)):
            s[i] = s[i - 1] - s[i - 1] / period + x[i]
        return s

    trs, pdms, mdms = smooth(tr), smooth(plus_dm), smooth(minus_dm)
    with np.errstate(invalid="ignore", divide="ignore"):
        pdi = 100 * pdms / trs
        mdi = 100 * mdms / trs
        dx = 100 * np.abs(pdi - mdi) / (pdi + mdi)
    adx_arr = np.full(len(dx), np.nan)
    valid = np.where(~np.isnan(dx))[0]
    if len(valid) and valid[0] + period <= len(dx):
        f = valid[0]
        adx_arr[f + period - 1] = np.nanmean(dx[f:f + period])
        for i in range(f + period, len(dx)):
            adx_arr[i] = (adx_arr[i - 1] * (period - 1) + dx[i]) / period
    adx[1:] = adx_arr                       # dx index i -> close index i+1
    return adx


def build_regime_map(adx_min=20.0, slope_lb=5):
    daily = _load_csv(os.path.join(EQ_DATA, "SPY_1day.csv"))
    if not daily:
        return {}, daily
    dates = [b.date.date() for b in daily]
    c = [b.close for b in daily]
    h = [b.high for b in daily]
    lo = [b.low for b in daily]
    sma20, sma50 = _sma(c, 20), _sma(c, 50)
    adx = _wilder_adx(h, lo, c)
    regime = {}
    for i in range(len(daily)):
        s20, s50, a = sma20[i], sma50[i], adx[i]
        if np.isnan(s50) or np.isnan(s20) or i < slope_lb or np.isnan(sma50[i - slope_lb]):
            regime[dates[i]] = "CHOPPY"
            continue
        slope = s50 - sma50[i - slope_lb]
        strong = (not np.isnan(a)) and a >= adx_min
        if strong and c[i] > s50 and slope > 0 and c[i] > s20:
            regime[dates[i]] = "UPTREND"
        elif strong and c[i] < s50 and slope < 0 and c[i] < s20:
            regime[dates[i]] = "DOWNTREND"
        else:
            regime[dates[i]] = "CHOPPY"
    return regime, daily


# ----------------------------------------------------------------- stats
def stats(trades):
    n = len(trades)
    if not n:
        return {"n": 0}
    wins = [t for t in trades if t["PnL"] > 0]
    gw = sum(t["PnL"] for t in wins)
    gl = abs(sum(t["PnL"] for t in trades if t["PnL"] < 0))
    exits = defaultdict(int)
    for t in trades:
        exits[t["Reason"]] += 1
    return {
        "n": n,
        "win_rate": 100.0 * len(wins) / n,
        "avg_R": sum(t["R_Multiple"] for t in trades) / n,     # expectancy in R
        "net_pnl": sum(t["PnL"] for t in trades),
        "pf": (gw / gl) if gl else float("inf"),
        "avg_win_R": (sum(t["R_Multiple"] for t in wins) / len(wins)) if wins else 0.0,
        "exits": dict(exits),
    }


def _fmt(s):
    if s["n"] == 0:
        return "no trades"
    pf = "inf" if s["pf"] == float("inf") else f"{s['pf']:.2f}"
    return (f"n={s['n']:>4}  win={s['win_rate']:>5.1f}%  avgR={s['avg_R']:>+5.2f}  "
            f"PF={pf:>5}  net=${s['net_pnl']:>10,.0f}  exits={s['exits']}")


MIN_STOP = BT.MIN_STOP


def bt_pdh_fill(sym, data, cfg, fill):
    """PDH breakout with an explicit entry-fill model. fill='trigger' reproduces the engine
    (fill at the PDH trigger AFTER the bar already closed above it -> optimistic); fill='close'
    fills at the breakout bar's close (what a close-confirmed signal can realistically get)."""
    wins = BT.parse_windows(cfg["windows"]); trades = []
    vol_mult = float(cfg.get("vol_mult", 1.5)); buf = float(cfg.get("breakout_buffer_pct", 0.001))
    off = float(cfg.get("entry_offset_pct", 0.0005)); stop_pct = float(cfg.get("stop_pct", 0.0005))
    t1 = float(cfg.get("target1_R", 2.0))
    be = float(cfg.get("breakeven_mult", 1.0)); ts = float(cfg.get("trail_start_mult", 1.5)); tl = float(cfg.get("trail_lock_mult", 0.5))
    daily = data["daily"]
    for d in BT.sessions(data["m5"]):
        bars = data["m5"][d]
        if len(bars) < 4: continue
        db = [b for b in daily if (b.date.date() if hasattr(b.date, "date") else b.date) < d]
        if not db: continue
        pdh = db[-1].high
        for i in range(1, len(bars) - 1):
            b = bars[i]
            if not BT.in_windows(b, wins):
                if BT._min(b.date) > max(w[1] for w in wins): break
                continue
            trig = pdh * (1 + buf)
            if b.close <= trig: continue
            recent = [x.volume for x in bars[max(0, i-6):i] if x.volume]
            if recent and b.volume < vol_mult * (sum(recent)/len(recent)): continue
            vw = BT.vwap_upto(bars, i)
            if vw is not None and b.close <= vw: continue
            entry = (trig + off * pdh) if fill == "trigger" else b.close
            stop = min(pdh * (1 - stop_pct), entry * (1 - MIN_STOP)); r = entry - stop
            if r <= 0: continue
            target = entry + t1 * r
            ex, why, _ = BT.simulate(bars, i, entry, stop, target, r, be, ts, tl)
            t = BT.record(sym, d, entry, stop, target, ex, why, r)
            if t: trades.append(t)
            break
    return trades


def bt_orb_fill(sym, data, cfg, fill):
    """ORB Stocks-in-Play with an entry-fill model. fill='trigger' reproduces the engine
    (fill at ORB_high + ATR buffer); fill='close' fills at the 1-min breakout bar close."""
    wins = BT.parse_windows(cfg["windows"]); trades = []
    gap_min = float(cfg.get("universe", {}).get("min_gap_pct", 0.02))
    hmin = max(float(cfg.get("orb_height_min_pct", 0.003)), 0.008)
    hmax = float(cfg.get("orb_height_max_pct", 0.05))
    vol_mult = float(cfg.get("signal", {}).get("vol_mult", 1.5))
    mid_pct = float(cfg.get("stop", {}).get("min_or_height_pct", 0.01))
    tmult = float(cfg.get("target", {}).get("mult", 2.0))
    buf = float(cfg.get("atr_entry_buffer_mult", 0.05))
    rvol_min = float(cfg.get("universe", {}).get("min_premarket_rvol", 1.5))
    pmvol = data.get("pmvol", {})
    be = float(cfg.get("breakeven_mult", 1.0)); ts = float(cfg.get("trail_start_mult", 1.5)); tl = float(cfg.get("trail_lock_mult", 0.5))
    daily = data["daily"]
    for d in BT.sessions(data["m1"]):
        bars = data["m1"][d]
        if len(bars) < 12: continue
        db_before = [b for b in daily if (b.date.date() if hasattr(b.date, "date") else b.date) < d]
        if not db_before or not db_before[-1].close: continue
        prior_close = db_before[-1].close
        gap = (bars[0].open - prior_close) / prior_close if prior_close else 0.0
        if gap < gap_min: continue
        rv = BT.premarket_rvol(pmvol, d)
        if rvol_min and rv is not None and rv < rvol_min: continue
        oh = max(b.high for b in bars[:5]); ol = min(b.low for b in bars[:5]); height = oh - ol
        if not oh or not (hmin <= height / oh <= hmax): continue
        atr_d = BT.atr_daily(db_before)
        for i in range(5, len(bars) - 1):
            b = bars[i]
            if not BT.in_windows(b, wins):
                if BT._min(b.date) > max(w[1] for w in wins): break
                continue
            if b.close <= oh: continue
            recent = [x.volume for x in bars[max(0, i-20):i] if x.volume]
            if recent and b.volume < vol_mult * (sum(recent)/len(recent)): continue
            vw = BT.vwap_upto(bars, i)
            if vw is not None and b.close <= vw: continue
            entry = (oh + buf * atr_d) if fill == "trigger" else b.close
            stop = (oh + ol) / 2 if (height / oh < mid_pct) else ol
            r = entry - stop
            if r <= 0: continue
            target = entry + tmult * height
            ex, why, _ = BT.simulate(bars, i, entry, stop, target, r, be, ts, tl)
            t = BT.record(sym, d, entry, stop, target, ex, why, r)
            if t: trades.append(t)
            break
    return trades


REALISTIC = {"pdh_breakout": bt_pdh_fill, "orb_stocks_in_play": bt_orb_fill}


# --- new intraday strategies (#1/#2/#3): 5-min replays, realistic close-fill by construction,
#     mirroring strategies/trend_pullback.py / range_breakout_retest.py / sr_bounce.py ---
from ta_utils import ema as _ema, rsi as _rsi   # noqa: E402


def _mgmt(cfg):
    return (float(cfg.get("breakeven_mult", 1.0)),
            float(cfg.get("trail_start_mult", 1.5)),
            float(cfg.get("trail_lock_mult", 0.5)))


def bt_trend_pullback(sym, data, cfg):
    wins = BT.parse_windows(cfg["windows"]); trades = []
    be, ts, tl = _mgmt(cfg)
    ef = int(cfg.get("ema_fast", 9)); es = int(cfg.get("ema_slow", 20))
    slope_lb = int(cfg.get("ema_slope_lookback", 3)); lb = int(cfg.get("pullback_lookback", 6))
    band = float(cfg.get("ema_touch_band", 0.002)); vmult = float(cfg.get("vol_mult", 1.2))
    sma_n = int(cfg.get("daily_trend_sma", 20)); satr = float(cfg.get("stop_atr_mult", 0.2))
    tmult = float(cfg.get("target_r_mult", 2.0)); daily = data["daily"]
    for d in BT.sessions(data["m5"]):
        bars = data["m5"][d]
        if len(bars) < es + lb + 3:
            continue
        db = [b for b in daily if (b.date.date() if hasattr(b.date, "date") else b.date) < d]
        if len(db) < sma_n + 1:
            continue
        dc = [b.close for b in db]
        sma_now = sum(dc[-sma_n:]) / sma_n; sma_prev = sum(dc[-sma_n - 1:-1]) / sma_n
        if db[-1].close <= sma_now or sma_now <= sma_prev:   # daily uptrend filter
            continue
        closes = [b.close for b in bars]
        fast = _ema(closes, ef); slow = _ema(closes, es)
        for i in range(es + lb, len(bars) - 1):
            b = bars[i]
            if not BT.in_windows(b, wins):
                if BT._min(b.date) > max(w[1] for w in wins): break
                continue
            if fast[i] is None or slow[i] is None or slow[i - slope_lb] is None:
                continue
            if not (fast[i] > slow[i] and slow[i] > slow[i - slope_lb]):
                continue
            vw = BT.vwap_upto(bars, i)
            if vw is not None and b.close <= vw:
                continue
            seg = range(i - lb, i)
            if not any(slow[j] is not None and bars[j].low <= slow[j] * (1 + band) for j in seg):
                continue
            pull_low = min(bars[j].low for j in seg); pull_high = max(bars[j].high for j in seg)
            if not (b.close > b.open and b.close > pull_high and b.close > fast[i]):
                continue
            recent = [x.volume for x in bars[i - 6:i] if x.volume]
            if recent and b.volume < vmult * (sum(recent) / len(recent)):
                continue
            a5 = BT.atr_intraday(bars, i)
            entry = b.close; stop = pull_low - satr * a5; r = entry - stop
            if r <= 0: continue
            target = entry + tmult * r
            ex, why, _ = BT.simulate(bars, i, entry, stop, target, r, be, ts, tl)
            t = BT.record(sym, d, entry, stop, target, ex, why, r)
            if t: trades.append(t)
            break
    return trades


def bt_range_retest(sym, data, cfg):
    wins = BT.parse_windows(cfg["windows"]); trades = []
    be, ts, tl = _mgmt(cfg)
    rlb = int(cfg.get("range_lookback", 6)); rw = int(cfg.get("retest_window", 4))
    rmax = float(cfg.get("range_max_pct", 0.03)); rmin = float(cfg.get("range_min_pct", 0.004))
    band = float(cfg.get("retest_band", 0.002)); sfrac = float(cfg.get("stop_inside_frac", 0.5))
    vmult = float(cfg.get("vol_mult", 1.2)); tmult = float(cfg.get("target_mult", 2.0))
    for d in BT.sessions(data["m5"]):
        bars = data["m5"][d]
        if len(bars) < rlb + rw + 2:
            continue
        for i in range(rlb + rw, len(bars) - 1):
            b = bars[i]
            if not BT.in_windows(b, wins):
                if BT._min(b.date) > max(w[1] for w in wins): break
                continue
            box = bars[i - rw - rlb:i - rw]
            if len(box) < rlb: continue
            rh = max(x.high for x in box); rl = min(x.low for x in box); height = rh - rl
            if rh <= 0 or height <= 0: continue
            if not (rmin <= height / rh <= rmax): continue
            if not any(x.close > rh for x in bars[i - rw:i]): continue
            if not (b.low <= rh * (1 + band) and b.low >= rl and b.close > rh and b.close > b.open):
                continue
            recent = [x.volume for x in bars[i - 6:i] if x.volume]
            if recent and b.volume < vmult * (sum(recent) / len(recent)): continue
            vw = BT.vwap_upto(bars, i)
            if vw is not None and b.close <= vw: continue
            entry = b.close; stop = rh - sfrac * height; r = entry - stop
            if r <= 0: continue
            target = entry + tmult * height
            ex, why, _ = BT.simulate(bars, i, entry, stop, target, r, be, ts, tl)
            t = BT.record(sym, d, entry, stop, target, ex, why, r)
            if t: trades.append(t)
            break
    return trades


def bt_sr_bounce(sym, data, cfg):
    wins = BT.parse_windows(cfg["windows"]); trades = []
    be, ts, tl = _mgmt(cfg)
    rp = int(cfg.get("rsi_period", 14)); os_lvl = float(cfg.get("rsi_oversold", 35.0))
    band = float(cfg.get("touch_band", 0.003)); sbuf = float(cfg.get("stop_buffer_pct", 0.002))
    tmult = float(cfg.get("target_r_mult", 1.75)); daily = data["daily"]
    for d in BT.sessions(data["m5"]):
        bars = data["m5"][d]
        if len(bars) < rp + 3:
            continue
        db = [b for b in daily if (b.date.date() if hasattr(b.date, "date") else b.date) < d]
        if not db: continue
        level = db[-1].low                       # prior-day low = tested support
        closes = [b.close for b in bars]; rv = _rsi(closes, rp)
        for i in range(rp + 1, len(bars) - 1):
            b = bars[i]
            if not BT.in_windows(b, wins):
                if BT._min(b.date) > max(w[1] for w in wins): break
                continue
            if min(b.low, bars[i - 1].low) > level * (1 + band): continue
            if rv[i] is None or rv[i] > os_lvl: continue
            if not (b.close > b.open and b.close > level): continue
            entry = b.close; stop = min(b.low, level) * (1 - sbuf); r = entry - stop
            if r <= 0: continue
            target = entry + tmult * r
            ex, why, _ = BT.simulate(bars, i, entry, stop, target, r, be, ts, tl)
            t = BT.record(sym, d, entry, stop, target, ex, why, r)
            if t: trades.append(t)
            break
    return trades


NEW = {"trend_pullback": bt_trend_pullback, "range_breakout_retest": bt_range_retest,
       "sr_bounce": bt_sr_bounce}


def _bucket(trades, regime):
    buckets = {r: [] for r in REGIMES}
    for t in trades:
        d = datetime.strptime(t["Date"], "%Y-%m-%d").date()
        r = regime.get(d)
        if r in buckets:
            buckets[r].append(t)
    return buckets


def main():
    os.makedirs(RESULTS, exist_ok=True)
    regime, spy_daily = build_regime_map()
    if not regime:
        print(f"No SPY daily data at {EQ_DATA}\\SPY_1day.csv -- run the downloader first.")
        return
    counts = defaultdict(int)
    for r in regime.values():
        counts[r] += 1
    span = f"{spy_daily[0].date.date()} .. {spy_daily[-1].date.date()}"
    print(f"SPY regime days ({span}): "
          + "  ".join(f"{k}={counts[k]}" for k in REGIMES))
    print(f"slippage {BT.SLIP*10000:.0f}bps/side + ${BT.COMM_PS}/sh commission | "
          f"risk {BT.RISK_PCT*100:.0f}% of ${BT.CAP:,.0f}\n")

    lines = [f"REGIME-SEGMENTED BACKTEST  (SPY per-session classification)",
             f"SPY window: {span}",
             f"regime days: " + "  ".join(f"{k}={counts[k]}" for k in REGIMES),
             f"costs: {BT.SLIP*10000:.0f}bps/side slippage + ${BT.COMM_PS}/sh commission",
             ""]

    note = ("NOTE: PDH/ORB use a REALISTIC entry fill (breakout-bar close). The engine's "
            "'trigger' fill (limit at the breakout level AFTER the bar closed above it) is "
            "optimistic and shown only as a labeled contrast.")
    print(note + "\n")
    lines += [note, ""]

    active = BT.CFG.get("active_strategies", [])
    for name in active:
        block = BT.CFG["strategies"].get(name, {})
        stype = block.get("strategy_type")
        run = BT.RUN.get(stype) or NEW.get(stype)
        if not run:
            continue
        realistic = REALISTIC.get(stype)
        is_new = stype in NEW
        universe = block.get("universe_symbols", [])[:UNIVERSE_CAP]
        datas, missing = {}, []
        for sym in universe:
            data = load_symbol(sym)
            if not data or not data.get("m5"):
                missing.append(sym)
                continue
            datas[sym] = data

        def collect(fn, fill=None):
            out = []
            for sym, data in datas.items():
                try:
                    out += (fn(sym, data, block, fill) if fill else fn(sym, data, block))
                except Exception as e:
                    print(f"  {name}/{sym}: error {e}")
            return out

        primary = collect(realistic, "close") if realistic else collect(run)
        label = "REALISTIC (close-fill)" if (realistic or is_new) else "engine"
        buckets = _bucket(primary, regime)

        hdr = f"===== {name}  ({stype})  [{label}] ====="
        print(hdr); lines.append(hdr)
        if missing:
            print(f"  (no data for: {missing})"); lines.append(f"  (no data for: {missing})")
        for r in REGIMES:
            row = f"  {r:<10} " + _fmt(stats(buckets[r]))
            print(row); lines.append(row)
        allrow = "  " + f"{'ALL':<10} " + _fmt(stats(primary))
        print(allrow); lines.append(allrow)

        if realistic:   # optimistic contrast (one line)
            opt = collect(realistic, "trigger")
            contrast = "  " + f"{'ALL(opt)':<10} " + _fmt(stats(opt))
            print(contrast); lines.append(contrast)
        print(); lines.append("")

        # persist per-bucket trades (the primary/realistic set)
        safe = "".join(ch if ch.isalnum() else "_" for ch in name)
        for r in REGIMES:
            if not buckets[r]:
                continue
            p = os.path.join(RESULTS, f"{safe}__{r}.csv")
            with open(p, "w", newline="") as f:
                cols = ["Date", "Ticker", "Shares", "Entry", "Stop", "Target",
                        "Exit", "PnL", "R_Multiple", "Result", "Reason"]
                w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
                w.writeheader()
                w.writerows(sorted(buckets[r], key=lambda t: t["Date"]))

    summary_path = os.path.join(RESULTS, "regime_backtest_summary.txt")
    with open(summary_path, "w") as f:
        f.write("\n".join(lines))
    print(f"summary -> {summary_path}")
    print(f"per-bucket trade CSVs -> {RESULTS}")


if __name__ == "__main__":
    main()
