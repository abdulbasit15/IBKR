"""Scalping strategy families (all evaluated on 5-min RTH bars, signal on bar close).

Times are minutes since midnight ET (570 = 09:30, 600 = 10:00, 660 = 11:00, 900 = 15:00).
"""
import itertools
import numpy as np
from scalp_engine import Strategy


def _grid(**kw):
    keys = list(kw)
    return [dict(zip(keys, vals)) for vals in itertools.product(*kw.values())]


# 1 ------------------------------------------------------------------ Opening Range Breakout / Initial Balance
class ORB(Strategy):
    """First close beyond the N-minute opening range (N=60 -> Initial Balance) -> trade the breakout.
    Stop: opposite side of range ('opp') or range midpoint ('mid'). Target: r x risk ('r1','r2') or a
    range extension ('ext0.5' = edge + 50% of range width). narrow=True: only when the range is
    narrower than its 20-day median. Skip ranges wider than 0.6 x 14-day avg daily range. 1 trade/day."""
    name = "ORB"
    grid = _grid(orm=[5, 15, 30, 60], stop=["mid", "opp"], tgt=["r1", "r2", "ext0.5"], narrow=[False, True],
                 max_bars=[24])

    def reset(self):
        self.hist = []

    def start_day(self, D, p):
        k = p["orm"] // 5
        hi, lo = D.high[:k].max(), D.low[:k].min()
        med = np.median(self.hist[-20:]) if len(self.hist) >= 10 else np.inf
        self.hist.append(hi - lo)
        D.state = {"n": 0, "k": k, "hi": hi, "lo": lo, "ok": (not p["narrow"]) or (hi - lo) < med}
        p["last_entry"] = 720 if p["orm"] >= 60 else 660

    def signal(self, D, i, p):
        s = D.state
        if s["n"] or i < s["k"] or not s["ok"]:
            return None
        hi, lo = s["hi"], s["lo"]
        w = hi - lo
        if w > 0.6 * D.datr[i]:                   # skip abnormally wide opening ranges
            return None
        mid = (hi + lo) / 2
        for d, edge, opp in ((1, hi, lo), (-1, lo, hi)):
            if (D.close[i] - edge) * d > 0:
                stop = mid if p["stop"] == "mid" else opp
                if p["tgt"].startswith("ext"):
                    return dict(dir=d, stop=stop, tgt=edge + d * float(p["tgt"][3:]) * w, max_bars=p["max_bars"])
                return dict(dir=d, stop=stop, r=float(p["tgt"][1:]), max_bars=p["max_bars"])
        return None


# 2 ------------------------------------------------------------------ First-candle momentum
class FirstBar(Strategy):
    """Zarattini/Aziz 5-min ORB: trade in the direction of the first 5-min candle at the 09:35 open.
    Stop = s x 14-day avg daily range. Target r x risk (None = hold to max_bars/EOD)."""
    name = "FirstBar"
    grid = _grid(s=[0.05, 0.10], r=[1.0, 2.0, None], max_bars=[12, 77], last_entry=[575])

    def signal(self, D, i, p):
        if i != 0 or D.state["n"]:
            return None
        if D.close[0] == D.open[0]:
            return None
        d = 1 if D.close[0] > D.open[0] else -1
        stop = D.open[1] - d * p["s"] * D.datr[0]
        return dict(dir=d, stop=stop, r=p["r"], max_bars=p["max_bars"])


