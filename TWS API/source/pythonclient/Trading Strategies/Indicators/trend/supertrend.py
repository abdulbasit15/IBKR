"""Supertrend indicator — shared, reusable by any strategy.

Two layers:

1. Pure math: ``supertrend(highs, lows, closes, atr_period, mult)`` -> (trend, line).
   trend[i] = +1 bullish / -1 bearish; line[i] = the active Supertrend value (lower band in
   an uptrend = the LONG stop, upper band in a downtrend = the SHORT stop). ATR is
   Wilder-smoothed (_rma), seeded at the first value to match the validated backtest engine.

2. Config-driven value: ``supertrend_value(...)`` — give it a symbol + timeframe + params
   (and an `ib` to fetch with, OR pre-fetched `bars`) and it returns a SupertrendResult for
   the last completed bar, e.g.::

       res = supertrend_value(ib=ib, symbol="SOXL", bar_size="15 mins",
                              atr_period=10, multiplier=3.0)
       res.value   # the Supertrend line (the active stop level)
       res.bull    # True if bullish
       float(res)  # also the line value

Pure-Python (no numpy/pandas) so it bundles cleanly into a PyInstaller one-file exe.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..market_data import fetch_bars


def _rma(values, n):
    """Wilder smoothing, seeded at the first value (matches the backtest engine)."""
    out = [None] * len(values)
    if not values:
        return out
    prev = values[0]
    out[0] = prev
    a = 1.0 / n
    for i in range(1, len(values)):
        v = values[i] if values[i] is not None else prev
        prev = prev + a * (v - prev)
        out[i] = prev
    return out


def _true_range(highs, lows, closes):
    tr = [highs[0] - lows[0]]
    for i in range(1, len(closes)):
        tr.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])))
    return tr


def supertrend(highs, lows, closes, atr_period=10, mult=3.0):
    """Return (trend, line): trend[i] = +1 bullish / -1 bearish; line[i] = the active
    Supertrend value — the lower band in an uptrend (the LONG stop) or the upper band in a
    downtrend (the SHORT stop). Identical logic to the validated backtest supertrend()."""
    n = len(closes)
    a = _rma(_true_range(highs, lows, closes), atr_period)
    up_band = [0.0] * n
    dn_band = [0.0] * n
    trend = [1] * n
    line = [0.0] * n
    for i in range(n):
        hl2 = (highs[i] + lows[i]) / 2.0
        basic_up = hl2 - mult * (a[i] or 0.0)
        basic_dn = hl2 + mult * (a[i] or 0.0)
        if i == 0:
            up_band[i] = basic_up
            dn_band[i] = basic_dn
            trend[i] = 1
            line[i] = basic_up
            continue
        pc = closes[i - 1]
        up_band[i] = basic_up if (basic_up > up_band[i - 1] or pc < up_band[i - 1]) else up_band[i - 1]
        dn_band[i] = basic_dn if (basic_dn < dn_band[i - 1] or pc > dn_band[i - 1]) else dn_band[i - 1]
        pt = trend[i - 1]
        if pt == -1 and closes[i] > dn_band[i]:
            trend[i] = 1
        elif pt == 1 and closes[i] < up_band[i]:
            trend[i] = -1
        else:
            trend[i] = pt
        line[i] = up_band[i] if trend[i] == 1 else dn_band[i]
    return trend, line


@dataclass
class SupertrendResult:
    """Supertrend on one evaluated bar. `value` is the Supertrend line (the active stop)."""
    value: float           # the Supertrend line
    trend: int             # +1 bullish, -1 bearish
    bull: bool
    prev_bull: bool        # trend on the prior bar (for flip detection)
    close: float
    time: object = None

    def __float__(self) -> float:
        return float(self.value)


def supertrend_value(symbol=None, bar_size="15 mins", *, atr_period=10, multiplier=3.0,
                     ib=None, bars=None, duration=None, use_rth=True, what="TRADES",
                     exchange="SMART", currency="USD", throttle=None, completed=True):
    """Compute the Supertrend for one symbol/timeframe and return the value on the last
    (completed) bar as a SupertrendResult, or None if there is not enough history.

    Provide EITHER ``bars`` (already-fetched history, most efficient when several indicators
    share one pull) OR ``ib`` + ``symbol`` (this fetches the history for you). ``completed``
    True evaluates the last CLOSED bar (bars[-2]); False uses the forming bar (bars[-1])."""
    if bars is None:
        if ib is None or symbol is None:
            raise ValueError("supertrend_value needs bars=..., or ib=... and symbol=...")
        bars = fetch_bars(ib, symbol, bar_size, duration=duration, use_rth=use_rth,
                          what=what, exchange=exchange, currency=currency, throttle=throttle)
    if len(bars) < atr_period + 3:
        return None
    highs = [b.high for b in bars]
    lows = [b.low for b in bars]
    closes = [b.close for b in bars]
    trend, line = supertrend(highs, lows, closes, atr_period, multiplier)
    i = len(bars) - (2 if completed else 1)
    if i < 1:
        return None
    return SupertrendResult(value=line[i], trend=trend[i], bull=trend[i] == 1,
                            prev_bull=trend[i - 1] == 1, close=closes[i], time=bars[i].date)
