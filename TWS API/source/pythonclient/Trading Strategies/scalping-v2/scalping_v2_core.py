"""
Scalping v2 bot — shared core (indicators + strategies + simulator + live replay).

This ONE module is used by BOTH the backtest (scalping_v2_backtest.py) and the live bot (scalping_v2_bot.py), so the bot
trades exactly the rules that were backtested. Logic is copied from the research study in
`scalping-v1/` (scalp_engine.py, rr2_strategies*.py, rr2_final.py, rr2_windows.py) —
see RR2_Strategy_Report.md / Windows_Report.md there. One deliberate fix vs the study: H2L2 uses the real
contract tick (the study guessed 0.25 for any price > 1000, i.e. 0.25 instead of 0.10 on MGC).

Bars: 5-minute RTH bars, 09:30-16:00 ET (bar START times 09:30 .. 15:55), times as minutes since midnight
ET in column `tm` (570 = 09:30). A signal is evaluated on a bar CLOSE.

Fill model (backtest):  market entry at the NEXT bar open (+1 tick slippage) | optional stop-entry order
(sig["entry"], valid sig["expire"] bars, cancelled if the stop trades first) | stop = stop-market (+1 tick,
gap-through fills at the open) | target = limit, needs a 1-tick trade-through | stop & target in the same
bar -> STOP | time exit at an absolute clock time (sig["exit_tm"]) or 16:00.
Target is ALWAYS 2 x risk measured from the actual fill (R_MULT).
"""
from __future__ import annotations

import itertools
import numpy as np
import pandas as pd

R_MULT = 2.0
TZ = "America/New_York"

# fallback contract specs (the bot reads multiplier / minTick from IB; the backtest uses these)
SPECS = {
    # micros
    "MNQ": dict(pv=2.0, tick=0.25, comm=0.62, exchange="CME", data="MNQ"),
    "MES": dict(pv=5.0, tick=0.25, comm=0.62, exchange="CME", data="MES"),
    "MGC": dict(pv=10.0, tick=0.10, comm=0.80, exchange="COMEX", data="MGC"),
    "MYM": dict(pv=0.5, tick=1.0, comm=0.62, exchange="CBOT", data="MYM"),
    # full-size (same underlying prices as the micro -> the backtest reuses the micro's bar history via `data`)
    "NQ": dict(pv=20.0, tick=0.25, comm=2.25, exchange="CME", data="MNQ"),
    "ES": dict(pv=50.0, tick=0.25, comm=2.25, exchange="CME", data="MES"),
    "GC": dict(pv=100.0, tick=0.10, comm=2.42, exchange="COMEX", data="MGC"),
    "YM": dict(pv=5.0, tick=1.0, comm=2.25, exchange="CBOT", data="MYM"),
    # crude oil: IB "RTH" for CL is the NYMEX pit (09:00-14:30 ET), so CL uses FULL-session bars (use_rth=False)
    # trimmed to the same 09:30-16:00 ET clock as the other markets.
    "CL": dict(pv=1000.0, tick=0.01, comm=2.35, exchange="NYMEX", data="CL", use_rth=False),
    "MCL": dict(pv=100.0, tick=0.01, comm=0.80, exchange="NYMEX", data="CL", use_rth=False),
}


def _grid(**kw):
    keys = list(kw)
    return [dict(zip(keys, vals)) for vals in itertools.product(*kw.values())]


# ─────────────────────────────── bar preparation ───────────────────────────────
def prepare_bars(df: pd.DataFrame, live_day=None) -> pd.DataFrame:
    """df: columns date(tz-aware or UTC), open, high, low, close, volume. Returns RTH-trimmed bars with
    `tm` and `day`, keeping only complete/real past sessions (opens 09:30, >=40 bars, <=3% flat padded
    bars). `live_day` (a date) is ALWAYS kept even though it is still partial (live trading)."""
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"], utc=True).dt.tz_convert(TZ)
    df = df.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)
    df["tm"] = df.date.dt.hour * 60 + df.date.dt.minute
    df = df[(df.tm >= 570) & (df.tm <= 955)].copy()
    df["day"] = df.date.dt.date
    g = df.groupby("day").agg(n=("tm", "size"), first=("tm", "min"))
    flat = (df.high == df.low).groupby(df.day).mean()
    good = set(g[(g.n >= 40) & (g["first"] == 570)].index.intersection(flat[flat <= 0.03].index))
    if live_day is not None:
        good.add(live_day)
    return df[df.day.isin(good)].reset_index(drop=True)