# 3 ------------------------------------------------------------------ VWAP band fade (mean reversion)
class VWAPFade(Strategy):
    """Bar closes outside VWAP +/- k*sd, next bar closes back inside -> fade toward VWAP.
    Stop beyond excursion extreme + 0.1 ATR. Target VWAP ('vwap') or the 1-sd band ('1sd')."""
    name = "VWAPFade"
    grid = _grid(k=[2.0, 2.5], tgt=["vwap", "1sd"], trendfilt=[False, True],
                 first=[600], last_entry=[900], max_bars=[12], max_trades=[3])

    def signal(self, D, i, p):
        if D.tm[i] < p["first"] or D.state["n"] >= p["max_trades"] or i < 2:
            return None
        k, vw, sd = p["k"], D.vwap, D.vsd
        if sd[i] <= 0:
            return None
        if p["trendfilt"] and abs(vw[i] - vw[max(0, i - 12)]) > 0.75 * D.atr[i]:
            return None                           # VWAP sloping hard = trend day, don't fade
        up_prev, dn_prev = D.close[i - 1] > vw[i - 1] + k * sd[i - 1], D.close[i - 1] < vw[i - 1] - k * sd[i - 1]
        if up_prev and D.close[i] < vw[i] + k * sd[i]:
            tgt = vw[i] if p["tgt"] == "vwap" else vw[i] + sd[i]
            return dict(dir=-1, stop=max(D.high[i - 2:i + 1]) + 0.1 * D.atr[i], tgt=tgt, max_bars=p["max_bars"])
        if dn_prev and D.close[i] > vw[i] - k * sd[i]:
            tgt = vw[i] if p["tgt"] == "vwap" else vw[i] - sd[i]
            return dict(dir=1, stop=min(D.low[i - 2:i + 1]) - 0.1 * D.atr[i], tgt=tgt, max_bars=p["max_bars"])
        return None


# 4 ------------------------------------------------------------------ VWAP / EMA trend pullback
class VWAPPullback(Strategy):
    """Trend: close above VWAP, VWAP rising (vs 6 bars ago), EMA9 > EMA20.
    Pullback: one of the last 3 bars tagged EMA20 (within 0.1 ATR). Trigger: close above prior bar high.
    Stop: lowest low of last 3 bars - 0.1 ATR. Target r x risk. Mirror for shorts."""
    name = "VWAPPullback"
    grid = _grid(r=[1.0, 1.5, 2.0], first=[600], last_entry=[900], max_bars=[24], max_trades=[2, 4])

    def signal(self, D, i, p):
        if D.tm[i] < p["first"] or D.state["n"] >= p["max_trades"] or i < 6:
            return None
        c, a, e9, e20, vw = D.close, D.atr[i], D.ema9, D.ema20, D.vwap
        lo3, hi3 = D.low[i - 2:i + 1].min(), D.high[i - 2:i + 1].max()
        if c[i] > vw[i] and vw[i] > vw[i - 6] and e9[i] > e20[i]:
            if (D.low[i - 2:i + 1] <= e20[i - 2:i + 1] + 0.1 * a).any() and c[i] > D.high[i - 1]:
                return dict(dir=1, stop=lo3 - 0.1 * a, r=p["r"], max_bars=p["max_bars"])
        if c[i] < vw[i] and vw[i] < vw[i - 6] and e9[i] < e20[i]:
            if (D.high[i - 2:i + 1] >= e20[i - 2:i + 1] - 0.1 * a).any() and c[i] < D.low[i - 1]:
                return dict(dir=-1, stop=hi3 + 0.1 * a, r=p["r"], max_bars=p["max_bars"])
        return None


# 5 ------------------------------------------------------------------ RSI(2) pullback in trend (Connors-style)
class RSI2(Strategy):
    """Trend filter: close vs VWAP and EMA20 vs EMA50. Long when RSI(2) < th in an uptrend.
    Exit on close back above EMA9 (rule), stop m x ATR, time stop max_bars."""
    name = "RSI2"
    grid = _grid(th=[5, 10], m=[1.0, 1.5], max_bars=[6, 12], first=[600], last_entry=[900], max_trades=[4])

    def signal(self, D, i, p):
        if D.tm[i] < p["first"] or D.state["n"] >= p["max_trades"]:
            return None
        c, a = D.close[i], D.atr[i]
        if c > D.vwap[i] and D.ema20[i] > D.ema50[i] and D.rsi2[i] < p["th"]:
            return dict(dir=1, stop=c - p["m"] * a, max_bars=p["max_bars"])
        if c < D.vwap[i] and D.ema20[i] < D.ema50[i] and D.rsi2[i] > 100 - p["th"]:
            return dict(dir=-1, stop=c + p["m"] * a, max_bars=p["max_bars"])
        return None

    def exit(self, D, j, d, p, sig):
        return (D.close[j] > D.ema9[j]) if d == 1 else (D.close[j] < D.ema9[j])


