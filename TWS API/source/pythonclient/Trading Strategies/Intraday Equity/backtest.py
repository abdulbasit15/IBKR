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
    for p in PORTS:
        try:
            ib.connect("127.0.0.1", p, clientId=93, readonly=True)
            ib.reqMarketDataType(3)
            ib.sleep(6)   # let the HMDS data farm wake after (re)login before first hist req
            print(f"connected on port {p}")
            return ib
        except Exception as e:
            print(f"  port {p} failed: {e}")
    return None


_cache = {}
def get_data(ib, sym):
    if sym in _cache:
        return _cache[sym]
    c = Stock(sym, "SMART", "USD")
    def _hist(dur, bar, retries=1):
        # isolate each request: a 1-min pacing failure must NOT null out daily/5-min
        for _ in range(retries + 1):
            try:
                b = ib.reqHistoricalData(c, "", dur, bar, "TRADES", True, 1); ib.sleep(0.3)
                if b:
                    return b
            except Exception as e:
                print(f"  {sym} {dur}/{bar}: {e}"); ib.sleep(0.5)
        return []
    try:
        ib.qualifyContracts(c)
    except Exception as e:
        print(f"  {sym}: qualify error {e}"); _cache[sym] = None; return None
    daily = _hist("40 D", "1 day", retries=1)
    m5 = _hist(f"{N_DAYS+4} D", "5 mins", retries=1)
    m1 = _hist(f"{min(N_DAYS,10)+2} D", "1 min", retries=1)
    def by_day(bars):
        d = defaultdict(list)
        for b in (bars or []):
            d[b.date.date() if hasattr(b.date, "date") else b.date].append(b)
        for k in d: d[k].sort(key=lambda b: b.date)
        return d
    _cache[sym] = {"daily": daily or [], "m5": by_day(m5), "m1": by_day(m1)}
    return _cache[sym]


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
    wins = parse_windows(cfg["windows"]); trades = []
    hmin = float(cfg.get("orb_height_min_pct", 0.003)); hmax = float(cfg.get("orb_height_max_pct", 0.05))
    vol_mult = float(cfg.get("signal", {}).get("vol_mult", 1.5))
    mid_pct = float(cfg.get("stop", {}).get("min_or_height_pct", 0.01))
    tmult = float(cfg.get("target", {}).get("mult", 2.0))
    buf = float(cfg.get("atr_entry_buffer_mult", 0.05))
    be = float(cfg.get("breakeven_mult", 1.0)); ts = float(cfg.get("trail_start_mult", 1.5)); tl = float(cfg.get("trail_lock_mult", 0.5))
    daily = data["daily"]
    for d in sorted(data["m1"])[-N_DAYS:]:
        bars = data["m1"][d]
        if len(bars) < 12: continue
        db_before = [b for b in daily if (b.date.date() if hasattr(b.date, "date") else b.date) < d]
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
            structural = (oh + ol) / 2 if (height / oh < mid_pct) else ol
            stop = min(structural, entry * (1 - MIN_STOP)); r = entry - stop
            if r <= 0: continue
            target = entry + tmult * r
            if (target - entry) / r < MIN_RR: break
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
    for d in sorted(data["m5"])[-N_DAYS:]:
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
    for d in sorted(data["m5"])[-N_DAYS:]:
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


RUN = {"orb_stocks_in_play": bt_orb, "nr7_compression": bt_nr7, "pdh_breakout": bt_pdh}


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
            allt = []
            for sym in universe:
                data = get_data(ib, sym)
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
