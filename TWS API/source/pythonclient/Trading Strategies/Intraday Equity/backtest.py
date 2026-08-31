"""FAITHFUL backtest of the live engine (ORB / NR7 / PDH) on IBKR historical bars.

Mirrors the live bots (equity_base + strategies), driven by the SAME equity.json:
  * trade WINDOWS enforced for entries (ORB/NR7 09:35-11:00, PDH 09:35-11:30 + 14:00-15:30)
  * session VWAP computed FROM BARS (the live fix), gap/RVOL/vol-confirm gates
  * stop floored to min_stop_pct; target = entry + mult*R (ORB/PDH) or 2.2R (NR7); min_rr check
  * BREAKEVEN + TRAILING-STOP management (breakeven_mult / trail_start_mult / trail_lock_mult)
  * EOD flatten at eod_flatten_time; one trade per symbol per day
  * SLIPPAGE (bps/side) + COMMISSION ($/share) applied
Sizing: 1% risk-at-stop on strategy_capital (for readable $); R-multiples are sizing-free.
ORB triggers on 1-min bars; NR7/PDH on 5-min bars. Read-only (no orders).

Run: python backtest.py        (env: BT_DAYS, BT_SLIP_BPS, BT_COMMISSION_PS)
"""
from __future__ import annotations
import asyncio, json, math, os, sys
from collections import defaultdict

BASE = os.path.dirname(os.path.abspath(__file__))
if BASE not in sys.path:
    sys.path.insert(0, BASE)
from ib_async import IB, Stock                       # noqa: E402
from reporting import TradeReporter                  # noqa: E402

CFG = json.load(open(os.path.join(BASE, "equity.json")))
SR = CFG.get("shared_risk", {})
N_DAYS = int(os.environ.get("BT_DAYS", 12))
UNIVERSE_CAP = 10
SLIP = float(os.environ.get("BT_SLIP_BPS", 5)) / 10000.0    # 5 bps/side default
COMM_PS = float(os.environ.get("BT_COMMISSION_PS", 0.005))  # $/share/side
MIN_STOP = float(SR.get("min_stop_pct", 0.005))
MIN_RR = float(SR.get("min_rr", 1.5))
CAP = 100000.0
RISK_PCT = float(SR.get("risk_per_trade_pct", 0.01))
PORTS = [4002, 7497, 4001]


def connect():
    loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop)
    ib = IB()
    cid = int(os.environ.get("BT_CLIENT_ID", 93))   # override if 93 is already in use
    for p in PORTS:
        try:
            ib.connect("127.0.0.1", p, clientId=cid, readonly=True)
            ib.reqMarketDataType(3)
            ib.sleep(6)   # let the HMDS data farm wake after (re)login before first hist req
            print(f"connected on port {p}")
            return ib
        except Exception as e:
            print(f"  port {p} failed: {e}")
    return None


import calendar_util as cal                      # noqa: E402
TODAY = cal.now_et().date()
def sessions(day_map):
    """The last N_DAYS COMPLETED trading sessions in a {date: bars} map (today's still-forming
    session is excluded so partial intraday data can't skew the backtest)."""
    return [d for d in sorted(day_map) if d < TODAY][-N_DAYS:]


_cache = {}
def get_data(ib, sym, need_m1=True):
    # only ORB needs 1-min bars; skipping the heavy 30 D 1-min pull for NR7/PDH keeps the
    # request count under IBKR's ~60/10min historical pacing cap.
    if sym in _cache and (_cache[sym] is None or not need_m1 or _cache[sym].get("m1")):
        return _cache[sym]
    c = Stock(sym, "SMART", "USD")
    def _hist(dur, bar, retries=1, use_rth=True):
        # isolate each request: a 1-min pacing failure must NOT null out daily/5-min
        for _ in range(retries + 1):
            try:
                b = ib.reqHistoricalData(c, "", dur, bar, "TRADES", use_rth, 1); ib.sleep(0.3)
                if b:
                    return b
            except Exception as e:
                print(f"  {sym} {dur}/{bar}{'/pm' if not use_rth else ''}: {e}"); ib.sleep(0.5)
        return []
    try:
        ib.qualifyContracts(c)
    except Exception as e:
        print(f"  {sym}: qualify error {e}"); _cache[sym] = None; return None
    # generous fixed durations (cover a full month + the daily lookback NR7's SMA20 needs on
    # the earliest backtest session); N_DAYS just controls the final slice of sessions.
    daily = _hist("3 M", "1 day", retries=1)
    m5 = _hist("2 M", "5 mins", retries=1)
    m1 = _hist("30 D", "1 min", retries=1) if need_m1 else []
    # pre-market volume by day (useRTH=False) -> feeds the ORB pre-market RVOL filter.
    # Only for ORB symbols (need_m1) to stay under IBKR's request-pacing cap.
    pmvol = {}
    if need_m1:
        for b in (_hist("30 D", "5 mins", retries=1, use_rth=False) or []):
            t = getattr(b, "date", None)
            if t is None or not hasattr(t, "hour"):
                continue
            if t.hour * 60 + t.minute < 9 * 60 + 30:      # pre-market portion only (< 09:30 ET)
                dkey = t.date() if hasattr(t, "date") else t
                pmvol[dkey] = pmvol.get(dkey, 0.0) + float(b.volume or 0)
    def by_day(bars):
        d = defaultdict(list)
        for b in (bars or []):
            d[b.date.date() if hasattr(b.date, "date") else b.date].append(b)
        for k in d: d[k].sort(key=lambda b: b.date)
        return d
    _cache[sym] = {"daily": daily or [], "m5": by_day(m5), "m1": by_day(m1), "pmvol": pmvol}
    return _cache[sym]


