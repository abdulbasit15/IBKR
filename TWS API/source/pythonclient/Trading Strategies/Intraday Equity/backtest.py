"""Simple historical backtest for the three intraday strategies, using IBKR historical
bars (works against TWS or IB Gateway, paper or live - read-only, places NO orders).

It replays each strategy's CORE rules on 5-min RTH bars over the last ~N sessions:
  ORB : 09:30-09:35 opening range -> long on a later 5-min close > OR_high (vol-confirmed,
        above session VWAP); stop OR_low (or OR_mid on a narrow range); target +2x range.
  PDH : long on a 5-min close > prior-day high * 1.001 (vol-confirmed, > VWAP); stop floored
        to min_stop_pct below entry; target +2R.
  NR7 : only on days whose PRIOR day was an NR7 compression (narrowest range of 7, ADR%>5,
        close>SMA20); then the ORB breakout with stop = OR_low - 0.5*ATR5 (floored), +2.2R.

SIMPLIFICATIONS (so read the numbers as indicative, not live-accurate):
  * one trade per symbol per day; exit = first of {stop, target, EOD close}, stop checked
    before target within a bar (conservative); NO breakeven/trail/scale-out.
  * pre-market gap / cross-day RVOL "stocks in play" filters are NOT applied - the
    configured universe stands in for the scan. Volume confirmation + session-VWAP gate ARE
    applied (both computed from the bars).
  * dollars sized at 1% risk-at-stop on strategy_capital (the intended risk model);
    fixed_stocks is ignored for the backtest. R-multiples are sizing-independent.
"""
from __future__ import annotations
import asyncio
import json
import math
import os
import sys
from collections import defaultdict

BASE = os.path.dirname(os.path.abspath(__file__))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from ib_async import IB, Stock, util  # noqa: E402
from reporting import TradeReporter    # noqa: E402

N_DAYS = 10          # sessions to replay
UNIVERSE_CAP = 10    # symbols per strategy (keep it quick)
VOL_MULT = 1.5
PORTS = [4002, 7497, 4001]   # IB Gateway paper, TWS paper, IB Gateway live (last resort)


def connect():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    ib = IB()
    for port in PORTS:
        try:
            ib.connect("127.0.0.1", port, clientId=77, readonly=True)
            print(f"connected on port {port} ({'gateway-paper' if port==4002 else 'tws' if port==7497 else 'gateway'})")
            return ib
        except Exception as e:
            print(f"  port {port} failed: {e}")
    return None


_bars_cache: dict = {}


def get_bars(ib, sym):
    if sym in _bars_cache:
        return _bars_cache[sym]
    c = Stock(sym, "SMART", "USD")
    try:
        ib.qualifyContracts(c)
        daily = ib.reqHistoricalData(c, "", "40 D", "1 day", "TRADES", True, 1)
        ib.sleep(0.3)
        m5 = ib.reqHistoricalData(c, "", f"{N_DAYS + 5} D", "5 mins", "TRADES", True, 1)
        ib.sleep(0.3)
    except Exception as e:
        print(f"  {sym}: hist error {e}")
        _bars_cache[sym] = (None, None)
        return None, None
    if not m5:
        _bars_cache[sym] = (daily, None)
        return daily, None
    days = defaultdict(list)
    for b in m5:
        days[b.date.date() if hasattr(b.date, "date") else b.date].append(b)
    for d in days:
        days[d].sort(key=lambda b: b.date)
    _bars_cache[sym] = (daily, days)
    return daily, days


def running_vwap(bars):
    """Per-bar cumulative session VWAP (typical price * volume)."""
    out, pv, vv = [], 0.0, 0.0
    for b in bars:
        tp = (b.high + b.low + b.close) / 3
        pv += tp * (b.volume or 0)
        vv += (b.volume or 0)
        out.append(pv / vv if vv else b.close)
    return out


def simulate_exit(bars_after, entry, stop, target):
    for b in bars_after:
        if b.low <= stop:
            return stop, "STOP"
        if b.high >= target:
            return target, "TARGET"
    if bars_after:
        return bars_after[-1].close, "EOD"
    return entry, "NONE"


