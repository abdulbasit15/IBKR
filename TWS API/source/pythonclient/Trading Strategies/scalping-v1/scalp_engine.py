"""Bar-based scalping backtest engine for MNQ / MES / MGC on 5-min RTH bars (09:30-16:00 ET).

Data : Historical Data/data/{SYM}_cont_5mins_rth.csv  (+ {SYM}_5m_recent.csv appended, roll-offset aligned)
Rules: signal on bar CLOSE -> market entry at NEXT bar open (+1 tick slippage), or optional stop-entry
       order (sig["entry"], valid sig["expire"] bars; cancelled if the stop is hit first).
       Stop = stop-market (+1 tick slippage, gap-through filled at the open).
       Target = limit; only filled if the bar trades THROUGH it by 1 tick.
       Stop & target touched in the same bar -> assume the STOP (conservative).
       Flat by the 15:55 bar close. One position at a time per strategy.
Costs: commission per side per contract (IBKR micro approx) + slippage above.
"""
import os
import numpy as np
import pandas as pd

DATA_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                         "..", "Historical Data", "data"))
SPECS = {
    "MNQ": dict(pv=2.0, tick=0.25, comm=0.62),
    "MES": dict(pv=5.0, tick=0.25, comm=0.62),
    "MGC": dict(pv=10.0, tick=0.10, comm=0.80),
}
TZ = "America/New_York"
START = pd.Timestamp("2025-09-02").date()   # bars before ~late Aug 2025 are forward-fill padded (see data notes)


# ----------------------------------------------------------------------------- data
def _read(path):
    df = pd.read_csv(path)
    df["date"] = pd.to_datetime(df["date"], utc=True)
    return df


def load_rth(sym):
    a = _read(os.path.join(DATA_DIR, f"{sym}_cont_5mins_rth.csv"))
    rp = os.path.join(DATA_DIR, f"{sym}_5m_recent.csv")
    if os.path.exists(rp):
        b = _read(rp)
        m = a.merge(b, on="date", suffixes=("_a", "_b"))
        off = float((m.close_b - m.close_a).median()) if len(m) else 0.0  # back-adjust roll gap
        if off:
            for k in ("open", "high", "low", "close"):
                a[k] = a[k] + off
        a = pd.concat([a[a.date < b.date.min()], b])
    df = a.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)
    df["date"] = df["date"].dt.tz_convert(TZ)
    df["tm"] = df.date.dt.hour * 60 + df.date.dt.minute
    df = df[(df.tm >= 570) & (df.tm <= 955)].copy()          # 09:30 .. 15:55 bar starts
    df["day"] = df.date.dt.date
    # keep only real days: opens 09:30, >=40 bars, <3% flat padded bars
    g = df.groupby("day").agg(n=("tm", "size"), first=("tm", "min"))
    flat = (df.high == df.low).groupby(df.day).mean()
    good = g[(g.n >= 40) & (g["first"] == 570)].index.intersection(flat[flat <= 0.03].index)
    df = df[df.day.isin(good) & (df.day >= START)].reset_index(drop=True)
    return df


# ----------------------------------------------------------------------------- indicators
def ema(x, n):
    return pd.Series(x).ewm(span=n, adjust=False).mean().values


def rma(x, n):
    return pd.Series(x).ewm(alpha=1.0 / n, adjust=False).mean().values