def premarket_rvol(pmvol, day, lookback=20):
    """Pre-market RVOL = today's pre-market volume / mean of the prior `lookback` sessions'
    pre-market volume. None when there's no baseline (mirrors the live rvol() 'missing history
    -> keep' behaviour). No look-ahead: only prior sessions form the baseline."""
    if not pmvol or day not in pmvol:
        return None
    prior = [pmvol[d] for d in sorted(pmvol) if d < day and pmvol[d] > 0][-lookback:]
    if not prior:
        return None
    base = sum(prior) / len(prior)
    return (pmvol[day] / base) if base > 0 else None


def scanner_symbols(ib, block, cap):
    """Build the ORB universe from the IBKR scanner (mirrors the live scanner_universe):
    intersect the configured scan_codes. NOTE: reqScannerData only returns TODAY's snapshot,
    so a historical backtest of these names carries selection bias vs a true point-in-time
    daily scan -- documented limitation. Falls back to universe_symbols on empty/error."""
    from ib_async import ScannerSubscription
    sc = block.get("scanner", {}); fixed = block.get("universe_symbols", [])
    if not sc.get("use_scanner"):
        return fixed[:cap]
    sets = []
    for code in sc.get("scan_codes", []):
        try:
            sub = ScannerSubscription(instrument=sc.get("instrument", "STK"),
                    locationCode=sc.get("location_code", "STK.US.MAJOR"),
                    scanCode=code, numberOfRows=min(int(sc.get("scanner_rows", 50)), 50))
            if sc.get("above_price") is not None: sub.abovePrice = float(sc["above_price"])
            if sc.get("below_price") is not None: sub.belowPrice = float(sc["below_price"])
            if sc.get("stock_type_filter"):
                try: sub.stockTypeFilter = sc["stock_type_filter"]
                except Exception: pass
            out = ib.reqScannerData(sub, [], []) or []; ib.sleep(0.5)
            syms = [r.contractDetails.contract.symbol for r in out
                    if getattr(getattr(r, "contractDetails", None), "contract", None)]
            if syms: sets.append(syms)
            print(f"  scan {code}: {len(syms)} hits")
        except Exception as e:
            print(f"  scan {code} error: {e}")
    if not sets:
        print("  scanner empty -> universe_symbols"); return fixed[:cap]
    if sc.get("intersect") and len(sets) > 1:
        common = set(sets[0])
        for s in sets[1:]: common &= set(s)
        syms = [x for x in sets[0] if x in common]
    else:
        seen, syms = set(), []
        for s in sets:
            for x in s:
                if x not in seen: seen.add(x); syms.append(x)
    if not syms:
        print("  scanner intersect empty -> universe_symbols"); return fixed[:cap]
    print(f"  scanner universe ({len(syms)} -> cap {cap}): {syms[:cap]}")
    return syms[:cap]


def _min(t): return t.hour * 60 + t.minute
def parse_windows(ws): return [(_min_str(a), _min_str(b)) for a, b in ws]
def _min_str(s): h, m = map(int, s.split(":")); return h * 60 + m
def in_windows(bar, wins): return any(a <= _min(bar.date) <= b for a, b in wins)
EOD_MIN = _min_str(SR.get("eod_flatten_time", "15:55"))


