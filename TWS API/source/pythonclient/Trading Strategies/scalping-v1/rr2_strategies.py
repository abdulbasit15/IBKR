"""2:1 reward-to-risk scalping candidates. Every trade: structural stop, fixed target = 2 x risk
(measured from the actual fill), otherwise time stop / flat at 16:00. 5-min RTH bars.

Shared filter `dtf` (daily-trend filter): only trade in the direction of the daily trend, defined as
prior RTH close vs the 20-day EMA of RTH closes (known before the open -> no lookahead).
"""
import itertools
import numpy as np
import pandas as pd
from scalp_engine import Strategy

R = 2.0


def _grid(**kw):
    keys = list(kw)
    return [dict(zip(keys, vals)) for vals in itertools.product(*kw.values())]


def add_context(df):
    dd = df.groupby("day").agg(dc=("close", "last"))
    e20 = dd.dc.ewm(span=20, adjust=False).mean()
    dd["dtrend"] = np.sign(dd.dc - e20).shift(1)          # yesterday's close vs yesterday's EMA20
    df = df.join(dd[["dtrend"]], on="day")
    df["dtrend"] = df["dtrend"].fillna(0)
    return df


def _ok_dir(D, d, p):
    return (not p.get("dtf")) or D.dtrend[0] == d


# A ----------------------------------------------------------------- Initial Balance breakout, 2R
class IB2R(Strategy):
    """IB = first `ib` minutes. First 5-min close beyond the IB -> enter next open.
    Stop = IB midpoint ('mid') or opposite IB side ('opp'). Target 2R. narrow: IB < 20-day median IB.
    Skip IB wider than 0.6 x 14-day avg range. Entries until 12:00. One trade/day."""
    name = "IB2R"
    grid = _grid(ib=[30, 60], stop=["mid", "opp"], narrow=[False, True], dtf=[False, True], max_bars=[999])

    def reset(self):
        self.hist = []

    def start_day(self, D, p):
        k = p["ib"] // 5
        hi, lo = D.high[:k].max(), D.low[:k].min()
        med = np.median(self.hist[-20:]) if len(self.hist) >= 10 else np.inf
        self.hist.append(hi - lo)
        D.state = {"n": 0, "k": k, "hi": hi, "lo": lo, "ok": ((not p["narrow"]) or (hi - lo) < med) and (hi - lo) <= 0.6 * D.datr[0]}
        p["last_entry"] = 720

    def signal(self, D, i, p):
        s = D.state
        if s["n"] or i < s["k"] or not s["ok"]:
            return None
        hi, lo = s["hi"], s["lo"]
        mid = (hi + lo) / 2
        for d, edge, opp in ((1, hi, lo), (-1, lo, hi)):
            if (D.close[i] - edge) * d > 0:
                if not _ok_dir(D, d, p):
                    s["n"] = 1          # first break was against the trend -> done for the day
                    return None
                return dict(dir=d, stop=mid if p["stop"] == "mid" else opp, r=R, max_bars=p["max_bars"])
        return None


# B ----------------------------------------------------------------- Opening-range break, retest, go
class ORRetest(Strategy):
    """OR = first `orm` minutes. After a 5-min close beyond the OR edge, wait for price to come back
    within `tol` x ATR of the edge without closing back through the OR midpoint (the retest). Then a
    stop-entry 1 tick beyond the retest bar's extreme (valid 3 bars). Stop = retest extreme -/+ 0.1 ATR.
    Target 2R. Entries 09:45-12:00. One trade/day."""
    name = "ORRetest"
    grid = _grid(orm=[15, 30], tol=[0.1, 0.3], dtf=[False, True], max_bars=[999])

    def start_day(self, D, p):
        k = p["orm"] // 5
        D.state = {"n": 0, "k": k, "hi": D.high[:k].max(), "lo": D.low[:k].min(), "brk": 0, "dead": False}
        p["last_entry"] = 720

    def signal(self, D, i, p):
        s = D.state
        if s["n"] or s["dead"] or i < s["k"]:
            return None
        hi, lo, a = s["hi"], s["lo"], D.atr[i]
        mid = (hi + lo) / 2
        if (hi - lo) > 0.6 * D.datr[0]:
            return None
        if s["brk"] == 0:
            if D.close[i] > hi:
                s["brk"] = 1 if _ok_dir(D, 1, p) else 0
                s["dead"] = s["brk"] == 0
            elif D.close[i] < lo:
                s["brk"] = -1 if _ok_dir(D, -1, p) else 0
                s["dead"] = s["brk"] == 0
            return None
        d, edge = s["brk"], (hi if s["brk"] == 1 else lo)
        if (D.close[i] - mid) * d < 0:          # failed back through the OR midpoint
            s["dead"] = True
            return None
        ext = D.low[i] if d == 1 else D.high[i]
        if abs(ext - edge) <= p["tol"] * a or (ext - edge) * d < 0:   # retest touched the edge zone
            tick = D.tick[0]
            entry = (D.high[i] + tick) if d == 1 else (D.low[i] - tick)
            stop = ext - d * 0.1 * a
            return dict(dir=d, stop=stop, entry=entry, expire=3, r=R, max_bars=p["max_bars"])
        return None


