"""
Parity test: the LIVE decision path (scalping_v2_core.live_decision, fed only the bars completed so far, bar by bar)
must reproduce EXACTLY the trades the BACKTEST engine takes. Run after any change to scalping_v2_core.py.

For every day / strategy / symbol and every bar L, live_decision(bars[0..L]) is asked "what now?".
A live {"signal"} at L is turned into the trade it would cause using the next bar (same fill rules); the set
of those must equal the backtest's trades (signal bar, direction, stop, entry price). Also checks that
whenever the backtest is in a trade at bar L the live replay reports {"busy"}.

  python scalping_v2_parity_test.py               # all days
  python scalping_v2_parity_test.py --days 60     # last 60 sessions (faster)
"""
import argparse
import json
import os
import sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import scalping_v2_core as C  # noqa: E402
from scalping_v2_backtest import load_csv_bars, DEFAULT_DATA  # noqa: E402


def expected_from_signal(D, L, sig, tick, slip):
    """Mirror of the engine's entry logic for the bar after L (expire=1 stop entries / market entries)."""
    if L + 1 >= D.n:
        return None
    d, stop = sig["dir"], sig["stop"]
    k = L + 1
    if sig.get("entry") is not None:
        lvl = sig["entry"]
        if not ((D.high[k] >= lvl) if d == 1 else (D.low[k] <= lvl)):
            return None
        e = (max(D.open[k], lvl) if d == 1 else min(D.open[k], lvl)) + d * slip
    else:
        e = D.open[k] + d * slip
    if (e - stop) * d < 4 * tick:
        return None
    return (L, d, round(stop, 6), round(e, 6))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=os.path.join(HERE, "scalping_v2.json"))
    ap.add_argument("--days", type=int, default=0)
    a = ap.parse_args()
    cfg = json.load(open(a.config, encoding="utf-8"))
    total_bt = total_live = mism = busy_bad = 0
    for sym, scfg in cfg["symbols"].items():
        if not scfg.get("enabled", True):
            continue
        spec = C.SPECS[sym]
        tick = spec["tick"]
        df = C.add_indicators(load_csv_bars(C.SPECS[sym].get("data", sym), DEFAULT_DATA, "2025-09-02"), tick)
        days = sorted(df.day.unique())
        if a.days:
            days = days[-a.days:]
        for name, st_cfg in cfg["strategies"].items():
            if sym not in st_cfg.get("symbols", []):
                continue
            st, p = C.build_strategy(name, st_cfg)
            n_bt = n_live = bad = bb = 0
            for day in days:
                g = df[df.day == day].reset_index(drop=True)
                D = C.Day(g)
                if np.isnan(D.datr[0]):
                    continue
                bt = C._run_day(D, st, dict(p), tick, tick)
                bt_set = {(t["entry_bar"] - 1, t["dir"], round(t["stop"], 6), round(t["entry"], 6)) for t in bt}
                in_trade = set()
                for t in bt:
                    in_trade.update(range(t["entry_bar"], t["exit_bar"]))   # bars where the trade is open
                live_set = set()
                for L in range(D.n - 1):
                    dec = C.live_decision(g.iloc[:L + 1], st, p, tick)
                    if "signal" in dec:
                        e = expected_from_signal(D, L, dec["signal"], tick, tick)
                        if e:
                            live_set.add(e)
                    if L in in_trade and not dec.get("busy"):
                        bb += 1
                n_bt += len(bt_set)
                n_live += len(live_set)
                if bt_set != live_set:
                    bad += 1
                    if bad <= 3:
                        print(f"  MISMATCH {sym} {name} {day}: backtest-only {sorted(bt_set - live_set)} "
                              f"live-only {sorted(live_set - bt_set)}")
            print(f"{sym} {name:14s} backtest trades {n_bt:4d}  live-replay trades {n_live:4d}  "
                  f"mismatched days {bad}  busy-flag errors {bb}")
            total_bt += n_bt
            total_live += n_live
            mism += bad
            busy_bad += bb
    ok = mism == 0 and busy_bad == 0 and total_bt == total_live
    print(f"\nPARITY {'PASS' if ok else 'FAIL'}: {total_bt} backtest trades vs {total_live} live-replay trades, "
          f"{mism} mismatched day(s), {busy_bad} busy-flag error(s)")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