def vwap_upto(bars, i):
    pv = vv = 0.0
    for k in range(i + 1):
        b = bars[k]; vol = b.volume or 0
        pv += ((b.high + b.low + b.close) / 3.0) * vol; vv += vol
    return (pv / vv) if vv > 0 else None


def atr_daily(daily_before, period=14):
    if len(daily_before) < period + 1: return 0.0
    trs = []
    for i in range(1, len(daily_before)):
        h, l, pc = daily_before[i].high, daily_before[i].low, daily_before[i-1].close
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    w = trs[-period:]; return sum(w) / len(w) if w else 0.0


def atr_intraday(bars, i, period=14):
    seg = bars[max(0, i - period):i]
    if len(seg) < 2: return 0.0
    trs = [seg[k].high - seg[k].low for k in range(len(seg))]
    return sum(trs) / len(trs)


def simulate(day_bars, i_entry, entry, stop, target, r_unit, be_mult, trail_start, trail_lock):
    """Bar-by-bar management with breakeven + trailing stop + EOD flatten. Conservative:
    stop checked before target within a bar; trail updates for the NEXT bar."""
    hw = entry
    for j in range(i_entry + 1, len(day_bars)):
        b = day_bars[j]
        if _min(b.date) >= EOD_MIN:
            return b.close, "EOD", j
        if b.low <= stop:  return stop, "STOP", j
        if b.high >= target: return target, "TARGET", j
        hw = max(hw, b.high)
        if be_mult and hw >= entry + be_mult * r_unit and stop < entry:
            stop = entry
        if trail_start and hw >= entry + trail_start * r_unit:
            stop = max(stop, hw - trail_lock * r_unit)
    return day_bars[-1].close, "EOD", len(day_bars) - 1


def record(sym, d, entry, stop, target, exit_px, reason, r_unit):
    """Apply slippage+commission, size at 1% risk, return a trade dict (or None)."""
    e = entry * (1 + SLIP)                                  # buy slippage
    x = (target if reason == "TARGET" else exit_px * (1 - SLIP))  # target=limit; stop/EOD slip
    rps = e - stop
    if rps <= 0: return None
    shares = math.floor(CAP * RISK_PCT / rps)
    if shares <= 0: return None
    pnl = (x - e) * shares - COMM_PS * shares * 2
    r = (x - e) / rps
    return {"Date": str(d), "Time": "", "Ticker": sym, "Shares": shares,
            "Entry": round(e, 2), "Stop": round(stop, 2), "Target": round(target, 2),
            "Exit": round(x, 2), "PnL": round(pnl, 2), "R_Multiple": round(r, 3),
            "Result": "WIN" if pnl > 0 else "LOSS", "Reason": reason}


