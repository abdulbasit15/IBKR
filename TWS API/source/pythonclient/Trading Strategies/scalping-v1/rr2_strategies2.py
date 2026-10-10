"""2:1 RR candidates, research round 2 (2026-10-09). Same conventions as rr2_strategies.py:
structural stop, target = 2 x risk from the fill, flat at 16:00 unless noted."""
import numpy as np
import pandas as pd
from scalp_engine import Strategy
from rr2_strategies import _grid, _ok_dir, R


def add_context2(df):
    # 60-day noise sigma (Quantitativo found a longer lookback better than 14)
    dopen = df.groupby("day").open.transform("first").values
    mv = pd.Series(np.abs(df.close.values / dopen - 1.0))
    df["nsig60"] = mv.groupby(df.tm.values).transform(lambda x: x.shift(1).rolling(60, min_periods=30).mean()).values
    for nb in (24, 48):
        df[f"dch{nb}"] = df.high.rolling(nb).max().values
        df[f"dcl{nb}"] = df.low.rolling(nb).min().values
    return df


# K ----------------------------------------------------------------- Noise-area momentum, pure 2R exit
class Noise2R(Strategy):
    """Zarattini/Aziz/Barbon noise band, sigma_t = `lb`-day mean |close_t/open - 1| at that time of day.
    Checked on bars closing :00/:30 from 10:00. Long: close > max(open, prior close) x (1+sigma). Stop =
    the TIGHTER of band and VWAP (closest level still below price). Skip if risk < `mr` x 14-day avg range.
    Target 2R, no trailing exit, flat 16:00. Max `mx` trades/day."""
    name = "Noise2R"
    grid = _grid(lb=[14, 60], mr=[0.05, 0.10], mx=[1, 3], last_entry=[930], max_bars=[999])

    def signal(self, D, i, p):
        if D.state["n"] >= p["mx"]:
            return None
        t = D.tm[i] + 5
        if t < 600 or t % 30:
            return None
        sg = D.nsig[i] if p["lb"] == 14 else D.nsig60[i]
        if np.isnan(sg):
            return None
        ub, lb = max(D.open[0], D.pdc[0]) * (1 + sg), min(D.open[0], D.pdc[0]) * (1 - sg)
        c, vw = D.close[i], D.vwap[i]
        if c > ub:
            d, stop = 1, max(x for x in (ub, vw) if x < c) if min(ub, vw) < c else ub
        elif c < lb:
            d, stop = -1, min(x for x in (lb, vw) if x > c) if max(lb, vw) > c else lb
        else:
            return None
        if abs(c - stop) < p["mr"] * D.datr[0]:
            return None
        return dict(dir=d, stop=stop, r=R, max_bars=p["max_bars"])


# L ----------------------------------------------------------------- IB breakout confirmed by the 10:30-11:00 period
class IBConfirm(Strategy):
    """IB = 09:30-10:30, only when IB width < `nw` x 14-day avg range (9.9 = no filter). If the bar closing
    11:00 is beyond the IB edge, enter at the 11:00 open. Stop = tighter of IB midpoint or 0.5 x IB from
    the entry. Target 2R. Flat 16:00."""
    name = "IBConfirm"
    grid = _grid(nw=[0.5, 0.75, 9.9], dtf=[False, True], max_bars=[999], last_entry=[660])

    def signal(self, D, i, p):
        if D.tm[i] != 655 or D.state["n"]:
            return None
        k = D.tm < 630
        hi, lo = D.high[k].max(), D.low[k].min()
        w = hi - lo
        if w > p["nw"] * D.datr[0]:
            return None
        mid, c = (hi + lo) / 2, D.close[i]
        for d, edge in ((1, hi), (-1, lo)):
            if (c - edge) * d > 0 and _ok_dir(D, d, p):
                stop = mid if abs(c - mid) < 0.5 * w else c - d * 0.5 * w
                return dict(dir=d, stop=stop, r=R, max_bars=p["max_bars"])
        return None