def vol_confirmed(day_bars, idx):
    prior = [b.volume for b in day_bars[1:idx] if b.volume]   # same-day bars before breakout
    if len(prior) < 2:
        return True
    return (day_bars[idx].volume or 0) >= VOL_MULT * (sum(prior) / len(prior))


def atr5(day_bars, idx, period=14):
    seg = day_bars[max(0, idx - period):idx]
    if len(seg) < 2:
        return 0.0
    trs = [seg[i].high - seg[i].low for i in range(len(seg))]
    return sum(trs) / len(trs)


def make_trade(sym, d, entry, stop, target, exit_px, reason, capital, min_stop_pct):
    stop = min(stop, entry * (1 - min_stop_pct))      # floor risk-per-share (sizing sanity)
    rps = entry - stop
    if rps <= 0:
        return None
    shares = math.floor(capital * 0.01 / rps)
    if shares <= 0:
        return None
    pnl = (exit_px - entry) * shares
    r = (exit_px - entry) / rps
    return {"Date": str(d), "Time": "", "Strategy": "", "Ticker": sym, "Sector": "",
            "Shares": shares, "Entry": round(entry, 2), "Stop": round(stop, 2),
            "Target": round(target, 2), "Exit": round(exit_px, 2), "PnL": round(pnl, 2),
            "R_Multiple": round(r, 3), "Result": "WIN" if pnl > 0 else ("LOSS" if pnl < 0 else "FLAT"),
            "Reason": reason, "HoldMin": ""}


def bt_orb(sym, daily, days, cap, min_stop):
    trades = []
    for d in sorted(days)[-N_DAYS:]:
        db = days[d]
        if len(db) < 4:
            continue
        orb = db[0]
        h, l = orb.high, orb.low
        height = h - l
        if not h or not (0.003 <= height / h <= 0.05):
            continue
        vwap = running_vwap(db)
        stop = (h + l) / 2 if height / h < 0.01 else l
        for i in range(1, len(db) - 1):
            b = db[i]
            if b.close > h and b.close > vwap[i] and vol_confirmed(db, i):
                entry = b.close
                target = entry + 2.0 * height
                exit_px, reason = simulate_exit(db[i + 1:], entry, stop, target)
                t = make_trade(sym, d, entry, stop, target, exit_px, reason, cap, min_stop)
                if t:
                    trades.append(t)
                break
    return trades


def bt_pdh(sym, daily, days, cap, min_stop):
    trades = []
    if not daily:
        return trades
    by_date = {b.date.date() if hasattr(b.date, "date") else b.date: b for b in daily}
    dlist = sorted(by_date)
    for d in sorted(days)[-N_DAYS:]:
        if d not in dlist:
            continue
        idx = dlist.index(d)
        if idx == 0:
            continue
        pdh = by_date[dlist[idx - 1]].high
        db = days[d]
        if len(db) < 4:
            continue
        vwap = running_vwap(db)
        trig = pdh * 1.001
        for i in range(1, len(db) - 1):
            b = db[i]
            if b.close > trig and b.close > vwap[i] and vol_confirmed(db, i):
                entry = b.close
                stop = min(pdh * 0.9995, entry * (1 - min_stop))
                rps = entry - stop
                target = entry + 2.0 * rps
                exit_px, reason = simulate_exit(db[i + 1:], entry, stop, target)
                t = make_trade(sym, d, entry, stop, target, exit_px, reason, cap, min_stop)
                if t:
                    trades.append(t)
                break
    return trades