# ---------------- per-strategy replays ----------------
def bt_orb(sym, data, cfg):
    """ORB "Stocks in Play" (research #1). The edge lives in the pre-market universe
    selection (gap + RVOL); replaying that faithfully means applying the GAP gate (computable
    from bars) + the research ORB_HEIGHT>=0.8% floor + range-based stop(=ORB_LOW)/target
    (=entry+2xORB_HEIGHT). Without these it degrades to naive ORB (Sharpe ~0.48, whipsaw).
    Env overrides: BT_ORB_GAP_MIN, BT_ORB_HEIGHT_MIN, BT_ORB_NAIVE=1 (old naive behaviour)."""
    naive = os.environ.get("BT_ORB_NAIVE") == "1"
    wins = parse_windows(cfg["windows"]); trades = []
    gap_min = 0.0 if naive else float(os.environ.get("BT_ORB_GAP_MIN",
                cfg.get("universe", {}).get("min_gap_pct", 0.02)))
    hmin = float(cfg.get("orb_height_min_pct", 0.003))
    if not naive:
        hmin = max(hmin, float(os.environ.get("BT_ORB_HEIGHT_MIN", 0.008)))  # research >=0.8%
    hmax = float(cfg.get("orb_height_max_pct", 0.05))
    vol_mult = float(cfg.get("signal", {}).get("vol_mult", 1.5))
    mid_pct = float(cfg.get("stop", {}).get("min_or_height_pct", 0.01))
    tmult = float(cfg.get("target", {}).get("mult", 2.0))
    buf = float(cfg.get("atr_entry_buffer_mult", 0.05))
    rvol_min = 0.0 if naive else float(os.environ.get("BT_ORB_RVOL_MIN",
                cfg.get("universe", {}).get("min_premarket_rvol", 1.5)))
    pmvol = data.get("pmvol", {})
    be = float(cfg.get("breakeven_mult", 1.0)); ts = float(cfg.get("trail_start_mult", 1.5)); tl = float(cfg.get("trail_lock_mult", 0.5))
    daily = data["daily"]
    for d in sessions(data["m1"]):
        bars = data["m1"][d]
        if len(bars) < 12: continue
        db_before = [b for b in daily if (b.date.date() if hasattr(b.date, "date") else b.date) < d]
        if not db_before or not db_before[-1].close: continue
        prior_close = db_before[-1].close
        gap = (bars[0].open - prior_close) / prior_close if prior_close else 0.0
        if gap < gap_min: continue        # Stocks-in-Play gate: only opening-gap names
        rv = premarket_rvol(pmvol, d)     # pre-market RVOL gate (keep if no baseline, like live)
        if rvol_min and rv is not None and rv < rvol_min: continue
        oh = max(b.high for b in bars[:5]); ol = min(b.low for b in bars[:5]); height = oh - ol
        if not oh or not (hmin <= height / oh <= hmax): continue
        atr_d = atr_daily(db_before)
        for i in range(5, len(bars) - 1):
            b = bars[i]
            if not in_windows(b, wins):
                if _min(b.date) > max(w[1] for w in wins): break
                continue
            if b.close <= oh: continue
            recent = [x.volume for x in bars[max(0, i-20):i] if x.volume]
            if recent and b.volume < vol_mult * (sum(recent)/len(recent)): continue
            vw = vwap_upto(bars, i)
            if vw is not None and b.close <= vw: continue
            entry = b.close + buf * atr_d
            structural = (oh + ol) / 2 if (height / oh < mid_pct) else ol   # ORB_MID on tiny range, else ORB_LOW
            if naive:
                stop = min(structural, entry * (1 - MIN_STOP)); r = entry - stop
                if r <= 0: continue
                target = entry + tmult * r
                if (target - entry) / r < MIN_RR: break
            else:
                stop = structural; r = entry - stop           # research: stop = ORB_LOW, never widened
                if r <= 0: continue
                target = entry + tmult * height                # research: entry + 2 x ORB_HEIGHT (range)
            ex, why, _ = simulate(bars, i, entry, stop, target, r, be, ts, tl)
            t = record(sym, d, entry, stop, target, ex, why, r)
            if t: trades.append(t)
            break
    return trades


def bt_pdh(sym, data, cfg):
    wins = parse_windows(cfg["windows"]); trades = []
    vol_mult = float(cfg.get("vol_mult", 1.5)); buf = float(cfg.get("breakout_buffer_pct", 0.001))
    off = float(cfg.get("entry_offset_pct", 0.0005)); stop_pct = float(cfg.get("stop_pct", 0.0005))
    t1 = float(cfg.get("target1_R", 2.0))
    be = float(cfg.get("breakeven_mult", 1.0)); ts = float(cfg.get("trail_start_mult", 1.5)); tl = float(cfg.get("trail_lock_mult", 0.5))
    daily = data["daily"]
    for d in sessions(data["m5"]):
        bars = data["m5"][d]
        if len(bars) < 4: continue
        db_before = [b for b in daily if (b.date.date() if hasattr(b.date, "date") else b.date) < d]
        if not db_before: continue
        pdh = db_before[-1].high
        for i in range(1, len(bars) - 1):
            b = bars[i]
            if not in_windows(b, wins):
                if _min(b.date) > max(w[1] for w in wins): break
                continue
            trig = pdh * (1 + buf)
            if b.close <= trig: continue
            recent = [x.volume for x in bars[max(0, i-6):i] if x.volume]
            if recent and b.volume < vol_mult * (sum(recent)/len(recent)): continue
            vw = vwap_upto(bars, i)
            if vw is not None and b.close <= vw: continue
            entry = trig + off * pdh
            stop = min(pdh * (1 - stop_pct), entry * (1 - MIN_STOP)); r = entry - stop
            if r <= 0: continue
            target = entry + t1 * r
            ex, why, _ = simulate(bars, i, entry, stop, target, r, be, ts, tl)
            t = record(sym, d, entry, stop, target, ex, why, r)
            if t: trades.append(t)
            break
    return trades


