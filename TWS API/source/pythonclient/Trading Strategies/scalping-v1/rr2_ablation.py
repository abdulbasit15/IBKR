import pandas as pd, numpy as np
from scalp_engine import simulate, metrics
from rr2_run import load
from rr2_strategies import Confluence
SPLIT = pd.Timestamp("2026-05-01").date()
class Abl(Confluence):
    def _stack(self, D, i):
        if D.tm[i] < 595 or i < 6:
            return 0
        if D.state["f30"] is None:
            k = np.where(D.tm == 595)[0]
            D.state["f30"] = np.sign(D.close[k[0]] - D.pdc[0]) if len(k) else 0
        c = D.close[i]
        comp = {"daily": D.dtrend[0], "first30": D.state["f30"], "pdc": np.sign(c - D.pdc[0]),
                "vwap": np.sign(c - D.vwap[i]), "mom": np.sign(c - D.close[i - 6])}
        v = [x for n, x in comp.items() if n not in self.drop]
        ref = v[0]
        return int(ref) if ref != 0 and all(x == ref for x in v) else 0
base = dict(trig="pb", k=1.0, mx=4, last_entry=900, max_bars=999)
rows = []
data = {s: load(s) for s in ("MNQ", "MES", "MGC")}
for drop in [(), ("daily",), ("first30",), ("pdc",), ("vwap",), ("mom",), ("first30", "pdc"), ("daily", "first30", "pdc")]:
    st = Abl(); st.drop = set(drop)
    row = ["-".join(drop) or "none"]
    for s, df in data.items():
        days = sorted(df.day.unique())
        t = simulate(s, df, st, dict(base))
        for part in (True, False):
            dd = [d for d in days if (d < SPLIT) == part]
            m = metrics(t[t.day.isin(dd)], dd)
            row += [m["n"], round(m["pf"], 2), round(m["net"])]
    rows.append(row)
cols = ["dropped"] + [f"{s}_{p}_{m}" for s in data for p in ("IS", "OOS") for m in ("n", "pf", "$")]
print(pd.DataFrame(rows, columns=cols).to_string(index=False))
