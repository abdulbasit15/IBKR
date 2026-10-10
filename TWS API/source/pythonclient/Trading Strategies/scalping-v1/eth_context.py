"""Overnight / Asia / London context per RTH day from {SYM}_cont_5mins_eth.csv (useRTH=False).
Globex session for RTH day D = 18:00 ET (D-1) .. 09:30 ET (D).  Columns (NaN when ETH data missing):
  onh/onl  overnight high/low (18:00-09:30)   onr = onh-onl
  ash/asl  Asia 18:00-03:00                    lnh/lnl London 03:00-08:00
  pre_h/pre_l 08:00-09:30 (US pre-open incl. 8:30 data)
Prices are shifted onto the RTH series' back-adjustment using the median close difference on overlap."""
import os
import numpy as np
import pandas as pd
from scalp_engine import DATA_DIR, TZ


def eth_context(sym, rth_df):
    p = os.path.join(DATA_DIR, f"{sym}_cont_5mins_eth.csv")
    e = pd.read_csv(p)
    e["date"] = pd.to_datetime(e["date"], utc=True).dt.tz_convert(TZ)
    # align price level with the RTH frame (different back-adjustment after rolls)
    rk = rth_df.set_index(rth_df.date.dt.tz_convert("UTC")).close
    ek = e.set_index(e.date.dt.tz_convert("UTC")).close
    common = rk.index.intersection(ek.index)
    off = float((rk.loc[common] - ek.loc[common]).median()) if len(common) else 0.0
    for c in ("open", "high", "low", "close"):
        e[c] = e[c] + off
    tm = e.date.dt.hour * 60 + e.date.dt.minute
    sess = (e.date + pd.Timedelta(hours=6)).dt.date                 # 18:00 ET rolls to next day
    e = e.assign(tm=tm, sess=sess)
    e = e[e.tm.lt(570) | e.tm.ge(1080)]                              # overnight bars only
    g = e.groupby("sess")
    ctx = pd.DataFrame({"onh": g.high.max(), "onl": g.low.min()})
    for nm, (a, b) in {"as": (1080, 180), "ln": (180, 480), "pre": (480, 570)}.items():
        m = (e.tm >= a) | (e.tm < b) if a > b else (e.tm >= a) & (e.tm < b)
        gg = e[m].groupby("sess")
        ctx[f"{nm}h" if nm != "pre" else "pre_h"] = gg.high.max()
        ctx[f"{nm}l" if nm != "pre" else "pre_l"] = gg.low.min()
    ctx["onr"] = ctx.onh - ctx.onl
    ctx = ctx.rename(columns={"ash": "ash", "asl": "asl", "lnh": "lnh", "lnl": "lnl"})
    print(f"{sym}: ETH context {len(ctx)} sessions, offset {off:+.2f}")
    return rth_df.join(ctx, on="day")