def bt_nr7(sym, data, cfg):
    wins = parse_windows(cfg["windows"]); trades = []
    pmin = float(cfg.get("price_min", 15)); pmax = float(cfg.get("price_max", 150))
    adv_min = float(cfg.get("adv_min_shares", 1_000_000)); adr_min = float(cfg.get("adr_min_pct", 5.0))
    sma_n = int(cfg.get("sma_period", 20)); nr7_n = int(cfg.get("nr7_lookback", 7))
    tmult = float(cfg.get("target_r_mult", 2.2)); satr = float(cfg.get("stop_atr_mult", 0.5))
    eoff = float(cfg.get("entry_offset_atr_mult", 0.05)); vbuf = float(cfg.get("vwap_stop_buffer_pct", 0.001))
    be = float(cfg.get("breakeven_at_R", 1.0)); ts = float(cfg.get("trail_start_mult", 1.5)); tl = float(cfg.get("trail_lock_mult", 0.5))
    daily = data["daily"]
    for d in sessions(data["m5"]):
        bars = data["m5"][d]
        if len(bars) < 4: continue
        db = [b for b in daily if (b.date.date() if hasattr(b.date, "date") else b.date) < d]
        if len(db) < max(sma_n, nr7_n) + 1: continue
        ref = db[-1]
        if not ref.close or ref.close < pmin or ref.close > pmax: continue
        if (ref.high - ref.low) > min(b.high - b.low for b in db[-nr7_n:]): continue
        adrp = sum((b.high - b.low)/b.close for b in db[-20:])/20*100
        if adrp < adr_min: continue
        if ref.close <= sum(b.close for b in db[-sma_n:])/sma_n: continue
        if sum((b.volume or 0) for b in db[-20:])/20 < adv_min: continue
        oh = bars[0].high; ol = bars[0].low
        for i in range(1, len(bars) - 1):
            b = bars[i]
            if not in_windows(b, wins):
                if _min(b.date) > max(w[1] for w in wins): break
                continue
            if b.close <= oh: continue
            vw = vwap_upto(bars, i)
            if vw is not None and b.close <= vw: continue
            a5 = atr_intraday(bars, i)
            entry = oh + eoff * a5
            sv = vw * (1 - vbuf) if vw else (ol - satr * a5)
            structural = max(ol - satr * a5, sv)
            stop = min(structural, entry * (1 - MIN_STOP)); r = entry - stop
            if r <= 0: continue
            target = entry + tmult * r
            ex, why, _ = simulate(bars, i, entry, stop, target, r, be, ts, tl)
            t = record(sym, d, entry, stop, target, ex, why, r)
            if t: trades.append(t)
            break
    return trades


def bt_vwap(sym, data, cfg):
    """VWAP Pullback / Reclaim continuation (break-and-retest of session VWAP), 5-min bars.
    Mirrors strategies/vwap_pullback.py: rising VWAP + impulse above VWAP -> controlled
    pullback that re-tests the VWAP zone on a higher low -> long when the bar reclaims above
    the pullback high (and VWAP) on volume. Stop below the pullback low, floored to
    min_stop_pct; target = entry + target_r_mult * R."""
    wins = parse_windows(cfg["windows"]); trades = []
    slope_lb = int(cfg.get("vwap_slope_lookback", 3)); lb = int(cfg.get("pullback_lookback", 8))
    impulse_pct = float(cfg.get("impulse_pct", 0.003)); touch_band = float(cfg.get("pullback_touch_band", 0.003))
    reclaim_depth = float(cfg.get("reclaim_depth_pct", 0.002)); vmult = float(cfg.get("vol_mult", 1.3))
    eoff = float(cfg.get("entry_offset_atr_mult", 0.05)); satr = float(cfg.get("stop_atr_mult", 0.5))
    tmult = float(cfg.get("target_r_mult", 2.0))
    be = float(cfg.get("breakeven_mult", 1.0)); ts = float(cfg.get("trail_start_mult", 1.5)); tl = float(cfg.get("trail_lock_mult", 0.5))
    for d in sessions(data["m5"]):
        bars = data["m5"][d]
        if len(bars) < max(lb, slope_lb) + 3: continue
        vw = [vwap_upto(bars, k) for k in range(len(bars))]
        for i in range(max(lb, slope_lb) + 1, len(bars) - 1):
            b = bars[i]
            if not in_windows(b, wins):
                if _min(b.date) > max(w[1] for w in wins): break
                continue
            vw_now = vw[i]
            if vw_now is None: continue
            base_vw = vw[i - slope_lb]
            if base_vw is None or vw_now <= base_vw: continue      # VWAP must be rising
            if b.close <= vw_now: continue                          # price above VWAP now
            lo = max(1, i - lb); i_imp = None
            for k in range(lo, i - 1):
                if vw[k] is not None and bars[k].high >= vw[k] * (1 + impulse_pct):
                    i_imp = k; break                                # first impulse above VWAP
            if i_imp is None: continue
            seg = range(i_imp + 1, i)
            if len(list(seg)) < 1: continue
            pullback_low = min(bars[j].low for j in seg)
            pullback_high = max(bars[j].high for j in seg)
            pl_idx = min(seg, key=lambda j: bars[j].low)
            if not any(vw[j] is not None and bars[j].low <= vw[j] * (1 + touch_band) for j in seg): continue
            vw_pl = vw[pl_idx]
            if vw_pl is not None and pullback_low < vw_pl * (1 - reclaim_depth): continue  # held above VWAP
            if pullback_low <= bars[i_imp].low: continue            # higher low vs impulse base
            if b.close <= pullback_high: continue                   # reclaim/continuation trigger
            recent = [x.volume for x in bars[max(0, i-6):i] if x.volume]
            if recent and b.volume < vmult * (sum(recent)/len(recent)): continue
            a5 = atr_intraday(bars, i)
            entry = pullback_high + eoff * a5
            stop = min(pullback_low - satr * a5, entry * (1 - MIN_STOP)); r = entry - stop
            if r <= 0: continue
            target = entry + tmult * r
            ex, why, _ = simulate(bars, i, entry, stop, target, r, be, ts, tl)
            t = record(sym, d, entry, stop, target, ex, why, r)
            if t: trades.append(t)
            break
    return trades