def add_indicators(df):
    o, h, l, c, v = (df[k].values for k in ("open", "high", "low", "close", "volume"))
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc)))
    df["atr"] = rma(tr, 14)
    for n in (9, 20, 50):
        df[f"ema{n}"] = ema(c, n)
    d = np.diff(c, prepend=c[0])
    up, dn = rma(np.maximum(d, 0), 2), rma(np.maximum(-d, 0), 2)
    df["rsi2"] = 100 - 100 / (1 + up / np.where(dn == 0, 1e-12, dn))
    s = pd.Series(c)
    mid, sd = s.rolling(20).mean(), s.rolling(20).std(ddof=0)
    df["bb_mid"], df["bb_up"], df["bb_lo"] = mid.values, (mid + 2 * sd).values, (mid - 2 * sd).values
    bbw = (4 * sd / mid)
    df["bbw_rank"] = bbw.rolling(120).rank(pct=True).values
    # session VWAP + volume-weighted std bands
    tp = (h + l + c) / 3.0
    vv = np.where(v <= 0, 1.0, v)
    g = df.day
    cv = pd.Series(vv).groupby(g.values).cumsum().values
    cpv = pd.Series(tp * vv).groupby(g.values).cumsum().values
    cp2v = pd.Series(tp * tp * vv).groupby(g.values).cumsum().values
    vw = cpv / cv
    df["vwap"] = vw
    df["vsd"] = np.sqrt(np.maximum(cp2v / cv - vw * vw, 0))
    # noise-band sigma (Zarattini et al. 2024): 14-day mean of |close_t / day_open - 1| at the same time-of-day
    dopen = df.groupby("day").open.transform("first").values
    mv = pd.Series(np.abs(c / dopen - 1.0))
    df["nsig"] = mv.groupby(df.tm.values).transform(lambda x: x.shift(1).rolling(14, min_periods=10).mean()).values
    # daily context (prior RTH day high/low/close, 14-day avg RTH range)
    dd = df.groupby("day").agg(dh=("high", "max"), dl=("low", "min"), dc=("close", "last"), do=("open", "first"))
    dd["datr"] = (dd.dh - dd.dl).rolling(14, min_periods=5).mean().shift(1)
    dd["pdh"], dd["pdl"], dd["pdc"] = dd.dh.shift(1), dd.dl.shift(1), dd.dc.shift(1)
    df = df.join(dd[["datr", "pdh", "pdl", "pdc"]], on="day")
    return df


# ----------------------------------------------------------------------------- simulator
class Day:
    """Per-day array view handed to strategies."""
    def __init__(self, g):
        for k in g.columns:
            setattr(self, k, g[k].values)
        self.n = len(g)
        self.date = g["day"].iloc[0]
        self.state = {}