# M ----------------------------------------------------------------- IB shallow-extension retest & go
class IBRetest(Strategy):
    """After the IB (09:30-10:30) breaks and extends at least `lo_x` but no more than 0.25 x IB beyond the
    edge within 30 min of the break, place a LIMIT at the IB edge for the first retest (valid 90 min,
    before 12:00). Stop = edge -/+ `stopf` x IB. Target 2R. Cancelled if price runs past the would-be
    target region (edge + 0.5 x IB) before filling."""
    name = "IBRetest"
    grid = _grid(lo_x=[0.1, 0.0], stopf=[0.35, 0.25], dtf=[False, True], max_bars=[999], last_entry=[720])

    def start_day(self, D, p):
        D.state = {"n": 0, "brk": 0, "t0": None, "done": False}

    def signal(self, D, i, p):
        s = D.state
        if s["n"] or s["done"] or D.tm[i] < 625:
            return None
        k = D.tm < 630
        hi, lo = D.high[k].max(), D.low[k].min()
        w = max(hi - lo, 1e-9)
        if s["brk"] == 0:
            for d, edge in ((1, hi), (-1, lo)):
                if (D.close[i] - edge) * d > 0:
                    s["brk"], s["t0"] = d, D.tm[i]
            if s["brk"] == 0:
                return None
        d = s["brk"]
        edge = hi if d == 1 else lo
        ext = ((D.high[k.argmin():i + 1].max() - hi) if d == 1 else (lo - D.low[k.argmin():i + 1].min())) / w
        if ext > 0.25 or D.tm[i] - s["t0"] > 30:
            s["done"] = True
            return None
        if ext >= p["lo_x"] and _ok_dir(D, d, p):
            s["done"] = True
            return dict(dir=d, stop=edge - d * p["stopf"] * w, entry=edge, etype="limit", expire=18, r=R,
                        cancel=edge + d * 0.5 * w, max_bars=p["max_bars"])
        return None


# N ----------------------------------------------------------------- ORB second break (double break)
class ORB2nd(Strategy):
    """OR = first `orm` minutes. First 5-min close beyond one edge, then a close back inside the OR,
    then the first close beyond the OPPOSITE edge (before 12:00) -> enter next open that way.
    Stop = extreme of the failed first break, capped at 1 x OR from the signal close. Target 2R."""
    name = "ORB2nd"
    grid = _grid(orm=[15, 30], dtf=[False, True], max_bars=[999], last_entry=[720])

    def start_day(self, D, p):
        k = p["orm"] // 5
        D.state = {"n": 0, "k": k, "hi": D.high[:k].max(), "lo": D.low[:k].min(), "first": 0, "back": False, "xt": None}

    def signal(self, D, i, p):
        s = D.state
        if s["n"] or i < s["k"]:
            return None
        hi, lo, c = s["hi"], s["lo"], D.close[i]
        w = hi - lo
        if s["first"] == 0:
            if c > hi:
                s["first"], s["xt"] = 1, D.high[i]
            elif c < lo:
                s["first"], s["xt"] = -1, D.low[i]
            return None
        f = s["first"]
        s["xt"] = max(s["xt"], D.high[i]) if f == 1 else min(s["xt"], D.low[i])
        if not s["back"]:
            s["back"] = lo <= c <= hi
            return None
        d = -f
        edge = hi if d == 1 else lo
        if (c - edge) * d > 0:
            s["n"] = 1
            if not _ok_dir(D, d, p):
                return None
            stop = s["xt"] if abs(c - s["xt"]) <= w else c - d * w
            return dict(dir=d, stop=stop, r=R, max_bars=p["max_bars"])
        return None