# C ----------------------------------------------------------------- Open-drive trend day, first pullback
class OpenDrive(Strategy):
    """Trend-day detection at 10:00: |10:00 close - open| >= k x 14-day avg range AND close in the outer
    30% of the 09:30-10:00 range. Then the first pullback bar whose low (high for shorts) touches EMA9
    or VWAP (`pb`) -> stop-entry 1 tick beyond that bar (valid 3 bars). Stop = pullback low - 0.1 ATR.
    Target 2R. Entries 10:00-12:00. One trade/day."""
    name = "OpenDrive"
    grid = _grid(k=[0.25, 0.4], pb=["ema9", "vwap"], dtf=[False, True], max_bars=[999])

    def start_day(self, D, p):
        D.state = {"n": 0, "d": None}
        p["last_entry"] = 720

    def signal(self, D, i, p):
        s = D.state
        if s["n"]:
            return None
        if D.tm[i] == 595:                      # bar closing 10:00
            hi, lo = D.high[:i + 1].max(), D.low[:i + 1].min()
            mv = D.close[i] - D.open[0]
            pos = (D.close[i] - lo) / max(hi - lo, 1e-9)
            if abs(mv) >= p["k"] * D.datr[0]:
                d = 1 if mv > 0 else -1
                if (d == 1 and pos >= 0.7) or (d == -1 and pos <= 0.3):
                    s["d"] = d if _ok_dir(D, d, p) else None
            return None
        if s["d"] is None or D.tm[i] < 600:
            return None
        d, a = s["d"], D.atr[i]
        lvl = D.ema9[i] if p["pb"] == "ema9" else D.vwap[i]
        if (d == 1 and D.low[i] <= lvl and D.close[i] > D.vwap[i]) or (d == -1 and D.high[i] >= lvl and D.close[i] < D.vwap[i]):
            tick = D.tick[0]
            entry = (D.high[i] + tick) if d == 1 else (D.low[i] - tick)
            stop = (D.low[i] if d == 1 else D.high[i]) - d * 0.1 * a
            return dict(dir=d, stop=stop, entry=entry, expire=3, r=R, max_bars=p["max_bars"])
        return None


