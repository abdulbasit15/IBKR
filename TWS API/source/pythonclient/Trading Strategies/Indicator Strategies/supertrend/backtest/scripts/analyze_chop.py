"""Find choppy vs trending stretches: per-month Efficiency Ratio (ER, low=choppy) and
Supertrend flip count (high=whipsaw) on continuous MNQ 1h & 30m."""
import csv, os
from datetime import datetime
from collections import defaultdict
import backtest_adx as B   # reuse load(vol>0 filter) + supertrend

D = r"C:\Users\abdbasit\Downloads\Personal\Trade"


def monthly(sym, fname):
    bars = B.load(os.path.join(D, fname))
    h = [b["high"] for b in bars]; l = [b["low"] for b in bars]; c = [b["close"] for b in bars]
    trend, _ = B.supertrend(h, l, c, 10, 3.0)
    by = defaultdict(list)
    for i, b in enumerate(bars):
        by[b["ts"].strftime("%Y-%m")].append(i)
    print(f"\n### {sym} {fname}  ({len(bars)} bars, {bars[0]['ts'].date()}..{bars[-1]['ts'].date()})")
    print(f"{'month':<9}{'bars':>6}{'netRet%':>9}{'ER':>7}{'STflips':>9}{'range%':>8}  chop?")
    rows = []
    for m in sorted(by):
        idx = by[m]
        if len(idx) < 20:
            continue
        seg = [c[i] for i in idx]
        net = seg[-1] - seg[0]
        path = sum(abs(seg[k] - seg[k-1]) for k in range(1, len(seg))) or 1e-9
        er = abs(net) / path
        flips = sum(1 for k in range(1, len(idx)) if trend[idx[k]] != trend[idx[k-1]])
        hi = max(h[i] for i in idx); lo = min(l[i] for i in idx)
        rng = (hi - lo) / seg[0] * 100
        netpct = net / seg[0] * 100
        chop = "CHOP" if er < 0.12 else ("trend" if er > 0.30 else "")
        rows.append((m, er, flips, netpct))
        print(f"{m:<9}{len(idx):>6}{netpct:>+9.1f}{er:>7.2f}{flips:>9}{rng:>8.1f}  {chop}")
    return rows


if __name__ == "__main__":
    monthly("MNQ", "MNQ_cont_1hour.csv")
    monthly("MNQ", "MNQ_cont_30mins.csv")