def simulate(sym, df, strat, params, slip_ticks=1):
    sp = SPECS[sym]
    tick, pv, comm = sp["tick"], sp["pv"], sp["comm"]
    slip = tick * slip_ticks
    trades = []
    strat.reset()
    for day, g in df.groupby("day", sort=True):
        D = Day(g)
        if np.isnan(D.datr[0]):
            continue
        strat.start_day(D, params)
        i = 0
        while i < D.n - 1:
            sig = strat.signal(D, i, params)
            if not sig or D.tm[i + 1] > params.get("last_entry", 930):
                i += 1
                continue
            d = sig["dir"]
            stop = sig["stop"]
            k0 = i + 1                                 # entry bar
            if sig.get("entry") is not None:           # pending order at sig["entry"], valid sig["expire"] bars
                lvl, k0 = sig["entry"], None
                lim = sig.get("etype", "stop") == "limit"
                cancel = sig.get("cancel")              # limit only: cancel if price runs to this level unfilled
                for k in range(i + 1, min(i + 1 + sig.get("expire", 1), D.n)):
                    if D.tm[k] > params.get("last_entry", 930):
                        break
                    if lim:
                        hit = (D.low[k] <= lvl - tick) if d == 1 else (D.high[k] >= lvl + tick)
                    else:
                        hit = (D.high[k] >= lvl) if d == 1 else (D.low[k] <= lvl)
                    if hit:
                        k0 = k
                        break
                    if (D.low[k] <= stop) if d == 1 else (D.high[k] >= stop):
                        break                          # invalidated before trigger
                    if lim and cancel is not None and ((D.high[k] >= cancel) if d == 1 else (D.low[k] <= cancel)):
                        break
                if k0 is None:
                    i += 1
                    continue
                if lim:
                    e = min(D.open[k0], lvl) if d == 1 else max(D.open[k0], lvl)
                else:
                    e = (max(D.open[k0], lvl) if d == 1 else min(D.open[k0], lvl)) + d * slip
                # triggered inside the bar (not at its open) -> the part of the bar before the fill is unknown
                intrabar = ((D.open[k0] - lvl) * d > 1e-9) if lim else ((lvl - D.open[k0]) * d > 1e-9)
            else:
                e = D.open[k0] + d * slip
                intrabar = False
            risk = (e - stop) * d
            if risk < 4 * tick:                       # gap past stop / degenerate risk
                i = max(i + 1, k0 if sig.get("entry") is not None else i + 1)
                continue
            tgt = sig.get("tgt")
            if tgt is None and sig.get("r"):
                tgt = e + d * sig["r"] * risk
            if tgt is not None and (tgt - e) * d <= tick:
                i += 1
                continue
            maxb = sig.get("max_bars", 999)
            j = k0
            x, why = None, None
            while True:
                # on an intrabar-triggered entry bar the target only counts if the bar CLOSES through it
                th_hi = D.close[j] if (intrabar and j == k0) else D.high[j]
                th_lo = D.close[j] if (intrabar and j == k0) else D.low[j]
                if d == 1 and D.low[j] <= stop:
                    x, why = min(stop, D.open[j]) - slip, "stop"
                elif d == -1 and D.high[j] >= stop:
                    x, why = max(stop, D.open[j]) + slip, "stop"
                elif tgt is not None and d == 1 and th_hi >= tgt + tick:
                    x, why = max(tgt, D.open[j]) if j > k0 or not intrabar else tgt, "tgt"
                elif tgt is not None and d == -1 and th_lo <= tgt - tick:
                    x, why = min(tgt, D.open[j]) if j > k0 or not intrabar else tgt, "tgt"
                elif strat.exit(D, j, d, params, sig):
                    x, why = D.close[j] - d * slip, "rule"
                elif j - (k0 - 1) >= maxb:
                    x, why = D.close[j] - d * slip, "time"
                elif sig.get("exit_tm") is not None and D.tm[j] + 5 >= sig["exit_tm"]:
                    x, why = D.close[j] - d * slip, "window"     # flat at an absolute clock time
                elif j == D.n - 1:
                    x, why = D.close[j] - d * slip, "eod"
                if x is not None:
                    break
                j += 1
            pts = (x - e) * d
            net = pts * pv - 2 * comm
            trades.append(dict(day=day, sym=sym, dir=d, et=D.tm[k0], xt=D.tm[j], entry=e, exit=x,
                               risk=risk, pts=pts, net=net, r=net / (risk * pv), why=why, bars=j - k0 + 1))
            strat.on_trade(D, i, j, d, params)
            i = j            # next signal may form on the exit bar's close
    return pd.DataFrame(trades)


class Strategy:
    name = "base"
    grid = [{}]

    def reset(self):
        pass

    def start_day(self, D, p):
        D.state = {"n": 0}

    def signal(self, D, i, p):
        return None

    def exit(self, D, j, d, p, sig):
        return False

    def on_trade(self, D, i, j, d, p):
        D.state["n"] = D.state.get("n", 0) + 1


# ----------------------------------------------------------------------------- metrics
def metrics(t, days):
    ndays = len(days)
    if t is None or len(t) == 0:
        return dict(n=0, tpd=0, win=np.nan, avgR=np.nan, pf=np.nan, net=0, dd=0, sharpe=np.nan, posm=np.nan)
    w = t.net > 0
    gp, gl = t.net[w].sum(), -t.net[~w].sum()
    daily = t.groupby("day").net.sum().reindex(days, fill_value=0.0)
    eq = daily.cumsum()
    dd = float((eq.cummax().clip(lower=0) - eq).max())
    sharpe = daily.mean() / daily.std() * np.sqrt(252) if len(daily) > 2 and daily.std() > 0 else np.nan
    mon = t.assign(m=pd.to_datetime(t.day).dt.to_period("M")).groupby("m").net.sum()
    return dict(n=len(t), tpd=len(t) / ndays, win=w.mean(), avgR=t.r.mean(), pf=gp / gl if gl > 0 else np.inf,
                net=t.net.sum(), dd=dd, sharpe=sharpe, posm=(mon > 0).mean())
