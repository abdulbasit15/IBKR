"""Evaluate event definitions on the every-bar 2R label sets (stop = k x ATR, target 2R)."""
import pandas as pd, numpy as np
SPLIT = pd.Timestamp("2026-05-01").date()
pd.set_option('display.width', 250)
def prep(s, k):
    d = pd.read_pickle(f"results/rr2_labels_{s}_k{k}.pkl").sort_values(["ix", "dir"])
    d["IS"] = d.day < SPLIT
    # first IB break bar of the day per direction
    b = d[(d.ib_state * d.dir) == 1]
    first = b.groupby(["day", "dir"]).ix.min().rename("fib")
    d = d.join(first, on=["day", "dir"])
    d["ibbrk"] = d.ix == d.fib
    # first close across prior-day high/low per dir: use pdc_side? approximate with day_side flip
    return d
EV = {
    "IB first break": lambda d: d.ibbrk,
    "IB brk + dtrend": lambda d: d.ibbrk & (d.dtrend == d.dir),
    "IB brk + first30": lambda d: d.ibbrk & (d.first30 == d.dir),
    "IB brk + dtrend + first30": lambda d: d.ibbrk & (d.dtrend == d.dir) & (d.first30 == d.dir),
    "IB brk + vwap + ema": lambda d: d.ibbrk & (d.vwap_side == d.dir) & (d.ema_side == d.dir),
    "10:00-11:00 all agree": lambda d: d.tm.between(595, 655) & (d.dtrend == d.dir) & (d.first30 == d.dir) & (d.vwap_side == d.dir) & (d.mom6 == d.dir),
    "all agree any time": lambda d: (d.tm >= 595) & (d.dtrend == d.dir) & (d.first30 == d.dir) & (d.vwap_side == d.dir) & (d.mom6 == d.dir) & (d.pdc_side == d.dir),
}
rows = []
for k in ("0.5", "1.0", "2.0"):
    D = {s: prep(s, k) for s in ("MNQ", "MES", "MGC")}
    for name, fn in EV.items():
        row = [k, name]
        for s, d in D.items():
            x = d[fn(d)]
            for part in (True, False):
                y = x[x.IS == part]
                row += [len(y), round(y.R.mean(), 3), round((y.why == "tgt").mean(), 2)]
        rows.append(row)
cols = ["k", "event"] + [f"{s}_{p}_{m}" for s in ("MNQ", "MES", "MGC") for p in ("IS", "OOS") for m in ("n", "R", "tgt")]
print(pd.DataFrame(rows, columns=cols).to_string(index=False))
