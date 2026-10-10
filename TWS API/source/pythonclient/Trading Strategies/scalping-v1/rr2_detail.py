import pickle, sys, pandas as pd, numpy as np
SPLIT = pd.Timestamp("2026-05-01").date()
T = {}
for f in sys.argv[1:]:
    T.update(pickle.load(open(f, "rb")))
def show(cfg):
    print("==", cfg)
    allt = []
    for s in ("MNQ", "MES", "MGC"):
        t = T[(cfg, s)]; allt.append(t)
        IS, OOS = t[t.day < SPLIT], t[t.day >= SPLIT]
        pf = lambda x: x.net[x.net > 0].sum() / -x.net[x.net < 0].sum() if (x.net < 0).any() else np.inf
        print(f" {s} n={len(t):3d} tgt={np.mean(t.why=='tgt'):.0%} stop={np.mean(t.why=='stop'):.0%} other={np.mean(~t.why.isin(['tgt','stop'])):.0%} "
              f"avgR={t.r.mean():+.3f} PF={pf(t):.2f} ${t.net.sum():6.0f} | IS R {IS.r.mean():+.3f} PF {pf(IS):.2f} | OOS R {OOS.r.mean():+.3f} PF {pf(OOS):.2f} "
              f"| L n{(t.dir==1).sum()} ${t[t.dir==1].net.sum():.0f} S n{(t.dir==-1).sum()} ${t[t.dir==-1].net.sum():.0f}")
    a = pd.concat(allt)
    tstat = a.r.mean() / a.r.std() * np.sqrt(len(a))
    print(f" POOLED n={len(a)} avgR={a.r.mean():+.3f} t={tstat:.2f} tgt={np.mean(a.why=='tgt'):.0%}")
for c in [x for x in dict.fromkeys(k[0] for k in T) if x in CFGS] if False else []:
    pass
import re
CF = sys.stdin.read().split()
for c in CF:
    show(c)
