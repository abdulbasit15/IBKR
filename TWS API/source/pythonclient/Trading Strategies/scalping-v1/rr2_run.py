"""Run all 2:1-RR candidates (rr2_strategies.ALL) on MNQ/MES/MGC 5-min RTH -> results/rr2_all.csv + rr2_trades.pkl"""
import os
import pickle
import sys
import pandas as pd
from scalp_engine import load_rth, add_indicators, simulate, metrics, SPECS
import rr2_strategies as RS
from eth_context import eth_context
import rr2_strategies2 as RS2

SYMS = ["MNQ", "MES", "MGC"]
SPLIT = pd.Timestamp("2026-05-01").date()
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")


def load(sym):
    df = RS.add_context(add_indicators(load_rth(sym)))
    df = RS2.add_context2(eth_context(sym, df))
    df["tick"] = SPECS[sym]["tick"]
    return df


def main(only=None):
    data = {s: load(s) for s in SYMS}
    rows, trades = [], {}
    for st in RS.ALL + RS2.ALL:
        if only and st.name not in only:
            continue
        for k, p in enumerate(st.grid):
            cfg = f"{st.name}#{k}"
            for s in SYMS:
                days = sorted(data[s].day.unique())
                t = simulate(s, data[s], st, dict(p))
                trades[(cfg, s)] = t
                for part, dd in (("ALL", days), ("IS", [d for d in days if d < SPLIT]), ("OOS", [d for d in days if d >= SPLIT])):
                    tt = t[t.day.isin(dd)] if len(t) else t
                    m = metrics(tt, dd)
                    m["tgt_rate"] = float((tt.why == "tgt").mean()) if len(tt) else float("nan")
                    rows.append(dict(strategy=st.name, cfg=cfg, params=str(p), sym=s, part=part, **m))
        print("done", st.name, len(st.grid), flush=True)
    res = pd.DataFrame(rows)
    tag = "_".join(only) if only else "all"
    res.to_csv(os.path.join(OUT, f"rr2_{tag}.csv"), index=False)
    with open(os.path.join(OUT, f"rr2_trades_{tag}.pkl"), "wb") as f:
        pickle.dump(trades, f)


if __name__ == "__main__":
    main(sys.argv[1:] or None)
