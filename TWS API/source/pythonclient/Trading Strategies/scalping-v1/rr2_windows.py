"""Time-window study of the 2:1 RR strategies — RTH ONLY (09:30-16:00 ET bars; no overnight/ETH data;
daily trend from RTH closes).

Each strategy is wrapped so it may only ENTER inside a window [start, end):
  mode 'flat' : trade lives inside the window — forced exit at the window end (time-window trading)
  mode 'hold' : enter inside the window, then manage normally (2R / stop / 16:00)
'event' strategies (one setup per day, e.g. IB / ORB breaks) are skipped for the day if their setup fires
before the window opens; 'continuous' ones (pullbacks, breakouts that can recur) just skip that signal.
Output: results/windows.csv (+ windows_trades.pkl)."""
import os
import pickle
import sys
from multiprocessing import Pool
import numpy as np
import pandas as pd
from scalp_engine import load_rth, add_indicators, simulate, metrics, Strategy, SPECS
import rr2_strategies as RS
import rr2_strategies2 as RS2
import strategies as S1
from rr2_final import IBTrend, add_trends

SYMS = ["MNQ", "MES", "MGC"]
SPLIT = pd.Timestamp("2026-05-01").date()
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")

WINDOWS = {  # name: (start, end) minutes since midnight ET
    "09:30-11:30": (570, 690), "11:30-13:30": (690, 810), "13:30-16:00": (810, 960),
    "09:30-10:30": (570, 630), "10:30-11:30": (630, 690), "11:30-12:30": (690, 750),
    "12:30-13:30": (750, 810), "13:30-14:30": (810, 870), "14:30-15:30": (870, 930), "15:30-16:00": (930, 960),
    "Full RTH": (570, 960),
}
MAIN = ["09:30-11:30", "11:30-13:30", "13:30-16:00", "Full RTH"]

# (label, strategy object, params, event?)
STRATS = [
    ("IB Trend Breakout (first break)", IBTrend(), dict(trend="e20", entry="first", stop="mid", nw=0.75), True),
    ("IB Trend Breakout (11:00 confirm)", IBTrend(), dict(trend="e20", entry="confirm", stop="mid", nw=9.9), True),
    ("ORB 15-min breakout 2R", S1.ORB(), dict(orm=15, stop="mid", tgt="r2", narrow=False, max_bars=999), True),
    ("ORB second break 2R", RS2.ORB2nd(), dict(orm=15, dtf=False, max_bars=999), True),
    ("Opening candle 2R (trend)", RS.FirstBar2R(), dict(stop=0.12, dtf=True, max_bars=999), True),
    ("Trend-Confluence Pullback 2R", RS.Confluence(), dict(trig="pb", k=1.0, mx=4, max_bars=999), False),
    ("Al Brooks H2/L2 (trend) 2R", RS.H2L2(), dict(maxr=3.0, dtf=True, max_bars=999), False),
    ("VWAP/EMA Pullback 2R", S1.VWAPPullback(), dict(r=2.0, first=600, max_bars=999, max_trades=4), False),
    ("Inside-bar breakout (trend) 2R", RS.InsideBar(), dict(nr=0.6, dtf=True, max_bars=999), False),
    ("Donchian 48-bar breakout 2R", RS2.Donchian(), dict(nb=48, k=1.0, dtf=False, flat=955), False),
    ("Noise-band momentum 2R", RS2.Noise2R(), dict(lb=14, mr=0.05, mx=3, max_bars=999), False),
    ("Bollinger squeeze 2R", S1.Squeeze(), dict(q=0.15, r=2.0, first=600, max_bars=999, max_trades=2), False),
    ("PDH/PDL sweep-reclaim 2R", S1.SweepReclaim(), dict(level="pd", tgt="r2", max_bars=999), False),
]


class Windowed(Strategy):
    def __init__(self, inner, start, end, mode, event):
        self.inner, self.start, self.end, self.mode, self.event = inner, start, end, mode, event
        self.name = inner.name

    def reset(self):
        self.inner.reset()

    def start_day(self, D, p):
        self.inner.start_day(D, p)
        p["last_entry"] = min(self.end - 5, 925 if self.mode == "hold" else self.end - 10)
        self.dead = False

    def signal(self, D, i, p):
        sig = self.inner.signal(D, i, p)            # always called: keeps the inner state machine in sync
        if not sig or self.dead:
            return None
        if D.tm[i + 1] < self.start:
            if self.event:
                self.dead = True                     # the day's one setup happened before the window
            return None
        if self.mode == "flat":
            sig = dict(sig, exit_tm=self.end)
            if sig.get("entry") is not None:
                sig["expire"] = min(sig.get("expire", 1), max(1, (self.end - 5 - D.tm[i + 1]) // 5))
        return sig

    def exit(self, D, j, d, p, sig):
        return self.inner.exit(D, j, d, p, sig)

    def on_trade(self, D, i, j, d, p):
        self.inner.on_trade(D, i, j, d, p)


def load(sym):
    df = add_trends(RS2.add_context2(RS.add_context(add_indicators(load_rth(sym)))))
    df["tick"] = SPECS[sym]["tick"]
    return df


def pf(x):
    return float(x.net[x.net > 0].sum() / -x.net[x.net < 0].sum()) if len(x) and (x.net < 0).any() else np.nan


def run_sym(sym):
    df = load(sym)
    days = sorted(df.day.unique())
    rows, trades = [], {}
    for label, st, p, ev in STRATS:
        for wn, (a, b) in WINDOWS.items():
            for mode in ("flat", "hold"):
                if wn == "Full RTH" and mode == "flat":
                    continue
                t = simulate(sym, df, Windowed(st, a, b, mode, ev), dict(p))
                trades[(label, wn, mode, sym)] = t
                for part, dd in (("ALL", days), ("IS", [d for d in days if d < SPLIT]), ("OOS", [d for d in days if d >= SPLIT])):
                    tt = t[t.day.isin(dd)] if len(t) else t
                    m = metrics(tt, dd)
                    rows.append(dict(strategy=label, window=wn, mode=mode, sym=sym, part=part, **m,
                                     tgt=float((tt.why == "tgt").mean()) if len(tt) else np.nan,
                                     stop=float((tt.why == "stop").mean()) if len(tt) else np.nan))
        print(sym, label, flush=True)
    return rows, trades


def main():
    with Pool(3) as pool:
        res = pool.map(run_sym, SYMS)
    rows = [r for rr, _ in res for r in rr]
    trades = {k: v for _, tt in res for k, v in tt.items()}
    pd.DataFrame(rows).to_csv(os.path.join(OUT, "windows.csv"), index=False)
    with open(os.path.join(OUT, "windows_trades.pkl"), "wb") as f:
        pickle.dump(trades, f)


if __name__ == "__main__":
    main()
