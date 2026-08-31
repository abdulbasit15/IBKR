"""Smart Money Concepts [LuxAlgo] — faithful headless port.

A full Python port of the computational logic of LuxAlgo's "Smart Money Concepts" Pine v5
indicator (CC BY-NC-SA 4.0, (c) LuxAlgo). The original is a drawing-heavy overlay; this port
reproduces the DETECTION logic and returns the resulting state/levels as data (there is no
chart, so colours, boxes, labels and the MTF `request.security` plumbing are replaced by plain
values). Everything else is reproduced bar-for-bar:

  * leg / pivot detection (``leg(size)`` -> swing & internal pivots),
  * internal structure (length 5) and swing structure (length 50) BOS / CHoCH, including the
    confluence filter and the "internal level != swing level" guard,
  * order blocks (internal & swing) using the ATR(200) / cumulative-mean-range volatility
    filter, the parsed-high/low swap on high-volatility bars, and CLOSE/HIGHLOW mitigation,
  * equal highs / lows (EQH / EQL) with the ATR threshold,
  * fair value gaps with the auto threshold (chart timeframe),
  * trailing strong/weak highs & lows,
  * premium / discount / equilibrium zones,
  * prior Daily / Weekly / Monthly highs & lows (computed by grouping the supplied bars).

Two layers (same pattern as the rest of the library):

1. Pure math: ``smc(opens, highs, lows, closes, times, ...)`` -> SMCResult evaluated on the
   last supplied bar.
2. Config-driven value: ``smc_value(...)`` -> SMCResult on the last completed bar.

Pure-Python (no numpy/pandas) so it bundles cleanly into a PyInstaller one-file exe.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..market_data import fetch_bars
from ..volatility.atr import atr, true_range

BULLISH = 1
BEARISH = -1
_NAN = float("nan")


class _Pivot:
    __slots__ = ("current", "last", "crossed", "bar_time", "bar_index")

    def __init__(self):
        self.current = None
        self.last = None
        self.crossed = False
        self.bar_time = None
        self.bar_index = None


def _leg(highs, lows, size):
    """Port of LuxAlgo ``leg(size)``: 0 = bearish leg, 1 = bullish leg (BEARISH_LEG/BULLISH_LEG)."""
    n = len(highs)
    out = [0] * n
    cur = 0
    for i in range(n):
        if i >= size:
            hh = max(highs[i - size + 1:i + 1])  # ta.highest(size)
            ll = min(lows[i - size + 1:i + 1])   # ta.lowest(size)
            if highs[i - size] > hh:             # high[size] > highest -> new bearish leg
                cur = 0
            elif lows[i - size] < ll:            # low[size]  < lowest  -> new bullish leg
                cur = 1
        out[i] = cur
    return out


# ----------------------------------------------------------------------------- result types
@dataclass
class SMCStructure:
    bias: int = 0                 # +1 bullish / -1 bearish / 0 none (current trend)
    last_event: str = ""          # 'BOS' | 'CHoCH' | ''
    last_event_dir: int = 0       # +1 / -1 / 0
    last_event_index: int = -1
    last_event_level: float = _NAN
    event_on_this_bar: bool = False
    current_high: float = _NAN    # active swing/internal high pivot level
    current_low: float = _NAN     # active swing/internal low pivot level


@dataclass
class SMCOrderBlock:
    bias: int                     # +1 bullish (demand) / -1 bearish (supply)
    top: float
    bottom: float
    bar_index: int
    time: object = None


@dataclass
class SMCFairValueGap:
    bias: int                     # +1 bullish / -1 bearish
    top: float                    # normalised (top >= bottom)
    bottom: float
    bar_index: int
    time: object = None


@dataclass
class SMCEqual:
    kind: str = ""                # 'EQH' | 'EQL' | ''
    level: float = _NAN
    bar_index: int = -1


@dataclass
class SMCResult:
    internal: SMCStructure
    swing: SMCStructure
    internal_order_blocks: list = field(default_factory=list)
    swing_order_blocks: list = field(default_factory=list)
    fair_value_gaps: list = field(default_factory=list)
    last_equal_high: SMCEqual = field(default_factory=SMCEqual)
    last_equal_low: SMCEqual = field(default_factory=SMCEqual)
    strong_high: float = _NAN          # trailing top
    strong_high_label: str = ""        # 'Strong High' | 'Weak High'
    strong_low: float = _NAN           # trailing bottom
    strong_low_label: str = ""         # 'Strong Low' | 'Weak Low'
    premium_zone: tuple = (_NAN, _NAN)      # (top, bottom)
    equilibrium_zone: tuple = (_NAN, _NAN)
    discount_zone: tuple = (_NAN, _NAN)
    prev_day_high: float = _NAN
    prev_day_low: float = _NAN
    prev_week_high: float = _NAN
    prev_week_low: float = _NAN
    prev_month_high: float = _NAN
    prev_month_low: float = _NAN
    close: float = _NAN
    time: object = None


def _prev_period_hl(times, highs, lows, end, keyfn):
    if end < 0:
        return (_NAN, _NAN)
    cur_key = keyfn(times[end])
    j = end
    while j >= 0 and keyfn(times[j]) == cur_key:
        j -= 1
    if j < 0:
        return (_NAN, _NAN)
    prev_key = keyfn(times[j])
    hi = float("-inf")
    lo = float("inf")
    k = j
    while k >= 0 and keyfn(times[k]) == prev_key:
        hi = max(hi, highs[k])
        lo = min(lo, lows[k])
        k -= 1
    return (hi, lo)


def _day_key(t):
    d = getattr(t, "date", None)
    return d() if callable(d) else t


def _week_key(t):
    ic = getattr(t, "isocalendar", None)
    if callable(ic):
        c = ic()
        return (c[0], c[1])
    return t


def _month_key(t):
    return (getattr(t, "year", None), getattr(t, "month", None))


def smc(opens, highs, lows, closes, times, *, swing_length=50, internal_length=5,
        equal_length=3, equal_threshold=0.1, order_block_filter="atr",
        order_block_mitigation="highlow", internal_ob_size=5, swing_ob_size=5,
        confluence_filter=False, fvg_auto_threshold=True):
    """Run the full SMC engine over the supplied series and return an SMCResult evaluated on the
    LAST supplied bar. `times` is a list of bar timestamps (datetimes)."""
    n = len(closes)
    if n == 0:
        return None

    atr200 = atr(highs, lows, closes, 200)
    tr = true_range(highs, lows, closes)
    ob_filter_atr = str(order_block_filter).lower() == "atr"
    mit_close = str(order_block_mitigation).lower() == "close"

    leg_swing = _leg(highs, lows, swing_length)
    leg_internal = _leg(highs, lows, internal_length)
    leg_equal = _leg(highs, lows, equal_length)

    swing_high = _Pivot()
    swing_low = _Pivot()
    internal_high = _Pivot()
    internal_low = _Pivot()
    equal_high = _Pivot()
    equal_low = _Pivot()

    swing_trend = 0
    internal_trend = 0

    parsed_highs = []
    parsed_lows = []

    internal_obs = []
    swing_obs = []
    fvgs = []

    internal_events = []   # (bar_index, kind, dir, level)
    swing_events = []
    equal_high_events = []
    equal_low_events = []

    cum_tr = 0.0
    cum_abs_bdp = 0.0

    trailing_state = {"top": None, "bottom": None, "bar_time": None, "bar_index": None,
                      "last_top_time": None, "last_bottom_time": None}

    def handle_structure(leg_series, hi_piv, lo_piv, i, internal, equal):
        if i < 1 or leg_series[i] == leg_series[i - 1]:
            return
        change = leg_series[i] - leg_series[i - 1]
        size = equal_length if equal else (internal_length if internal else swing_length)
        if i - size < 0:
            return
        if change == 1:  # pivot low
            p = lo_piv
            lvl = lows[i - size]
            if equal and p.current is not None and atr200[i] is not None and \
               abs(p.current - lvl) < equal_threshold * atr200[i]:
                equal_low_events.append((i - size, "EQL", lvl))
            p.last = p.current
            p.current = lvl
            p.crossed = False
            p.bar_time = times[i - size]
            p.bar_index = i - size
            if not equal and not internal:
                trailing_state["bottom"] = p.current
                trailing_state["bar_time"] = p.bar_time
                trailing_state["bar_index"] = p.bar_index
                trailing_state["last_bottom_time"] = p.bar_time
        elif change == -1:  # pivot high
            p = hi_piv
            lvl = highs[i - size]
            if equal and p.current is not None and atr200[i] is not None and \
               abs(p.current - lvl) < equal_threshold * atr200[i]:
                equal_high_events.append((i - size, "EQH", lvl))
            p.last = p.current
            p.current = lvl
            p.crossed = False
            p.bar_time = times[i - size]
            p.bar_index = i - size
            if not equal and not internal:
                trailing_state["top"] = p.current
                trailing_state["bar_time"] = p.bar_time
                trailing_state["bar_index"] = p.bar_index
                trailing_state["last_top_time"] = p.bar_time

    def store_ob(p, internal, bias, i):
        lst = internal_obs if internal else swing_obs
        if p.bar_index is None:
            return
        if bias == BEARISH:
            arr = parsed_highs[p.bar_index:i]
            if not arr:
                return
            idx = p.bar_index + arr.index(max(arr))
        else:
            arr = parsed_lows[p.bar_index:i]
            if not arr:
                return
            idx = p.bar_index + arr.index(min(arr))
        ob = {"high": parsed_highs[idx], "low": parsed_lows[idx], "time": times[idx],
              "bias": bias, "bar_index": idx}
        if len(lst) >= 100:
            lst.pop()
        lst.insert(0, ob)

    def delete_obs(internal, i):
        lst = internal_obs if internal else swing_obs
        bear_src = closes[i] if mit_close else highs[i]
        bull_src = closes[i] if mit_close else lows[i]
        keep = []
        for ob in lst:
            if ob["bias"] == BEARISH and bear_src > ob["high"]:
                continue
            if ob["bias"] == BULLISH and bull_src < ob["low"]:
                continue
            keep.append(ob)
        lst[:] = keep

    for i in range(n):
        # --- per-bar volatility / parsed high-low (pushed before any function runs) ---
        cum_tr += tr[i]
        if ob_filter_atr:
            vol = atr200[i] if atr200[i] is not None else (cum_tr / (i + 1))
        else:
            vol = cum_tr / i if i > 0 else (highs[i] - lows[i])
        high_vol_bar = (highs[i] - lows[i]) >= (2 * vol)
        parsed_highs.append(lows[i] if high_vol_bar else highs[i])
        parsed_lows.append(highs[i] if high_vol_bar else lows[i])

        # capture pivot levels as of the previous bar (for crossover/crossunder)
        ih_prev = internal_high.current
        il_prev = internal_low.current
        sh_prev = swing_high.current
        sl_prev = swing_low.current
        prev_close = closes[i - 1] if i >= 1 else None

        # --- delete filled fair value gaps (uses current bar) ---
        kept = []
        for g in fvgs:
            if (lows[i] < g["bottom"] and g["bias"] == BULLISH) or \
               (highs[i] > g["top"] and g["bias"] == BEARISH):
                continue
            kept.append(g)
        fvgs[:] = kept

        # --- structure pivots: swing(50), internal(5), equal(3) ---
        handle_structure(leg_swing, swing_high, swing_low, i, internal=False, equal=False)
        handle_structure(leg_internal, internal_high, internal_low, i, internal=True, equal=False)
        handle_structure(leg_equal, equal_high, equal_low, i, internal=False, equal=True)

        # --- trailing extremes (extend) ---
        if trailing_state["top"] is not None:
            if highs[i] > trailing_state["top"]:
                trailing_state["top"] = highs[i]
                trailing_state["last_top_time"] = times[i]
        if trailing_state["bottom"] is not None:
            if lows[i] < trailing_state["bottom"]:
                trailing_state["bottom"] = lows[i]
                trailing_state["last_bottom_time"] = times[i]

        # --- confluence filter ---
        if confluence_filter:
            body_top = max(closes[i], opens[i])
            bullish_bar = (highs[i] - body_top) > min(closes[i], opens[i] - lows[i])
            bearish_bar = (highs[i] - body_top) < min(closes[i], opens[i] - lows[i])
        else:
            bullish_bar = True
            bearish_bar = True

        # --- displayStructure(internal) then displayStructure(swing) ---
        for internal in (True, False):
            hi_piv = internal_high if internal else swing_high
            lo_piv = internal_low if internal else swing_low
            hi_prev = ih_prev if internal else sh_prev
            lo_prev = il_prev if internal else sl_prev

            # bullish break (crossover close over high pivot)
            extra = (hi_piv.current != swing_high.current and bullish_bar) if internal else True
            if (hi_piv.current is not None and hi_prev is not None and prev_close is not None and
                    closes[i] > hi_piv.current and prev_close <= hi_prev and
                    not hi_piv.crossed and extra):
                trend = internal_trend if internal else swing_trend
                kind = "CHoCH" if trend == BEARISH else "BOS"
                hi_piv.crossed = True
                if internal:
                    internal_trend = BULLISH
                    internal_events.append((i, kind, BULLISH, hi_piv.current))
                else:
                    swing_trend = BULLISH
                    swing_events.append((i, kind, BULLISH, hi_piv.current))
                store_ob(hi_piv, internal, BULLISH, i)

            # bearish break (crossunder close under low pivot)
            extra = (lo_piv.current != swing_low.current and bearish_bar) if internal else True
            if (lo_piv.current is not None and lo_prev is not None and prev_close is not None and
                    closes[i] < lo_piv.current and prev_close >= lo_prev and
                    not lo_piv.crossed and extra):
                trend = internal_trend if internal else swing_trend
                kind = "CHoCH" if trend == BULLISH else "BOS"
                lo_piv.crossed = True
                if internal:
                    internal_trend = BEARISH
                    internal_events.append((i, kind, BEARISH, lo_piv.current))
                else:
                    swing_trend = BEARISH
                    swing_events.append((i, kind, BEARISH, lo_piv.current))
                store_ob(lo_piv, internal, BEARISH, i)

        # --- order block mitigation ---
        delete_obs(True, i)
        delete_obs(False, i)

        # --- new fair value gaps (chart timeframe) ---
        if i >= 1 and opens[i - 1]:
            bdp = (closes[i - 1] - opens[i - 1]) / (opens[i - 1] * 100.0)
            cum_abs_bdp += abs(bdp)
            threshold = (cum_abs_bdp / i * 2.0) if (fvg_auto_threshold and i > 0) else 0.0
            if i >= 2:
                c_high, c_low = highs[i], lows[i]
                last2_high, last2_low = highs[i - 2], lows[i - 2]
                last_close = closes[i - 1]
                if c_low > last2_high and last_close > last2_high and bdp > threshold:
                    fvgs.insert(0, {"bias": BULLISH, "top": c_low, "bottom": last2_high,
                                    "bar_index": i, "time": times[i]})
                if c_high < last2_low and last_close < last2_low and -bdp > threshold:
                    fvgs.insert(0, {"bias": BEARISH, "top": c_high, "bottom": last2_low,
                                    "bar_index": i, "time": times[i]})

    e = n - 1

    def _structure(events, trend, hi_piv, lo_piv):
        s = SMCStructure(bias=trend,
                         current_high=hi_piv.current if hi_piv.current is not None else _NAN,
                         current_low=lo_piv.current if lo_piv.current is not None else _NAN)
        if events:
            idx, kind, d, lvl = events[-1]
            s.last_event = kind
            s.last_event_dir = d
            s.last_event_index = idx
            s.last_event_level = lvl
            s.event_on_this_bar = (idx == e)
        return s

    def _obs(lst, size):
        out = []
        for ob in lst[:size]:
            out.append(SMCOrderBlock(bias=ob["bias"], top=max(ob["high"], ob["low"]),
                                     bottom=min(ob["high"], ob["low"]), bar_index=ob["bar_index"],
                                     time=ob["time"]))
        return out

    fvg_out = [SMCFairValueGap(bias=g["bias"], top=max(g["top"], g["bottom"]),
                               bottom=min(g["top"], g["bottom"]), bar_index=g["bar_index"],
                               time=g["time"]) for g in fvgs]

    eqh = SMCEqual()
    if equal_high_events:
        idx, kind, lvl = equal_high_events[-1]
        eqh = SMCEqual(kind=kind, level=lvl, bar_index=idx)
    eql = SMCEqual()
    if equal_low_events:
        idx, kind, lvl = equal_low_events[-1]
        eql = SMCEqual(kind=kind, level=lvl, bar_index=idx)

    top = trailing_state["top"]
    bottom = trailing_state["bottom"]
    if top is not None and bottom is not None:
        premium = (top, 0.95 * top + 0.05 * bottom)
        equilibrium = (0.525 * top + 0.475 * bottom, 0.525 * bottom + 0.475 * top)
        discount = (0.95 * bottom + 0.05 * top, bottom)
        strong_high_label = "Strong High" if swing_trend == BEARISH else "Weak High"
        strong_low_label = "Strong Low" if swing_trend == BULLISH else "Weak Low"
    else:
        premium = equilibrium = discount = (_NAN, _NAN)
        strong_high_label = strong_low_label = ""

    pdh, pdl = _prev_period_hl(times, highs, lows, e, _day_key)
    pwh, pwl = _prev_period_hl(times, highs, lows, e, _week_key)
    pmh, pml = _prev_period_hl(times, highs, lows, e, _month_key)

    return SMCResult(
        internal=_structure(internal_events, internal_trend, internal_high, internal_low),
        swing=_structure(swing_events, swing_trend, swing_high, swing_low),
        internal_order_blocks=_obs(internal_obs, internal_ob_size),
        swing_order_blocks=_obs(swing_obs, swing_ob_size),
        fair_value_gaps=fvg_out,
        last_equal_high=eqh,
        last_equal_low=eql,
        strong_high=top if top is not None else _NAN,
        strong_high_label=strong_high_label,
        strong_low=bottom if bottom is not None else _NAN,
        strong_low_label=strong_low_label,
        premium_zone=premium,
        equilibrium_zone=equilibrium,
        discount_zone=discount,
        prev_day_high=pdh, prev_day_low=pdl,
        prev_week_high=pwh, prev_week_low=pwl,
        prev_month_high=pmh, prev_month_low=pml,
        close=closes[e], time=times[e],
    )


def smc_value(symbol=None, bar_size="15 mins", *, swing_length=50, internal_length=5,
              equal_length=3, equal_threshold=0.1, order_block_filter="atr",
              order_block_mitigation="highlow", internal_ob_size=5, swing_ob_size=5,
              confluence_filter=False, fvg_auto_threshold=True, ib=None, bars=None,
              duration=None, use_rth=True, what="TRADES", exchange="SMART", currency="USD",
              throttle=None, completed=True):
    """Full Smart Money Concepts state on the last (completed) bar as an SMCResult, or None if
    there is not enough history. Provide EITHER ``bars`` OR ``ib`` + ``symbol``."""
    if bars is None:
        if ib is None or symbol is None:
            raise ValueError("smc_value needs bars=..., or ib=... and symbol=...")
        bars = fetch_bars(ib, symbol, bar_size, duration=duration, use_rth=use_rth,
                          what=what, exchange=exchange, currency=currency, throttle=throttle)
    e = len(bars) - (2 if completed else 1)
    if e < 1:
        return None
    sub = bars[:e + 1]
    opens = [b.open for b in sub]
    highs = [b.high for b in sub]
    lows = [b.low for b in sub]
    closes = [b.close for b in sub]
    times = [b.date for b in sub]
    return smc(opens, highs, lows, closes, times, swing_length=swing_length,
               internal_length=internal_length, equal_length=equal_length,
               equal_threshold=equal_threshold, order_block_filter=order_block_filter,
               order_block_mitigation=order_block_mitigation, internal_ob_size=internal_ob_size,
               swing_ob_size=swing_ob_size, confluence_filter=confluence_filter,
               fvg_auto_threshold=fvg_auto_threshold)
