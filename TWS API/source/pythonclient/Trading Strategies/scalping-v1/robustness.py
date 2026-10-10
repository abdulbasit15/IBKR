"""Robustness checks for the 3 finalists: parameter neighbourhood, 2-tick slippage stress, long/short split,
monthly P&L, IS/OOS. Writes results/finalists.json (consumed by make_report.py) and prints tables."""
import json
import os
import pandas as pd
from scalp_engine import load_rth, add_indicators, simulate, metrics, SPECS
from strategies import ORB, FirstBar, LastHalf

SYMS = ["MNQ", "MES", "MGC"]
SPLIT = pd.Timestamp("2026-05-01").date()
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")

FINALISTS = {
    "IB Breakout": (ORB(), dict(orm=60, stop="opp", tgt="ext0.5", narrow=False, max_bars=24)),
    "Opening-Candle Momentum": (FirstBar(), dict(s=0.10, r=None, max_bars=12, last_entry=575)),
    "Last-Half-Hour Momentum": (LastHalf(), dict(sig="first30", thr=0.25, last_entry=930)),
}
NEIGH = {
    "IB Breakout": [dict(orm=o, stop=s, tgt=t, narrow=False, max_bars=24)
                    for o in (45, 60, 75, 90) for s in ("opp", "mid") for t in ("ext0.3", "ext0.5", "ext0.75", "ext1.0")],
    "Opening-Candle Momentum": [dict(s=s, r=None, max_bars=m, last_entry=575)
                                for s in (0.075, 0.10, 0.15) for m in (6, 12, 18, 24)],
    "Last-Half-Hour Momentum": [dict(sig=g, thr=t, last_entry=930) for g in ("first30", "day") for t in (0.1, 0.25, 0.4)],
}


def summarize(t, days):
    m = metrics(t, days)
    return {k: (None if pd.isna(v) else float(v)) for k, v in m.items()}


def main():
    data = {s: add_indicators(load_rth(s)) for s in SYMS}
    days = {s: sorted(data[s].day.unique()) for s in SYMS}
    out = {"meta": {s: dict(first=str(days[s][0]), last=str(days[s][-1]), n=len(days[s])) for s in SYMS},
           "specs": SPECS, "split": str(SPLIT), "strategies": {}}
    for name, (st, p) in FINALISTS.items():
        res = {"params": p, "doc": st.__doc__.strip(), "sym": {}}
        print(f"\n=== {name}  {p}")
        for s in SYMS:
            dd = days[s]
            t = simulate(s, data[s], st, dict(p))
            t2 = simulate(s, data[s], st, dict(p), slip_ticks=2)
            isd, osd = [d for d in dd if d < SPLIT], [d for d in dd if d >= SPLIT]
            r = dict(
                all=summarize(t, dd), IS=summarize(t[t.day.isin(isd)], isd), OOS=summarize(t[t.day.isin(osd)], osd),
                slip2=summarize(t2, dd),
                long=summarize(t[t.dir == 1], dd), short=summarize(t[t.dir == -1], dd),
                avg_pts=float(t.pts.mean()), avg_hold_min=float(t.bars.mean() * 5),
                exits=t.why.value_counts().to_dict(),
                monthly={str(k): float(v) for k, v in t.assign(m=pd.to_datetime(t.day).dt.to_period("M")).groupby("m").net.sum().items()},
                equity=[[str(d), float(v)] for d, v in t.groupby("day").net.sum().reindex(dd, fill_value=0).cumsum().items()],
            )
            # neighbourhood
            nb = []
            for q in NEIGH[name]:
                tq = simulate(s, data[s], st, dict(q))
                m = metrics(tq, dd)
                nb.append(dict(params=q, n=int(m["n"]), net=float(m["net"]), pf=float(m["pf"]), win=float(m["win"])))
            r["neigh"] = nb
            r["neigh_pos"] = sum(x["net"] > 0 for x in nb) / len(nb)
            res["sym"][s] = r
            a, i_, o_, s2 = r["all"], r["IS"], r["OOS"], r["slip2"]
            print(f"{s}: n={a['n']:.0f} win={a['win']:.0%} PF={a['pf']:.2f} net=${a['net']:.0f} DD=${a['dd']:.0f} "
                  f"Sharpe={a['sharpe']:.2f} | IS PF {i_['pf']:.2f} ${i_['net']:.0f} | OOS PF {o_['pf']:.2f} ${o_['net']:.0f} "
                  f"| 2-tick slip PF {s2['pf']:.2f} ${s2['net']:.0f} | L ${r['long']['net']:.0f} S ${r['short']['net']:.0f} "
                  f"| hold {r['avg_hold_min']:.0f}m | neighbours positive {r['neigh_pos']:.0%}")
        out["strategies"][name] = res
    with open(os.path.join(OUT, "finalists.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)


if __name__ == "__main__":
    main()