def bt_nr7(sym, daily, days, cap, min_stop):
    trades = []
    if not daily or len(daily) < 28:
        return trades
    by_date = {b.date.date() if hasattr(b.date, "date") else b.date: b for b in daily}
    dlist = sorted(by_date)
    for d in sorted(days)[-N_DAYS:]:
        if d not in dlist:
            continue
        idx = dlist.index(d)
        if idx < 21:
            continue
        prior = by_date[dlist[idx - 1]]                       # the compression day
        last7 = [by_date[dlist[idx - 1 - k]] for k in range(7)]
        if (prior.high - prior.low) > min(b.high - b.low for b in last7):
            continue
        adr = sum((b.high - b.low) / b.close for b in [by_date[dlist[idx - 1 - k]] for k in range(20)]) / 20 * 100
        if adr < 5.0:
            continue
        sma = sum(by_date[dlist[idx - 1 - k]].close for k in range(20)) / 20
        if prior.close <= sma:
            continue
        db = days[d]
        if len(db) < 4:
            continue
        orb = db[0]
        h, l = orb.high, orb.low
        vwap = running_vwap(db)
        for i in range(1, len(db) - 1):
            b = db[i]
            if b.close > h and b.close > vwap[i] and vol_confirmed(db, i):
                entry = b.close
                a5 = atr5(db, i)
                stop = max(l - 0.5 * a5, vwap[i] * (1 - 0.001))
                stop = min(stop, entry * (1 - min_stop))
                rps = entry - stop
                if rps <= 0:
                    break
                target = entry + 2.2 * rps
                exit_px, reason = simulate_exit(db[i + 1:], entry, stop, target)
                t = make_trade(sym, d, entry, stop, target, exit_px, reason, cap, min_stop)
                if t:
                    trades.append(t)
                break
    return trades


RUNNERS = {"orb_stocks_in_play": bt_orb, "nr7_compression": bt_nr7, "pdh_breakout": bt_pdh}


def summarize(name, trades):
    n = len(trades)
    if not n:
        print(f"\n=== {name} ===  no trades")
        return
    wins = [t for t in trades if t["PnL"] > 0]
    losses = [t for t in trades if t["PnL"] < 0]
    pnl = sum(t["PnL"] for t in trades)
    gw = sum(t["PnL"] for t in wins)
    gl = abs(sum(t["PnL"] for t in losses))
    pf = round(gw / gl, 2) if gl else "inf"
    avg_r = sum(t["R_Multiple"] for t in trades) / n
    print(f"\n=== {name} ===")
    print(f"  trades={n}  win_rate={100*len(wins)/n:.0f}%  total_PnL=${pnl:,.0f}  "
          f"avg_R={avg_r:.2f}  profit_factor={pf}  (sized @1% of strategy_capital)")
    print(f"  best=${max(t['PnL'] for t in trades):,.0f}  worst=${min(t['PnL'] for t in trades):,.0f}")


def main():
    cfg = json.load(open(os.path.join(BASE, "equity.json")))
    ib = connect()
    if ib is None:
        print("Could not connect to IBKR (tried gateway 4002 / TWS 7497). Is the API enabled?")
        return
    reports_dir = os.path.join(BASE, "reports")
    os.makedirs(reports_dir, exist_ok=True)
    min_stop = float(cfg.get("shared_risk", {}).get("min_stop_pct", 0.005))
    try:
        for name in cfg.get("active_strategies", []):
            block = cfg["strategies"].get(name, {})
            stype = block.get("strategy_type")
            run = RUNNERS.get(stype)
            if not run:
                continue
            cap = float(block.get("strategy_capital", 100000))
            universe = block.get("universe_symbols", [])[:UNIVERSE_CAP]
            safe = "".join(ch if ch.isalnum() else "_" for ch in name)
            rep = TradeReporter(os.path.join(reports_dir, f"backtest_{safe}.xlsx"), name)
            print(f"\n--- backtesting '{name}' ({stype}) over {N_DAYS} sessions, "
                  f"{len(universe)} symbols ---")
            all_tr = []
            for sym in universe:
                daily, days = get_bars(ib, sym)
                if not days:
                    print(f"  {sym}: no intraday data (skip)")
                    continue
                tr = run(sym, daily, days, cap, min_stop)
                for t in tr:
                    t["Strategy"] = name
                    rep.record_trade(t)
                all_tr += tr
                print(f"  {sym}: {len(tr)} trades")
            summarize(name, all_tr)
            print(f"  report -> reports/backtest_{safe}.xlsx")
    finally:
        ib.disconnect()
        print("\ndisconnected.")


if __name__ == "__main__":
    main()
