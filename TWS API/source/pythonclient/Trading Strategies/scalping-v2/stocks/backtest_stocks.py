"""
Backtest the Scalping v2 bot's four strategies on liquid stocks / ETFs (5-min RTH bars from IB).
Uses the SAME engine as the bot (scalping_v2_core) with the SAME windows/params as scalping_v2.json.

Costs per share: slippage `--slip` cents per market/stop fill (engine: 1 tick = $0.01) + commission
`--comm` $/share per side (IBKR tiered ~0.0035). Results in R (net of costs, size-independent) and in $ with
risk_usd per trade, shares capped so the position notional <= max_notional.

  python backtest_stocks.py                       # all CSVs in Historical Data/data/equity_rth
  python backtest_stocks.py --slip 2 --comm 0.005 # cost stress
"""
import argparse
import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import scalping_v2_core as C  # noqa: E402

DATA = os.path.normpath(os.path.join(HERE, "..", "..", "Historical Data", "data", "equity_rth"))
ETFS = {"SPY", "QQQ", "IWM", "DIA"}


def load(sym):
    df = pd.read_csv(os.path.join(DATA, f"{sym}_5m_rth.csv"))
    return C.add_indicators(C.prepare_bars(df), 0.01)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=os.path.join(os.path.dirname(HERE), "scalping_v2.json"))
    ap.add_argument("--slip", type=int, default=1, help="slippage in cents per market/stop fill")
    ap.add_argument("--comm", type=float, default=0.0035, help="commission $/share per side")
    ap.add_argument("--risk-usd", type=float, default=1000)
    ap.add_argument("--max-notional", type=float, default=250000)
    ap.add_argument("--split", default="2025-10-01")
    ap.add_argument("--out", default=os.path.join(HERE, "results"))
    a = ap.parse_args()
    cfg = json.load(open(a.config, encoding="utf-8"))
    syms = sorted(f.split("_")[0] for f in os.listdir(DATA) if f.endswith("_5m_rth.csv"))
    rows = []
    spec = dict(pv=1.0, tick=0.01, comm=0.0)
    for sym in syms:
        df = load(sym)
        for name, sc in cfg["strategies"].items():
            st, p = C.build_strategy(name, sc)
            t = C.simulate(sym, df, st, p, spec, slip_ticks=a.slip)
            if not len(t):
                continue
            t["px"] = t.entry
            t["R_net"] = (t.pts - 2 * a.comm) / t.risk
            t["shares"] = np.floor(np.minimum(a.risk_usd / t.risk, a.max_notional / t.px))
            t["usd"] = t.shares * (t.pts - 2 * a.comm)
            rows.append(t)
        print(f"{sym}: {df.day.nunique()} sessions {df.day.min()} .. {df.day.max()}", flush=True)
    T = pd.concat(rows, ignore_index=True)
    os.makedirs(a.out, exist_ok=True)
    tag = f"slip{a.slip}_comm{a.comm}"
    T.to_csv(os.path.join(a.out, f"stock_trades_{tag}.csv"), index=False)
    sp = pd.Timestamp(a.split).date()

    def stats(x):
        if not len(x):
            return dict(n=0)
        w = x.R_net > 0
        gl = -x.R_net[~w].sum()
        return dict(n=len(x), win=w.mean(), tgt=(x.why == "target").mean(), avgR=x.R_net.mean(),
                    totR=x.R_net.sum(), pfR=x.R_net[w].sum() / gl if gl > 0 else np.inf,
                    t=x.R_net.mean() / x.R_net.std() * np.sqrt(len(x)) if len(x) > 2 else np.nan,
                    usd=x.usd.sum(), isR=x[x.day < sp].R_net.mean(), oosR=x[x.day >= sp].R_net.mean())
    out = []
    for (name, sym), g in T.groupby(["strategy", "sym"]):
        out.append(dict(strategy=name, sym=sym, group="ETF" if sym in ETFS else "Stock", **stats(g)))
    for (name, grp), g in T.assign(group=np.where(T.sym.isin(ETFS), "ETF", "Stock")).groupby(["strategy", "group"]):
        out.append(dict(strategy=name, sym=f"ALL {grp}s", group=grp, **stats(g)))
    for name, g in T.groupby("strategy"):
        out.append(dict(strategy=name, sym="ALL", group="ALL", **stats(g)))
    S = pd.DataFrame(out)
    S.to_csv(os.path.join(a.out, f"stock_summary_{tag}.csv"), index=False)
    pd.set_option("display.width", 220)
    pd.set_option("display.max_rows", 200)
    print(f"\ncosts: slip {a.slip}c/fill, comm ${a.comm}/sh/side | IS < {a.split} <= OOS")
    print(S.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
