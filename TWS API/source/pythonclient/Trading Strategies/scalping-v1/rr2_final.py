"""Final robustness study for the winning 2:1 family: Initial-Balance breakout in the daily-trend direction.

IBTrend params
  trend : daily-trend filter: 'e10'/'e20'/'e50' = prior RTH close vs that EMA of RTH closes;
          'none' = both sides; 'long' = longs only (control: is the filter just bull-market beta?)
  entry : 'first'   = first 5-min close beyond the IB (09:30-10:30), entries until 12:00
          'confirm' = only if the bar closing 11:00 is beyond the IB -> enter 11:00 open
  stop  : 'mid' = IB midpoint ; 'cap' = tighter of IB midpoint and 0.5 x IB from the signal close
  nw    : skip days whose IB is wider than nw x 14-day avg RTH range (9.9 = off)
Target = 2R from the fill, else flat 16:00. One trade per day; if the FIRST IB break is against the
trend, no trade that day.
Writes results/rr2_final.json for the report."""
import json
import os
import numpy as np
import pandas as pd
from scalp_engine import simulate, metrics, Strategy, SPECS
from rr2_run import load
from rr2_strategies import _grid

SPLIT = pd.Timestamp("2026-05-01").date()
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
SYMS = ["MNQ", "MES", "MGC"]
CENTER = dict(trend="e20", entry="confirm", stop="mid", nw=9.9)


def add_trends(df):
    dd = df.groupby("day").agg(dc=("close", "last"))
    for n in (10, 20, 50):
        dd[f"tr{n}"] = np.sign(dd.dc - dd.dc.ewm(span=n, adjust=False).mean()).shift(1)
    return df.join(dd[["tr10", "tr20", "tr50"]], on="day")


class IBTrend(Strategy):
    name = "IBTrend"
    grid = _grid(trend=["e10", "e20", "e50", "none", "long"], entry=["first", "confirm"], stop=["mid", "cap"], nw=[9.9, 0.75])

    def start_day(self, D, p):
        k = D.tm < 630
        hi, lo = D.high[k].max(), D.low[k].min()
        tr = {"e10": D.tr10[0], "e20": D.tr20[0], "e50": D.tr50[0], "none": 0, "long": 1}[p["trend"]]
        D.state = {"n": 0, "hi": hi, "lo": lo, "tr": tr, "ok": (hi - lo) <= p["nw"] * D.datr[0] and not np.isnan(tr)}
        p["last_entry"] = 720 if p["entry"] == "first" else 660
        p["max_bars"] = 999

    def signal(self, D, i, p):
        s = D.state
        if s["n"] or not s["ok"] or D.tm[i] < 625:
            return None
        if p["entry"] == "confirm" and D.tm[i] != 655:
            return None
        hi, lo, c = s["hi"], s["lo"], D.close[i]
        w, mid = hi - lo, (hi + lo) / 2
        for d, edge in ((1, hi), (-1, lo)):
            if (c - edge) * d > 0:
                s["n"] = 1                                  # first break decides the day
                if s["tr"] != 0 and s["tr"] != d:
                    return None
                stop = mid
                if p["stop"] == "cap" and abs(c - mid) > 0.5 * w:
                    stop = c - d * 0.5 * w
                return dict(dir=d, stop=stop, r=2.0, max_bars=999)
        return None

    def on_trade(self, D, i, j, d, p):
        D.state["n"] = 1


def pf(x):
    return float(x.net[x.net > 0].sum() / -x.net[x.net < 0].sum()) if (x.net < 0).any() else float("inf")


def summary(t, days):
    m = metrics(t, days)
    out = {k: (None if pd.isna(v) else float(v)) for k, v in m.items()}
    out["tgt"] = float((t.why == "tgt").mean()) if len(t) else None
    out["stop_rate"] = float((t.why == "stop").mean()) if len(t) else None
    return out


def main():
    data = {s: add_trends(load(s)) for s in SYMS}
    days = {s: sorted(data[s].day.unique()) for s in SYMS}
    st = IBTrend()
    grid_rows, center = [], {}
    for p in st.grid:
        key = "|".join(f"{k}={v}" for k, v in p.items())
        pooled = []
        row = dict(p)
        for s in SYMS:
            t = simulate(s, data[s], st, dict(p))
            pooled.append(t)
            isd = [d for d in days[s] if d < SPLIT]
            row[f"{s}_n"], row[f"{s}_pf"], row[f"{s}_net"] = len(t), pf(t), float(t.net.sum())
            row[f"{s}_isR"] = float(t[t.day < SPLIT].r.mean())
            row[f"{s}_oosR"] = float(t[t.day >= SPLIT].r.mean())
        a = pd.concat(pooled)
        row["pooled_n"], row["pooled_R"] = len(a), float(a.r.mean())
        row["t"] = float(a.r.mean() / a.r.std() * np.sqrt(len(a)))
        row["pooled_net"] = float(a.net.sum())
        grid_rows.append(row)
    g = pd.DataFrame(grid_rows)
    g.to_csv(os.path.join(OUT, "rr2_final_grid.csv"), index=False)
    pd.set_option("display.width", 260)
    cols = ["trend", "entry", "stop", "nw", "pooled_n", "pooled_R", "t", "pooled_net"] + [f"{s}_{m}" for s in SYMS for m in ("pf", "isR", "oosR")]
    print(g[cols].sort_values("pooled_R", ascending=False).round(3).to_string(index=False))

    # detailed run of the centre config (+ 2-tick slippage stress)
    for s in SYMS:
        t = simulate(s, data[s], st, dict(CENTER))
        t2 = simulate(s, data[s], st, dict(CENTER), slip_ticks=2)
        isd, osd = [d for d in days[s] if d < SPLIT], [d for d in days[s] if d >= SPLIT]
        center[s] = dict(
            all=summary(t, days[s]), IS=summary(t[t.day < SPLIT], isd), OOS=summary(t[t.day >= SPLIT], osd),
            slip2=summary(t2, days[s]), long=summary(t[t.dir == 1], days[s]), short=summary(t[t.dir == -1], days[s]),
            avg_risk_pts=float(t.risk.mean()), avg_risk_usd=float(t.risk.mean() * SPECS[s]["pv"]),
            avg_hold_min=float(t.bars.mean() * 5),
            monthly={str(k): float(v) for k, v in t.assign(m=pd.to_datetime(t.day).dt.to_period("M")).groupby("m").net.sum().items()},
            equity=[[str(d), float(v)] for d, v in t.groupby("day").net.sum().reindex(days[s], fill_value=0).cumsum().items()],
            trades=t.assign(day=t.day.astype(str)).to_dict("records"),
        )
        c = center[s]
        print(f"CENTER {s}: n={c['all']['n']:.0f} win={c['all']['win']:.0%} 2R-hit={c['all']['tgt']:.0%} PF={c['all']['pf']:.2f} "
              f"net=${c['all']['net']:.0f} DD=${c['all']['dd']:.0f} | IS PF {c['IS']['pf']:.2f} OOS PF {c['OOS']['pf']:.2f} "
              f"| 2-tick PF {c['slip2']['pf']:.2f} | L ${c['long']['net']:.0f} S ${c['short']['net']:.0f} | risk {c['avg_risk_pts']:.1f}pt (${c['avg_risk_usd']:.0f})")
    json.dump(dict(center=CENTER, sym=center, split=str(SPLIT),
                   meta={s: [str(days[s][0]), str(days[s][-1]), len(days[s])] for s in SYMS}),
              open(os.path.join(OUT, "rr2_final.json"), "w"), default=str)


if __name__ == "__main__":
    main()
