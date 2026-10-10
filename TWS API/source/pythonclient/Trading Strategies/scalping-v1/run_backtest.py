"""Run every strategy x param grid on MNQ/MES/MGC 5-min RTH bars; write results/all_configs.csv
and trades for every config to results/trades.pkl. In-sample = before SPLIT, out-of-sample = after."""
import os
import pickle
import pandas as pd
from scalp_engine import load_rth, add_indicators, simulate, metrics
from strategies import ALL

SYMS = ["MNQ", "MES", "MGC"]
SPLIT = pd.Timestamp("2026-05-01").date()
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
os.makedirs(OUT, exist_ok=True)


def main():
    data = {}
    for s in SYMS:
        df = add_indicators(load_rth(s))
        data[s] = df
        days = sorted(df.day.unique())
        print(f"{s}: {len(days)} days {days[0]} .. {days[-1]}  (IS {sum(d < SPLIT for d in days)} / OOS {sum(d >= SPLIT for d in days)})")
    rows, all_trades = [], {}
    for st in ALL:
        for k, p in enumerate(st.grid):
            cfg = f"{st.name}#{k}"
            for s in SYMS:
                df = data[s]
                days = [d for d in sorted(df.day.unique()) if d >= df.day.iloc[0]]
                t = simulate(s, df, st, p)
                all_trades[(cfg, s)] = t
                for part, dd in (("ALL", days), ("IS", [d for d in days if d < SPLIT]), ("OOS", [d for d in days if d >= SPLIT])):
                    tt = t[t.day.isin(dd)] if len(t) else t
                    rows.append(dict(strategy=st.name, cfg=cfg, params=str(p), sym=s, part=part, **metrics(tt, dd)))
        print(f"done {st.name} ({len(st.grid)} configs)", flush=True)
    res = pd.DataFrame(rows)
    res.to_csv(os.path.join(OUT, "all_configs.csv"), index=False)
    with open(os.path.join(OUT, "trades.pkl"), "wb") as f:
        pickle.dump(all_trades, f)


if __name__ == "__main__":
    main()