# ─────────────────────────────── indicators ───────────────────────────────
def ema(x, n):
    return pd.Series(x).ewm(span=n, adjust=False).mean().values


def rma(x, n):
    return pd.Series(x).ewm(alpha=1.0 / n, adjust=False).mean().values


def add_indicators(df: pd.DataFrame, tick: float) -> pd.DataFrame:
    """All causal: EMA/ATR use only past bars, VWAP is cumulative within the session, daily context
    (prior-day close, 14-day avg range, daily trend) is shifted one day."""
    df = df.reset_index(drop=True).copy()
    o, h, l, c, v = (df[k].values.astype(float) for k in ("open", "high", "low", "close", "volume"))
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc)))
    df["atr"] = rma(tr, 14)
    for n in (9, 20, 50):
        df[f"ema{n}"] = ema(c, n)
    tp = (h + l + c) / 3.0
    vv = np.where(v <= 0, 1.0, v)
    g = df.day.values
    cv = pd.Series(vv).groupby(g).cumsum().values
    cpv = pd.Series(tp * vv).groupby(g).cumsum().values
    df["vwap"] = cpv / cv
    dd = df.groupby("day").agg(dh=("high", "max"), dl=("low", "min"), dc=("close", "last"))
    dd["datr"] = (dd.dh - dd.dl).rolling(14, min_periods=5).mean().shift(1)
    dd["pdh"], dd["pdl"], dd["pdc"] = dd.dh.shift(1), dd.dl.shift(1), dd.dc.shift(1)
    # daily trend: yesterday's RTH close vs the EMA(n) of RTH closes (known before today's open)
    dd["dtrend"] = np.sign(dd.dc - dd.dc.ewm(span=20, adjust=False).mean()).shift(1)
    for n in (10, 20, 50):
        dd[f"tr{n}"] = np.sign(dd.dc - dd.dc.ewm(span=n, adjust=False).mean()).shift(1)
    df = df.join(dd[["datr", "pdh", "pdl", "pdc", "dtrend", "tr10", "tr20", "tr50"]], on="day")
    df["dtrend"] = df["dtrend"].fillna(0)
    df["tick"] = tick
    return df


# ─────────────────────────────── strategy framework ───────────────────────────────
class Day:
    """Per-day array view handed to strategies (attributes = columns as numpy arrays)."""
    def __init__(self, g: pd.DataFrame):
        for k in g.columns:
            setattr(self, k, g[k].values)
        self.n = len(g)
        self.date = g["day"].iloc[0]
        self.state = {}


class Strategy:
    name = "base"

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


def _ok_dir(D, d, p):
    return (not p.get("dtf")) or D.dtrend[0] == d


# 1 ─── IB Trend Breakout (Initial Balance + daily-trend filter) ───────────────────────────────
class IBTrend(Strategy):
    """IB = 09:30-10:30 high/low. Daily trend = prior close vs EMA(10/20/50) of RTH closes (`trend`).
    entry='confirm': if the bar closing 11:00 is beyond the IB in the trend direction -> enter 11:00 open.
    entry='first'  : first 5-min close beyond the IB (until 12:00). The FIRST IB break decides the day
    (against-trend break = no trade). Stop = IB midpoint ('mid') or tighter of mid / 0.5 x IB ('cap').
    nw: skip days whose IB > nw x 14-day avg range (9.9 = off). Target 2R."""
    name = "ib_trend"

    def start_day(self, D, p):
        k = D.tm < 630
        hi, lo = (D.high[k].max(), D.low[k].min()) if k.any() else (np.nan, np.nan)
        tr = {"e10": D.tr10[0], "e20": D.tr20[0], "e50": D.tr50[0], "none": 0, "long": 1}[p["trend"]]
        D.state = {"n": 0, "hi": hi, "lo": lo, "tr": tr,
                   "ok": (hi - lo) <= p["nw"] * D.datr[0] and not np.isnan(tr)}
        p.setdefault("last_entry", 720 if p["entry"] == "first" else 660)

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
                return dict(dir=d, stop=stop, r=R_MULT, max_bars=999)
        return None

    def on_trade(self, D, i, j, d, p):
        D.state["n"] = 1