# D ----------------------------------------------------------------- Al Brooks High-2 / Low-2 pullback
class H2L2(Strategy):
    """Trend: EMA20 rising over 6 bars, close above EMA20 and VWAP at the setup (mirror for shorts).
    In a pullback from the session's swing high, count 'H' bars (high > prior high). After H1, when a
    bar makes a lower high, place a stop-entry 1 tick above it (the H2 trigger). Stop = pullback low
    - 1 tick; skip if risk > `maxr` x ATR. Target 2R. Entries 10:00-15:00, max 3/day."""
    name = "H2L2"
    grid = _grid(maxr=[1.5, 3.0], dtf=[False, True], max_bars=[24, 999], last_entry=[900])

    def start_day(self, D, p):
        D.state = {"n": 0, "L": dict(hh=-np.inf, cnt=0, plo=np.inf), "S": dict(ll=np.inf, cnt=0, phi=-np.inf)}

    def signal(self, D, i, p):
        if D.state["n"] >= 3 or i < 6:
            return None
        h, l, c, a = D.high, D.low, D.close, D.atr[i]
        tick = 0.25 if c[i] > 1000 else 0.1
        L, S = D.state["L"], D.state["S"]
        # long side bookkeeping
        if h[i] > L["hh"]:
            L.update(hh=h[i], cnt=0, plo=np.inf)
        else:
            L["plo"] = min(L["plo"], l[i])
            if h[i] > h[i - 1]:
                L["cnt"] += 1
        if l[i] < S["ll"]:
            S.update(ll=l[i], cnt=0, phi=-np.inf)
        else:
            S["phi"] = max(S["phi"], h[i])
            if l[i] < l[i - 1]:
                S["cnt"] += 1
        if D.tm[i] < 600:
            return None
        up = D.ema20[i] > D.ema20[i - 6] and c[i] > D.ema20[i] and c[i] > D.vwap[i]
        dn = D.ema20[i] < D.ema20[i - 6] and c[i] < D.ema20[i] and c[i] < D.vwap[i]
        if up and _ok_dir(D, 1, p) and L["cnt"] == 1 and h[i] <= h[i - 1] and np.isfinite(L["plo"]):
            stop = L["plo"] - tick
            if (h[i] + tick - stop) <= p["maxr"] * a:
                return dict(dir=1, stop=stop, entry=h[i] + tick, expire=1, r=R, max_bars=p["max_bars"])
        if dn and _ok_dir(D, -1, p) and S["cnt"] == 1 and l[i] >= l[i - 1] and np.isfinite(S["phi"]):
            stop = S["phi"] + tick
            if (stop - (l[i] - tick)) <= p["maxr"] * a:
                return dict(dir=-1, stop=stop, entry=l[i] - tick, expire=1, r=R, max_bars=p["max_bars"])
        return None

    def on_trade(self, D, i, j, d, p):
        D.state["n"] += 1
        D.state["L"]["cnt"] = 2 if d == 1 else D.state["L"]["cnt"]     # consume the setup
        D.state["S"]["cnt"] = 2 if d == -1 else D.state["S"]["cnt"]


# E ----------------------------------------------------------------- ICT Silver Bullet (sweep -> FVG -> retrace)
class SilverBullet(Strategy):
    """Window 10:00-11:00 ET (setups from 09:50). Liquidity = high/low of 09:30-10:00 (`liq`='open30')
    or prior-day high/low ('pd'). After price sweeps one side, a 3-bar fair value gap forms in the
    OPPOSITE direction (bearish FVG after a high sweep: low[a] > high[c]). Limit entry at the FVG's near
    edge on retrace (valid until 11:00). Stop = sweep extreme + 1 tick. Target 2R. One trade/day."""
    name = "SilverBullet"
    grid = _grid(liq=["open30", "pd"], minfvg=[0.0, 0.25], dtf=[False, True], max_bars=[999])

    def start_day(self, D, p):
        D.state = {"n": 0, "swH": None, "swL": None}
        p["last_entry"] = 655

    def signal(self, D, i, p):
        s = D.state
        if s["n"] or i < 3:
            return None
        if p["liq"] == "open30":
            if D.tm[i] < 600:
                return None
            k = 6
            H, L = D.high[:k].max(), D.low[:k].min()
        else:
            H, L = D.pdh[0], D.pdl[0]
        if D.high[i] > H:
            s["swH"] = max(s["swH"] or -np.inf, D.high[i])
        if D.low[i] < L:
            s["swL"] = min(s["swL"] or np.inf, D.low[i])
        if D.tm[i] < 590 or D.tm[i] > 650:
            return None
        a = D.atr[i]
        tick = D.tick[0]
        h0, l0 = D.high[i - 2], D.low[i - 2]          # bar a ; bar c = i
        if s["swH"] is not None and l0 > D.high[i] and (l0 - D.high[i]) >= p["minfvg"] * a and _ok_dir(D, -1, p):
            stop = s["swH"] + tick
            return dict(dir=-1, stop=stop, entry=D.high[i], etype="limit", expire=12, r=R,
                        cancel=D.high[i] - 2 * (stop - D.high[i]), max_bars=p["max_bars"])
        if s["swL"] is not None and h0 < D.low[i] and (D.low[i] - h0) >= p["minfvg"] * a and _ok_dir(D, 1, p):
            stop = s["swL"] - tick
            return dict(dir=1, stop=stop, entry=D.low[i], etype="limit", expire=12, r=R,
                        cancel=D.low[i] + 2 * (D.low[i] - stop), max_bars=p["max_bars"])
        return None