# O ----------------------------------------------------------------- Wide opening range continuation
class WideOR(Strategy):
    """30-min OR width > `ww` x 14-day avg range. Trade only in the direction of the OR candle
    (09:55 bar close vs 09:30 open). First 5-min close beyond that edge before 12:00. Stop = OR mid.
    Target 2R."""
    name = "WideOR"
    grid = _grid(ww=[0.4, 0.5, 0.6], max_bars=[999], last_entry=[720])

    def start_day(self, D, p):
        hi, lo = D.high[:6].max(), D.low[:6].min()
        D.state = {"n": 0, "hi": hi, "lo": lo, "d": int(np.sign(D.close[5] - D.open[0])),
                   "ok": (hi - lo) > p["ww"] * D.datr[0]}

    def signal(self, D, i, p):
        s = D.state
        if s["n"] or i < 6 or not s["ok"] or s["d"] == 0:
            return None
        d, edge = s["d"], (s["hi"] if s["d"] == 1 else s["lo"])
        if (D.close[i] - edge) * d > 0:
            s["n"] = 1
            return dict(dir=d, stop=(s["hi"] + s["lo"]) / 2, r=R, max_bars=p["max_bars"])
        return None


# P ----------------------------------------------------------------- ORB with overnight / London midpoint direction filter
class ORBMid(Strategy):
    """`orm`-minute OR. Longs only if the 09:30 open is above BOTH the overnight (18:00-09:30) midpoint and
    the London (03:00-08:00) midpoint; shorts only if below both. First 5-min close beyond the allowed edge
    before 12:00. Stop = OR midpoint ('mid') or breakout-bar extreme ('bar'). Target 2R."""
    name = "ORBMid"
    grid = _grid(orm=[15, 30], stop=["mid", "bar"], max_bars=[999], last_entry=[720])

    def start_day(self, D, p):
        k = p["orm"] // 5
        o, d = D.open[0], 0
        if not np.isnan(D.onh[0]) and not np.isnan(D.lnh[0]):
            onm, lnm = (D.onh[0] + D.onl[0]) / 2, (D.lnh[0] + D.lnl[0]) / 2
            d = 1 if (o > onm and o > lnm) else (-1 if (o < onm and o < lnm) else 0)
        D.state = {"n": 0, "k": k, "hi": D.high[:k].max(), "lo": D.low[:k].min(), "d": d}

    def signal(self, D, i, p):
        s = D.state
        if s["n"] or i < s["k"] or s["d"] == 0:
            return None
        d, edge = s["d"], (s["hi"] if s["d"] == 1 else s["lo"])
        if (D.close[i] - edge) * d > 0:
            s["n"] = 1
            stop = (s["hi"] + s["lo"]) / 2 if p["stop"] == "mid" else (D.low[i] if d == 1 else D.high[i])
            return dict(dir=d, stop=stop, r=R, max_bars=p["max_bars"])
        return None


# Q ----------------------------------------------------------------- Intraday Donchian breakout (Unger-style)
class Donchian(Strategy):
    """Stop-entry 1 tick beyond the highest high / lowest low of the prior `nb` 5-min bars (channel spans
    prior days), 09:45-13:30, on the side nearer to price (or the daily-trend side if dtf). Stop = `k` x
    ATR(5m) x sqrt(12) (~k x 60-min ATR). Target 2R. Flat at `flat` (13:30 or 16:00). Max 2 trades/day."""
    name = "Donchian"
    grid = _grid(nb=[24, 48], k=[0.5, 1.0], dtf=[False, True], flat=[810, 955], last_entry=[810])

    def signal(self, D, i, p):
        if D.state["n"] >= 2 or D.tm[i] < 585:
            return None
        hh, ll = getattr(D, f"dch{p['nb']}")[i], getattr(D, f"dcl{p['nb']}")[i]
        if np.isnan(hh):
            return None
        c, tk = D.close[i], D.tick[0]
        risk = p["k"] * D.atr[i] * 12 ** 0.5
        mb = max(1, (p["flat"] - D.tm[i]) // 5)
        if p["dtf"]:
            d = int(D.dtrend[0])
        else:
            d = 1 if (hh - c) <= (c - ll) else -1
        if d == 1 and c < hh:
            return dict(dir=1, stop=hh + tk - risk, entry=hh + tk, expire=1, r=R, max_bars=mb)
        if d == -1 and c > ll:
            return dict(dir=-1, stop=ll - tk + risk, entry=ll - tk, expire=1, r=R, max_bars=mb)
        return None


ALL = [Noise2R(), IBConfirm(), IBRetest(), ORB2nd(), WideOR(), ORBMid(), Donchian()]