# 2 ─── Al Brooks High-2 / Low-2 pullback in trend ───────────────────────────────
class H2L2(Strategy):
    """Trend: EMA20 rising over 6 bars, close above EMA20 and VWAP (mirror for shorts); dtf=True also
    requires the daily trend. In a pullback from the session swing high count 'H' bars (high > prior
    high). After H1, when a bar makes a lower high, place a stop-entry 1 tick above it (the H2 trigger,
    valid 1 bar). Stop = pullback low - 1 tick; skip if risk > maxr x ATR. From 10:00, max 3/day. 2R."""
    name = "h2l2_trend"

    def start_day(self, D, p):
        D.state = {"n": 0, "L": dict(hh=-np.inf, cnt=0, plo=np.inf), "S": dict(ll=np.inf, cnt=0, phi=-np.inf)}

    def signal(self, D, i, p):
        if D.state["n"] >= p.get("max_trades", 3) or i < 6:
            return None
        h, l, c, a = D.high, D.low, D.close, D.atr[i]
        tick = D.tick[0]
        L, S = D.state["L"], D.state["S"]
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
                return dict(dir=1, stop=stop, entry=h[i] + tick, expire=1, r=R_MULT, max_bars=999)
        if dn and _ok_dir(D, -1, p) and S["cnt"] == 1 and l[i] >= l[i - 1] and np.isfinite(S["phi"]):
            stop = S["phi"] + tick
            if (stop - (l[i] - tick)) <= p["maxr"] * a:
                return dict(dir=-1, stop=stop, entry=l[i] - tick, expire=1, r=R_MULT, max_bars=999)
        return None

    def on_trade(self, D, i, j, d, p):
        D.state["n"] += 1
        D.state["L"]["cnt"] = 2 if d == 1 else D.state["L"]["cnt"]     # consume the setup
        D.state["S"]["cnt"] = 2 if d == -1 else D.state["S"]["cnt"]


# 3 ─── ORB second break (double break) ───────────────────────────────
class ORB2nd(Strategy):
    """OR = first `orm` minutes. First 5-min close beyond one edge, then a close back inside the OR,
    then the first close beyond the OPPOSITE edge -> enter next open that way. Stop = extreme of the failed
    first break, capped at 1 x OR from the signal close. One per day. Target 2R."""
    name = "orb2nd"

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
            return dict(dir=d, stop=stop, r=R_MULT, max_bars=999)
        return None


# 4 ─── Trend-confluence EMA9 pullback ───────────────────────────────
class Confluence(Strategy):
    """From 10:00 all five agree with the trade: daily trend, first-30-min return (10:00 close vs prior
    close), price vs prior close, price vs VWAP, 30-min momentum. trig='pb': a bar dips to EMA9 and closes
    back beyond it in the trend direction -> enter next open. Stop = k x ATR(14,5m). Max mx/day. 2R."""
    name = "confluence_pb"

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
        if p.get("trig", "pb") == "align":
            if prev == st:
                return None
        else:
            touched = D.low[i] <= D.ema9[i] if d == 1 else D.high[i] >= D.ema9[i]
            if not (touched and (D.close[i] - D.ema9[i]) * d > 0):
                return None
        return dict(dir=d, stop=D.close[i] - d * p["k"] * D.atr[i], r=R_MULT, max_bars=999)


STRATEGY_CLASSES = {"ib_trend": IBTrend, "h2l2_trend": H2L2, "orb2nd": ORB2nd, "confluence_pb": Confluence}
EVENT_STRATEGIES = {"ib_trend", "orb2nd"}       # one setup per day (skip the day if it fires before the window)


def hhmm_to_min(s: str) -> int:
    h, m = s.split(":")[:2]
    return int(h) * 60 + int(m)