# F ----------------------------------------------------------------- Inside-bar / NR breakout with trend
class InsideBar(Strategy):
    """Trend: close vs VWAP and EMA9 vs EMA20 agree. Signal bar = inside bar (high < prior high and
    low > prior low) whose range <= `nr` x ATR. Stop-entry 1 tick beyond the inside bar in trend
    direction (valid 2 bars). Stop = other side of the inside bar - 1 tick. Target 2R.
    Entries 10:00-15:00, max 3/day."""
    name = "InsideBar"
    grid = _grid(nr=[0.6, 1.0], dtf=[False, True], max_bars=[24, 999], last_entry=[900])

    def signal(self, D, i, p):
        if D.state["n"] >= 3 or D.tm[i] < 600 or i < 1:
            return None
        h, l, a = D.high, D.low, D.atr[i]
        if not (h[i] < h[i - 1] and l[i] > l[i - 1] and (h[i] - l[i]) <= p["nr"] * a):
            return None
        tick = D.tick[0]
        if D.close[i] > D.vwap[i] and D.ema9[i] > D.ema20[i] and _ok_dir(D, 1, p):
            return dict(dir=1, stop=l[i] - tick, entry=h[i] + tick, expire=2, r=R, max_bars=p["max_bars"])
        if D.close[i] < D.vwap[i] and D.ema9[i] < D.ema20[i] and _ok_dir(D, -1, p):
            return dict(dir=-1, stop=h[i] + tick, entry=l[i] - tick, expire=2, r=R, max_bars=p["max_bars"])
        return None


# G ----------------------------------------------------------------- Opening-candle momentum, 2R
class FirstBar2R(Strategy):
    """Direction of the 09:30-09:35 candle, enter at 09:35 open. Stop = first candle's opposite
    extreme ('bar') or s x 14-day avg range. Target 2R."""
    name = "FirstBar2R"
    grid = _grid(stop=["bar", 0.08, 0.12], dtf=[False, True], max_bars=[999], last_entry=[575])

    def signal(self, D, i, p):
        if i != 0 or D.state["n"] or D.close[0] == D.open[0]:
            return None
        d = 1 if D.close[0] > D.open[0] else -1
        if not _ok_dir(D, d, p):
            return None
        stop = (D.low[0] if d == 1 else D.high[0]) if p["stop"] == "bar" else D.open[1] - d * p["stop"] * D.datr[0]
        return dict(dir=d, stop=stop, r=R, max_bars=p["max_bars"])


ALL = [IB2R(), ORRetest(), OpenDrive(), H2L2(), SilverBullet(), InsideBar(), FirstBar2R()]


# H ----------------------------------------------------------------- Overnight-range breakout (needs ETH context)
class ONBreak(Strategy):
    """Overnight range (18:00-09:30) narrower than `nar` x 14-day avg RTH range. First 5-min close
    beyond ONH (long) / ONL (short) between 09:35 and 11:30. Stop: breakout bar's opposite extreme
    ('bar') or k x ATR ('atr'). Target 2R. One trade/day."""
    name = "ONBreak"
    grid = _grid(nar=[0.5, 1.0], stop=["bar", "atr"], dtf=[False, True], max_bars=[999])

    def start_day(self, D, p):
        ok = not np.isnan(D.onh[0]) and D.onr[0] <= p["nar"] * D.datr[0]
        D.state = {"n": 0, "ok": ok}
        p["last_entry"] = 690

    def signal(self, D, i, p):
        s = D.state
        if s["n"] or not s["ok"] or i < 1:
            return None
        for d, lvl in ((1, D.onh[0]), (-1, D.onl[0])):
            if (D.close[i] - lvl) * d > 0 and (D.close[i - 1] - lvl) * d <= 0:
                if not _ok_dir(D, d, p):
                    return None
                stop = (D.low[i] if d == 1 else D.high[i]) if p["stop"] == "bar" else D.close[i] - d * D.atr[i]
                return dict(dir=d, stop=stop, r=R, max_bars=p["max_bars"])
        return None


