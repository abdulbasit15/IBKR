"""Same strategy, same dates: SPY vs MES and QQQ vs MNQ (R per trade, net of each market's costs).
Answers: do the futures strategies behave the same on the ETF over the identical period?"""
import json
import os
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import scalping_v2_core as C  # noqa: E402
from scalping_v2_backtest import load_csv_bars, DEFAULT_DATA  # noqa: E402
from backtest_stocks import load as load_stock  # noqa: E402

cfg = json.load(open(os.path.join(os.path.dirname(HERE), "scalping_v2.json"), encoding="utf-8"))
START, END = pd.Timestamp("2025-09-02").date(), pd.Timestamp("2026-10-07").date()
pairs = [("SPY", "MES"), ("QQQ", "MNQ")]
rows = []
for etf, fut in pairs:
    fs = C.SPECS[fut]
    fdf = C.add_indicators(load_csv_bars(fut, DEFAULT_DATA, "2025-09-02"), fs["tick"])
    edf = load_stock(etf)
    for name, sc in cfg["strategies"].items():
        st, p = C.build_strategy(name, sc)
        tf = C.simulate(fut, fdf, st, p, fs)
        te = C.simulate(etf, edf, st, p, dict(pv=1.0, tick=0.01, comm=0.0))
        te = te[(te.day >= START) & (te.day <= END)]
        te_r = (te.pts - 2 * 0.0035) / te.risk
        rows.append(dict(strategy=name, pair=f"{etf} vs {fut}", n_etf=len(te), R_etf=te_r.mean(), n_fut=len(tf), R_fut=tf.r.mean(),
                         same_day_dir=len(set(zip(te.day, te.dir)) & set(zip(tf.day, tf.dir))) / max(1, min(len(te), len(tf)))))
print(pd.DataFrame(rows).round(3).to_string(index=False))