class Windowed(Strategy):
    """Restricts an inner strategy to ENTER only inside [start, end) ET.
    mode 'flat': forced exit at the window end. mode 'hold': manage to 2R / stop / 16:00 (entries <= 15:25).
    Event strategies are skipped for the day if their one setup fires before the window opens."""
    def __init__(self, inner, start, end, mode, event):
        self.inner, self.start, self.end, self.mode, self.event = inner, start, end, mode, event
        self.name = inner.name
        self.dead = False

    def reset(self):
        self.inner.reset()

    def start_day(self, D, p):
        self.inner.start_day(D, p)
        p["last_entry"] = min(self.end - 5, 925 if self.mode == "hold" else self.end - 10)
        self.dead = False

    def signal(self, D, i, p):
        sig = self.inner.signal(D, i, p)            # always called: keeps the inner state machine in sync
        if not sig or self.dead:
            return None
        nxt = D.tm[i + 1] if i + 1 < D.n else D.tm[i] + 5
        if nxt < self.start:
            if self.event:
                self.dead = True
            return None
        if self.mode == "flat":
            sig = dict(sig, exit_tm=self.end)
            if sig.get("entry") is not None:
                sig["expire"] = min(sig.get("expire", 1), max(1, (self.end - 5 - nxt) // 5))
        return sig

    def exit(self, D, j, d, p, sig):
        return self.inner.exit(D, j, d, p, sig)

    def on_trade(self, D, i, j, d, p):
        self.inner.on_trade(D, i, j, d, p)


def build_strategy(name: str, scfg: dict) -> tuple[Strategy, dict]:
    """(Windowed strategy, params) from a config block {"window": ["09:30","11:30"], "mode": "hold", "params": {...}}"""
    inner = STRATEGY_CLASSES[name]()
    a, b = (hhmm_to_min(x) for x in scfg.get("window", ["09:30", "16:00"]))
    st = Windowed(inner, a, b, scfg.get("mode", "hold"), name in EVENT_STRATEGIES)
    return st, dict(scfg.get("params", {}))


# ─────────────────────────────── per-day trade engine ───────────────────────────────
def _run_day(D: Day, strat: Strategy, params: dict, tick: float, slip: float, upto: int | None = None):
    """Run one day. Backtest mode (upto=None): returns list of trade dicts.
    Live replay mode (upto=L): bars 0..L are COMPLETE; returns (trades, live) where live is
       {"busy": True, "trade": {...}}  -> a replayed trade is still open at bar L (strategy is in a position)
       {"signal": sig, "ref": close[L]} -> the strategy wants to act NOW (at the open of the next bar)
       {}                              -> nothing to do."""
    p = params
    strat.reset()
    strat.start_day(D, p)
    trades = []
    n = D.n if upto is None else upto + 1
    i = 0
    while i < n:
        if i == n - 1:
            if upto is None:
                break
            sig = strat.signal(D, i, p)                  # the live decision point
            if sig and D.tm[i] + 5 <= p.get("last_entry", 930):
                return trades, {"signal": sig, "ref": float(D.close[i]), "bar_tm": int(D.tm[i])}
            return trades, {}
        sig = strat.signal(D, i, p)
        if not sig or D.tm[i + 1] > p.get("last_entry", 930):
            i += 1
            continue
        d, stop, k0 = sig["dir"], sig["stop"], i + 1
        intrabar = False
        if sig.get("entry") is not None:
            lvl, k0 = sig["entry"], None
            pending_open = False
            for k in range(i + 1, i + 1 + sig.get("expire", 1)):
                if k >= n:
                    pending_open = True                   # order still resting at the live edge
                    break
                if D.tm[k] > p.get("last_entry", 930):
                    break
                if (D.high[k] >= lvl) if d == 1 else (D.low[k] <= lvl):
                    k0 = k
                    break
                if (D.low[k] <= stop) if d == 1 else (D.high[k] >= stop):
                    break
            if k0 is None:
                if pending_open and upto is not None:
                    return trades, {"pending": sig}
                i += 1
                continue
            e = (max(D.open[k0], lvl) if d == 1 else min(D.open[k0], lvl)) + d * slip
            intrabar = (lvl - D.open[k0]) * d > 1e-9
        else:
            e = D.open[k0] + d * slip
        risk = (e - stop) * d
        if risk < 4 * tick:                              # gap past stop / degenerate risk -> skip
            i = max(i + 1, k0) if sig.get("entry") is not None else i + 1
            continue
        tgt = e + d * sig.get("r", R_MULT) * risk
        j, x, why = k0, None, None
        open_at_edge = False
        while True:
            if j >= n:
                open_at_edge = True
                break
            th_hi = D.close[j] if (intrabar and j == k0) else D.high[j]
            th_lo = D.close[j] if (intrabar and j == k0) else D.low[j]
            if d == 1 and D.low[j] <= stop:
                x, why = min(stop, D.open[j]) - slip, "stop"
            elif d == -1 and D.high[j] >= stop:
                x, why = max(stop, D.open[j]) + slip, "stop"
            elif d == 1 and th_hi >= tgt + tick:
                x, why = (max(tgt, D.open[j]) if (j > k0 or not intrabar) else tgt), "target"
            elif d == -1 and th_lo <= tgt - tick:
                x, why = (min(tgt, D.open[j]) if (j > k0 or not intrabar) else tgt), "target"
            elif strat.exit(D, j, d, p, sig):
                x, why = D.close[j] - d * slip, "rule"
            elif sig.get("exit_tm") is not None and D.tm[j] + 5 >= sig["exit_tm"]:
                x, why = D.close[j] - d * slip, "window"
            elif j == D.n - 1 and upto is None:
                x, why = D.close[j] - d * slip, "eod"
            if x is not None:
                break
            j += 1
        tr = dict(dir=d, signal_tm=int(D.tm[i]), entry_bar=k0, et=int(D.tm[k0]), entry=float(e), stop=float(stop),
                  target=float(tgt), risk=float(risk), sig=sig)
        if open_at_edge:
            if upto is not None:
                return trades, {"busy": True, "trade": tr}
            break
        tr.update(exit_bar=j, xt=int(D.tm[j]), exit=float(x), why=why, pts=float((x - e) * d))
        trades.append(tr)
        strat.on_trade(D, i, j, d, p)
        i = j
    return (trades, {}) if upto is not None else trades


def simulate(sym: str, df: pd.DataFrame, strat: Strategy, params: dict, spec: dict, slip_ticks: int = 1) -> pd.DataFrame:
    """Backtest over all days in df (indicators already added). Returns a trades DataFrame."""
    tick, pv, comm = spec["tick"], spec["pv"], spec["comm"]
    rows = []
    for day, g in df.groupby("day", sort=True):
        D = Day(g)
        if np.isnan(D.datr[0]):
            continue
        for t in _run_day(D, strat, dict(params), tick, tick * slip_ticks):
            net = t["pts"] * pv - 2 * comm
            rows.append(dict(day=day, sym=sym, strategy=strat.name, dir=t["dir"], et=t["et"], xt=t["xt"],
                             entry=t["entry"], exit=t["exit"], stop=t["stop"], target=t["target"], risk=t["risk"],
                             pts=t["pts"], net=net, r=net / (t["risk"] * pv), why=t["why"]))
    return pd.DataFrame(rows)


def live_decision(df_today: pd.DataFrame, strat: Strategy, params: dict, tick: float, slip_ticks: int = 1) -> dict:
    """Replay today's COMPLETE bars through the exact backtest engine and return what the strategy wants
    at the live edge: {"signal": ...} / {"busy": ...} / {"pending": ...} / {}."""
    if df_today.empty:
        return {}
    D = Day(df_today)
    if np.isnan(D.datr[0]):
        return {"error": "no daily context (need >=5 prior sessions)"}
    _, live = _run_day(D, strat, dict(params), tick, tick * slip_ticks, upto=D.n - 1)
    return live


# ─────────────────────────────── metrics ───────────────────────────────
def metrics(t: pd.DataFrame, days: list) -> dict:
    if t is None or len(t) == 0:
        return dict(n=0, win=np.nan, pf=np.nan, net=0.0, dd=0.0, avgR=np.nan, tgt=np.nan, sharpe=np.nan)
    w = t.net > 0
    gl = -t.net[~w].sum()
    daily = t.groupby("day").net.sum().reindex(days, fill_value=0.0)
    eq = daily.cumsum()
    dd = float((eq.cummax().clip(lower=0) - eq).max())
    sharpe = float(daily.mean() / daily.std() * np.sqrt(252)) if daily.std() > 0 else np.nan
    return dict(n=int(len(t)), win=float(w.mean()), pf=float(t.net[w].sum() / gl) if gl > 0 else np.inf,
                net=float(t.net.sum()), dd=dd, avgR=float(t.r.mean()), tgt=float((t.why == "target").mean()),
                sharpe=sharpe)
