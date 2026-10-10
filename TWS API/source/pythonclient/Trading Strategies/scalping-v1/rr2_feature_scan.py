import sys, itertools, pandas as pd, numpy as np
k = sys.argv[1] if len(sys.argv) > 1 else "1.0"
SPLIT = pd.Timestamp("2026-05-01").date()
pd.set_option('display.width', 250); pd.set_option('display.max_rows', 300)
L = {s: pd.read_pickle(f"results/rr2_labels_{s}_k{k}.pkl") for s in ("MNQ", "MES", "MGC")}
ALIGN = ["dtrend", "vwap_side", "ema_side", "day_side", "pdc_side", "ib_state", "mom6", "first30"]
for s, d in L.items():
    for c in ALIGN:
        d["a_" + c] = d[c] * d["dir"]          # +1 = trade agrees with feature, -1 = against
    d["IS"] = d.day < SPLIT
    d["atr_hi"] = d.atr_rel > d.atr_rel.median()
def tab(mask_fn, label):
    out = []
    for s, d in L.items():
        m = mask_fn(d)
        for part in (True, False):
            x = d[m & (d.IS == part)]
            out.append((s, "IS" if part else "OOS", len(x), x.R.mean(), (x.why == "tgt").mean()))
    return out
print("=== single features (agree=+1)  meanR per (sym, IS/OOS); n per day-bar-dir sample")
rows = []
for c in ALIGN:
    for v in (1, -1):
        r = tab(lambda d: d["a_" + c] == v, f"{c}={v}")
        rows.append([f"{c}={v:+d}"] + [f"{m:+.3f}" for *_, m, _ in [(a, b, n, m, t) for a, b, n, m, t in r]])
for t in sorted(L["MNQ"].tod.unique()):
    r = tab(lambda d: d.tod == t, "")
    rows.append([f"tod={t//60:02d}:{t%60:02d}"] + [f"{m:+.3f}" for a, b, n, m, tt in r])
for v in (True, False):
    r = tab(lambda d: d.atr_hi == v, "")
    rows.append([f"atr_hi={v}"] + [f"{m:+.3f}" for a, b, n, m, tt in r])
cols = ["feature"] + [f"{s}_{p}" for s in L for p in ("IS", "OOS")]
print(pd.DataFrame(rows, columns=cols).to_string(index=False))