# 6 ------------------------------------------------------------------ Bollinger squeeze breakout
class Squeeze(Strategy):
    """BB(20,2) width in the bottom q of the last 120 bars on the prior bar, then a close outside the
    band in the direction of VWAP. Stop = BB mid. Target r x risk."""
    name = "Squeeze"
    grid = _grid(q=[0.15, 0.25], r=[1.0, 1.5, 2.0], first=[600], last_entry=[900], max_bars=[24], max_trades=[2])

    def signal(self, D, i, p):
        if D.tm[i] < p["first"] or D.state["n"] >= p["max_trades"] or i < 1:
            return None
        if not (D.bbw_rank[i - 1] <= p["q"]):
            return None
        c = D.close[i]
        if c > D.bb_up[i] and c > D.vwap[i]:
            return dict(dir=1, stop=D.bb_mid[i], r=p["r"], max_bars=p["max_bars"])
        if c < D.bb_lo[i] and c < D.vwap[i]:
            return dict(dir=-1, stop=D.bb_mid[i], r=p["r"], max_bars=p["max_bars"])
        return None


# 7 ------------------------------------------------------------------ Failed breakout of key level (sweep & reclaim)
class SweepReclaim(Strategy):
    """Price trades beyond a key level (prior-day H/L, or 15-min opening range H/L) and a bar CLOSES
    back inside -> fade. Stop = extreme since the sweep + 0.1 ATR. Target r x risk or VWAP.
    One trade per level per day."""
    name = "SweepReclaim"
    grid = _grid(level=["pd", "or15"], tgt=["r1.5", "r2", "vwap"], last_entry=[840], max_bars=[24])

    def start_day(self, D, p):
        D.state = {"n": 0, "used": set(), "xhi": -np.inf, "xlo": np.inf}
        if p["level"] == "pd":
            D.state["H"], D.state["L"], D.state["k"] = D.pdh[0], D.pdl[0], 0
        else:
            D.state["H"], D.state["L"], D.state["k"] = D.high[:3].max(), D.low[:3].min(), 3

    def signal(self, D, i, p):
        s = D.state
        if i < s["k"]:
            return None
        H, L = s["H"], s["L"]
        s["xhi"] = max(s["xhi"], D.high[i]) if D.high[i] > H else s["xhi"]
        s["xlo"] = min(s["xlo"], D.low[i]) if D.low[i] < L else s["xlo"]

        def mk(d, stop):
            if p["tgt"] == "vwap":
                if (D.vwap[i] - D.close[i]) * d <= 0:
                    return None
                return dict(dir=d, stop=stop, tgt=D.vwap[i], max_bars=p["max_bars"])
            return dict(dir=d, stop=stop, r=float(p["tgt"][1:]), max_bars=p["max_bars"])

        if "H" not in s["used"] and s["xhi"] > H and D.close[i] < H:
            s["used"].add("H")
            return mk(-1, s["xhi"] + 0.1 * D.atr[i])
        if "L" not in s["used"] and s["xlo"] < L and D.close[i] > L:
            s["used"].add("L")
            return mk(1, s["xlo"] - 0.1 * D.atr[i])
        return None


