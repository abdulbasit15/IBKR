"""Moving averages — shared, reusable by any strategy.

Canonical home for the basic moving-average math used across the indicator library:

    sma(values, period)   simple moving average
    ema(values, period)   exponential MA (alpha = 2/(period+1), seeded at the first value)
    wma(values, period)   linearly weighted MA
    rma(values, period)   Wilder's smoothing (seeded with the SMA of the first `period`),
                          matching TradingView's ta.rma (used by RSI / ATR)

Plus a config-driven ``ma_value(...)`` that returns the moving average of one symbol/timeframe
on the last completed bar, with `ma_type` selecting sma | ema | wma | rma | dema, e.g.::

    res = ma_value(ib=ib, symbol="SOXL", bar_size="15 mins", period=50, ma_type="ema")
    res.value   # the moving-average value

Pure-Python (no numpy/pandas) so it bundles cleanly into a PyInstaller one-file exe.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .market_data import fetch_bars


def sma(values, period):
    """Simple moving average; out[i] is the mean of values[i-period+1..i] (None before)."""
    period = int(period)
    out = [None] * len(values)
    if period <= 0:
        return out
    run = 0.0
    for i, v in enumerate(values):
        run += v
        if i >= period:
            run -= values[i - period]
        if i >= period - 1:
            out[i] = run / period
    return out


def ema(values, period):
    """Exponential moving average, alpha = 2/(period+1), seeded at the first value.
    Returns a list the same length as `values` (None only for an empty input)."""
    period = int(period)
    out = [None] * len(values)
    if not values or period < 1:
        return out
    alpha = 2.0 / (period + 1.0)
    prev = values[0]
    out[0] = prev
    for i in range(1, len(values)):
        v = values[i] if values[i] is not None else prev
        prev = prev + alpha * (v - prev)
        out[i] = prev
    return out


def wma(values, period):
    """Linearly weighted moving average (most recent bar weighted highest)."""
    period = int(period)
    out = [None] * len(values)
    if period <= 0:
        return out
    denom = period * (period + 1) / 2.0
    for i in range(len(values)):
        if i >= period - 1:
            s = 0.0
            for k in range(period):
                s += values[i - period + 1 + k] * (k + 1)
            out[i] = s / denom
    return out


def rma(values, period):
    """Wilder's moving average / smoothing, seeded with the SMA of the first `period`
    values (matches TradingView ta.rma). Returns None before the seed index."""
    period = int(period)
    out = [None] * len(values)
    if period <= 0 or len(values) < period:
        return out
    seed = sum(values[:period]) / period
    out[period - 1] = seed
    prev = seed
    alpha = 1.0 / period
    for i in range(period, len(values)):
        v = values[i] if values[i] is not None else prev
        prev = prev + alpha * (v - prev)
        out[i] = prev
    return out


def hma(values, period):
    """Hull Moving Average: WMA(2*WMA(n/2) - WMA(n), sqrt(n)) — fast and smooth."""
    period = int(period)
    n = len(values)
    out = [None] * n
    if period < 2:
        return out
    half = max(1, period // 2)
    sq = max(1, int(math.isqrt(period)))
    w_half = wma(values, half)
    w_full = wma(values, period)
    diff = [None] * n
    for i in range(n):
        if w_half[i] is not None and w_full[i] is not None:
            diff[i] = 2.0 * w_half[i] - w_full[i]
    denom = sq * (sq + 1) / 2.0
    for i in range(n):
        if i >= sq - 1:
            window = diff[i - sq + 1:i + 1]
            if all(v is not None for v in window):
                s = 0.0
                for k in range(sq):
                    s += window[k] * (k + 1)
                out[i] = s / denom
    return out


def stdev(values, period):
    """Population standard deviation (divides by period), matching TradingView ta.stdev."""
    period = int(period)
    out = [None] * len(values)
    if period <= 0:
        return out
    for i in range(len(values)):
        if i >= period - 1:
            window = values[i - period + 1:i + 1]
            m = sum(window) / period
            out[i] = (sum((x - m) ** 2 for x in window) / period) ** 0.5
    return out


@dataclass
class MAResult:
    value: float
    ma_type: str
    period: int
    close: float
    time: object = None

    def __float__(self) -> float:
        return float(self.value)


def ma_value(symbol=None, bar_size="15 mins", *, period=20, ma_type="ema", ib=None, bars=None,
             duration=None, use_rth=True, what="TRADES", exchange="SMART", currency="USD",
             throttle=None, completed=True):
    """Moving average of one symbol/timeframe on the last (completed) bar as an MAResult,
    or None if there is not enough history. `ma_type` is sma | ema | wma | rma | dema.

    Provide EITHER ``bars`` OR ``ib`` + ``symbol`` (see supertrend_value for the rationale)."""
    if bars is None:
        if ib is None or symbol is None:
            raise ValueError("ma_value needs bars=..., or ib=... and symbol=...")
        bars = fetch_bars(ib, symbol, bar_size, duration=duration, use_rth=use_rth,
                          what=what, exchange=exchange, currency=currency, throttle=throttle)
    closes = [b.close for b in bars]
    t = str(ma_type).lower()
    if t == "sma":
        series = sma(closes, period)
    elif t == "ema":
        series = ema(closes, period)
    elif t == "wma":
        series = wma(closes, period)
    elif t == "rma":
        series = rma(closes, period)
    elif t == "hma":
        series = hma(closes, period)
    elif t == "dema":
        from .dema import dema as _dema
        series = _dema(closes, period)
    else:
        raise ValueError(f"unknown ma_type {ma_type!r} (use sma|ema|wma|rma|hma|dema)")
    i = len(bars) - (2 if completed else 1)
    if i < 1:
        return None
    val = series[i] if 0 <= i < len(series) else None
    if val is None:
        return None
    return MAResult(value=val, ma_type=t, period=int(period), close=bars[i].close, time=bars[i].date)