RUN = {"orb_stocks_in_play": bt_orb, "nr7_compression": bt_nr7, "pdh_breakout": bt_pdh,
       "vwap_pullback": bt_vwap}


def summarize(name, trades):
    if not trades: print(f"\n=== {name} ===  no trades"); return
    n = len(trades); wins = [t for t in trades if t["PnL"] > 0]
    pnl = sum(t["PnL"] for t in trades); gw = sum(t["PnL"] for t in wins)
    gl = abs(sum(t["PnL"] for t in trades if t["PnL"] < 0))
    exits = defaultdict(int)
    for t in trades: exits[t["Reason"]] += 1
    print(f"\n=== {name} ===")
    print(f"  trades={n}  win_rate={100*len(wins)/n:.0f}%  net_PnL=${pnl:,.0f}  "
          f"avg_R={sum(t['R_Multiple'] for t in trades)/n:.2f}  PF={gw/gl:.2f}" if gl else
          f"  trades={n}  win_rate={100*len(wins)/n:.0f}%  net_PnL=${pnl:,.0f}")
    print(f"  exits: {dict(exits)}  (net of {SLIP*10000:.0f}bps/side slippage + ${COMM_PS}/sh comm)")


def main():
    ib = connect()
    if not ib: print("Could not connect."); return
    os.makedirs(os.path.join(BASE, "reports"), exist_ok=True)
    try:
        for name in CFG.get("active_strategies", []):
            block = CFG["strategies"].get(name, {}); run = RUN.get(block.get("strategy_type"))
            if not run: continue
            universe = block.get("universe_symbols", [])[:UNIVERSE_CAP]
            safe = "".join(ch if ch.isalnum() else "_" for ch in name)
            rep = TradeReporter(os.path.join(BASE, "reports", f"bt_faithful_{safe}.xlsx"), name)
            print(f"\n--- {name} ({block['strategy_type']}) | {N_DAYS} sessions | windows {block.get('windows')} ---")
            need_m1 = block.get("strategy_type") == "orb_stocks_in_play"
            if need_m1 and os.environ.get("BT_ORB_USE_SCANNER", "0") == "1":
                # scanner only returns TODAY's snapshot (unrepresentative + often data-starved
                # for a historical replay) -> opt-in; default uses the liquid fixed universe.
                universe = scanner_symbols(ib, block, int(os.environ.get("BT_ORB_UNIVERSE_CAP", 12)))
            allt = []
            for sym in universe:
                data = get_data(ib, sym, need_m1=need_m1)
                if not data or not data.get("m5"): print(f"  {sym}: no data"); continue
                tr = run(sym, data, block)
                for t in tr: t["Strategy"] = name; rep.record_trade(t)
                allt += tr
                print(f"  {sym}: {len(tr)} trades")
            summarize(name, allt)
            print(f"  report -> reports/bt_faithful_{safe}.xlsx")
    finally:
        ib.disconnect(); print("\ndisconnected.")


if __name__ == "__main__":
    main()
