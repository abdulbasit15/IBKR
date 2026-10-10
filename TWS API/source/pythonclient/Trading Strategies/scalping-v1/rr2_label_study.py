"""Data-driven 2:1 study. For EVERY 5-min RTH bar close i and both directions: enter at open[i+1] (+1 tick),
stop = k x ATR(14, 5m), target = 2 x stop. Walk forward bar by bar (stop first if both in a bar) until
hit or 16:00. Label = net R after costs. Then measure the conditional expectancy by context feature,
discovering on in-sample (< SPLIT) and checking on out-of-sample.
Output: results/rr2_labels_{SYM}_k{k}.pkl"""
import os
import sys
import numpy as np
import pandas as pd
from scalp_engine import SPECS
from rr2_run import load

SPLIT = pd.Timestamp("2026-05-01").date()
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")


def label(df, sym, k):
    sp = SPECS[sym]
    tick, pv, comm = sp["tick"], sp["pv"], sp["comm"]
    rows = []
    for day, g in df.groupby("day"):
        o, h, l, c, a, tm = (g[x].values for x in ("open", "high", "low", "close", "atr", "tm"))
        n = len(g)
        idx = g.index.values
        for i in range(n - 1):
            if tm[i + 1] > 930:
                break
            risk = max(k * a[i], 4 * tick)
            for d in (1, -1):
                e = o[i + 1] + d * tick
                stop, tgt = e - d * risk, e + d * 2 * risk
                res, j = None, i + 1
                while j < n:
                    if (l[j] <= stop) if d == 1 else (h[j] >= stop):
                        res = ((min(stop, o[j]) if d == 1 else max(stop, o[j])) - d * tick - e) * d
                        break
                    if (h[j] >= tgt + tick) if d == 1 else (l[j] <= tgt - tick):
                        res = 2 * risk
                        break
                    j += 1
                if res is None:
                    res = (c[n - 1] - d * tick - e) * d
                    why = "eod"
                else:
                    why = "tgt" if res > 0 and abs(res - 2 * risk) < 1e-9 else "stop"
                rows.append((idx[i], d, (res * pv - 2 * comm) / (risk * pv), why, j - i))
    lab = pd.DataFrame(rows, columns=["ix", "dir", "R", "why", "bars"])
    return lab


def features(df):
    f = pd.DataFrame(index=df.index)
    f["day"] = df.day
    f["tm"] = df.tm
    f["tod"] = ((df.tm + 5) // 30) * 30          # 30-min bucket of the signal-bar close
    f["dow"] = pd.to_datetime(df.day).dt.dayofweek
    f["dtrend"] = df.dtrend
    f["vwap_side"] = np.sign(df.close - df.vwap)
    f["ema_side"] = np.sign(df.ema9 - df.ema20)
    dopen = df.groupby("day").open.transform("first")
    f["day_side"] = np.sign(df.close - dopen)                     # above/below today's open
    f["pdc_side"] = np.sign(df.close - df.pdc)                    # above/below prior close
    ibh = df[df.tm < 630].groupby("day").high.max().reindex(df.day).values
    ibl = df[df.tm < 630].groupby("day").low.min().reindex(df.day).values
    f["ib_state"] = np.where(df.tm < 625, 0, np.where(df.close > ibh, 1, np.where(df.close < ibl, -1, 0)))
    f["mom6"] = np.sign(df.close - df.close.shift(6))             # 30-min momentum (crosses days only at 09:30)
    f["atr_rel"] = df.atr / (df.datr / 78 ** 0.5)                 # 5m ATR vs "typical" from daily range
    f["first30"] = np.sign(df[df.tm == 595].set_index("day").close.reindex(df.day).values - df.pdc.values)
    f.loc[df.tm < 595, "first30"] = 0
    return f


def main(k=1.0):
    for sym in ("MNQ", "MES", "MGC"):
        df = load(sym)
        lab = label(df, sym, k)
        f = features(df)
        lab = lab.join(f, on="ix")
        lab.to_pickle(os.path.join(OUT, f"rr2_labels_{sym}_k{k}.pkl"))
        print(sym, len(lab), "baseline meanR", round(lab.R.mean(), 3), "tgt%", round((lab.why == "tgt").mean(), 3), flush=True)


if __name__ == "__main__":
    main(float(sys.argv[1]) if len(sys.argv) > 1 else 1.0)