# 8 ------------------------------------------------------------------ Opening gap fill
class GapFill(Strategy):
    """Open gaps >= g x 14-day avg range vs prior RTH close (and < 1x). If the first 5-min bar
    closes in the fill direction, enter toward the prior close. Stop = first-bar extreme + 0.1 ATR.
    Target = full fill (prior close) or half fill."""
    name = "GapFill"
    grid = _grid(g=[0.10, 0.20, 0.30], fill=[1.0, 0.5], last_entry=[575], max_bars=[18])

    def signal(self, D, i, p):
        if i != 0:
            return None
        gap = D.open[0] - D.pdc[0]
        da = D.datr[0]
        if not (p["g"] * da <= abs(gap) < 1.0 * da):
            return None
        d = -1 if gap > 0 else 1
        if (D.close[0] - D.open[0]) * d <= 0:
            return None
        tgt = D.open[1] + (D.pdc[0] - D.open[1]) * p["fill"]
        stop = (D.high[0] if d == -1 else D.low[0]) - d * 0.1 * D.atr[0]
        return dict(dir=d, stop=stop, tgt=tgt, max_bars=p["max_bars"])


# 9 ------------------------------------------------------------------ Noise-area momentum (Zarattini/Aziz/Barbon 2024)
class NoiseBand(Strategy):
    """Upper band = max(open, prior close) x (1 + sigma_t), lower = min(open, prior close) x (1 - sigma_t),
    sigma_t = 14-day mean |close/open - 1| at that time of day. Checked only on bars closing on :00/:30
    (check=30) from 10:00. Long above upper / short below lower. Stop = max(upper, VWAP) (mirror) placed at
    entry; at every check bar exit on a close back through the CURRENT trailing level. Optional r target.
    Flat at the close."""
    name = "NoiseBand"
    grid = _grid(check=[30, 15], vm=[1.0, 1.5], tgt=[None, "r2"], last_entry=[930])

    def _bands(self, D, i, p):
        sg = D.nsig[i] * p["vm"]
        return max(D.open[0], D.pdc[0]) * (1 + sg), min(D.open[0], D.pdc[0]) * (1 - sg)

    def _is_check(self, D, i, p):
        t = D.tm[i] + 5
        return t >= 600 and t % p["check"] == 0

    def signal(self, D, i, p):
        if np.isnan(D.nsig[i]) or not self._is_check(D, i, p):
            return None
        ub, lb = self._bands(D, i, p)
        c, vw = D.close[i], D.vwap[i]
        r = 2.0 if p["tgt"] == "r2" else None
        if c > ub:
            return dict(dir=1, stop=max(ub, vw), r=r)
        if c < lb:
            return dict(dir=-1, stop=min(lb, vw), r=r)
        return None

    def exit(self, D, j, d, p, sig):
        if not self._is_check(D, j, p) or np.isnan(D.nsig[j]):
            return False
        ub, lb = self._bands(D, j, p)
        return D.close[j] < max(ub, D.vwap[j]) if d == 1 else D.close[j] > min(lb, D.vwap[j])


# 10 ----------------------------------------------------------------- Last-half-hour intraday momentum (Gao et al.)
class LastHalf(Strategy):
    """At 15:30, trade the sign of the day's return so far ('day' = 15:30 close vs prior close) or of the
    first half hour ('first30' = 10:00 close vs prior close), if |ret| >= thr x 14-day avg range.
    Stop = 0.15 x 14-day avg range. Exit at the 16:00 close."""
    name = "LastHalf"
    grid = _grid(sig=["day", "first30"], thr=[0.0, 0.25], last_entry=[930])

    def signal(self, D, i, p):
        if D.tm[i] != 925 or D.state["n"]:
            return None
        if p["sig"] == "day":
            ret = D.close[i] - D.pdc[0]
        else:
            k = np.where(D.tm == 595)[0]
            if not len(k):
                return None
            ret = D.close[k[0]] - D.pdc[0]
        if abs(ret) < p["thr"] * D.datr[0] or ret == 0:
            return None
        d = 1 if ret > 0 else -1
        return dict(dir=d, stop=D.open[i + 1] - d * 0.15 * D.datr[0])


ALL = [ORB(), FirstBar(), VWAPFade(), VWAPPullback(), RSI2(), Squeeze(), SweepReclaim(), GapFill(), NoiseBand(), LastHalf()]