# I ----------------------------------------------------------------- Overnight high/low sweep & reclaim ("Judas swing")
class ONSweep(Strategy):
    """Between 09:30 and `until`, price trades beyond ONH (or ONL) and a 5-min bar closes back inside.
    Fade it: stop-entry 1 tick beyond the reclaim bar (valid 3 bars), stop = sweep extreme + 1 tick.
    Target 2R. One trade/day."""
    name = "ONSweep"
    grid = _grid(until=[630, 690], dtf=[False, True], max_bars=[999])

    def start_day(self, D, p):
        D.state = {"n": 0, "xh": None, "xl": None, "ok": not np.isnan(D.onh[0])}
        p["last_entry"] = p["until"] + 15

    def signal(self, D, i, p):
        s = D.state
        if s["n"] or not s["ok"] or D.tm[i] > p["until"]:
            return None
        H, L, tick = D.onh[0], D.onl[0], D.tick[0]
        if D.high[i] > H:
            s["xh"] = max(s["xh"] or -np.inf, D.high[i])
        if D.low[i] < L:
            s["xl"] = min(s["xl"] or np.inf, D.low[i])
        if s["xh"] is not None and D.close[i] < H and _ok_dir(D, -1, p):
            return dict(dir=-1, stop=s["xh"] + tick, entry=D.low[i] - tick, expire=3, r=R, max_bars=p["max_bars"])
        if s["xl"] is not None and D.close[i] > L and _ok_dir(D, 1, p):
            return dict(dir=1, stop=s["xl"] - tick, entry=D.high[i] + tick, expire=3, r=R, max_bars=p["max_bars"])
        return None


ALL += [ONBreak(), ONSweep()]


# J ----------------------------------------------------------------- Trend confluence (daily + session + intraday agree)
class Confluence(Strategy):
    """From 10:00, all must agree with the trade direction: daily trend (prior close vs 20d EMA),
    first-30-min return (10:00 close vs prior close), price vs prior close, price vs VWAP, 30-min momentum
    (close vs close 6 bars ago). Trigger: 'align' = first bar the full stack becomes true (re-arms after the
    stack breaks), 'pb' = while aligned, a bar dips to EMA9 and closes back beyond it in trend direction.
    Stop = k x ATR(14, 5m) from the fill. Target 2R. Max `mx` trades/day, entries until `last_entry`."""
    name = "Confluence"
    grid = _grid(trig=["align", "pb"], k=[1.0, 1.5], mx=[2, 4], last_entry=[900, 720], max_bars=[999])

    def start_day(self, D, p):
        D.state = {"n": 0, "prev": 0, "f30": None}

    def _stack(self, D, i):
        if D.tm[i] < 595 or i < 6:
            return 0
        if D.state["f30"] is None:
            k = np.where(D.tm == 595)[0]
            D.state["f30"] = np.sign(D.close[k[0]] - D.pdc[0]) if len(k) else 0
        c = D.close[i]
        v = [D.dtrend[0], D.state["f30"], np.sign(c - D.pdc[0]), np.sign(c - D.vwap[i]), np.sign(c - D.close[i - 6])]
        return int(v[0]) if v[0] != 0 and all(x == v[0] for x in v) else 0

    def signal(self, D, i, p):
        s = D.state
        st = self._stack(D, i)
        prev, s["prev"] = s["prev"], st
        if s["n"] >= p["mx"] or st == 0:
            return None
        d = st
        if p["trig"] == "align":
            if prev == st:
                return None
        else:
            touched = D.low[i] <= D.ema9[i] if d == 1 else D.high[i] >= D.ema9[i]
            if not (touched and (D.close[i] - D.ema9[i]) * d > 0):
                return None
        return dict(dir=d, stop=D.close[i] - d * p["k"] * D.atr[i], r=R, max_bars=p["max_bars"])


ALL += [Confluence()]
