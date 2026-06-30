"""Double Exponential Moving Average (DEMA) — shared, reusable by any strategy.

DEMA(n) = 2 * EMA(price, n) - EMA(EMA(price, n), n)

DEMA reacts faster than a plain EMA/SMA of the same period because the second EMA term
subtracts most of the lag. Pure-Python (no numpy/pandas) so it bundles cleanly into a
PyInstaller one-file exe, mirroring the Supertrend indicator next to it.

Two layers (same pattern as supertrend.py):

1. Pure math: ``dema(values, period)`` -> list aligned to `values`.
2. Config-driven value: ``dema_value(...)`` — give it a symbol + timeframe + period (and an
   `ib` to fetch with, OR pre-fetched `bars`) and it returns a DemaResult for the last
   completed bar, e.g.::

       res = dema_value(ib=ib, symbol="SOXL", bar_size="15 mins", period=200)
       res.value   # the DEMA value
       float(res)  # also the DEMA value

Both EMAs are seeded at the first value (EMA/Wilder-style warmup), so allow ~2x the period
of warmup bars before relying on DEMA as a trend filter (e.g. DEMA(200) -> feed ~400+ bars).
"""
from __future__ import annotations

from dataclasses import dataclass

from .market_data import fetch_bars


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


def dema(values, period):
    """DEMA = 2*EMA - EMA(EMA). Returns a list the same length as `values`."""
    e1 = ema(values, period)
    e2 = ema(e1, period)
    out = [None] * len(values)
    for i in range(len(values)):
        if e1[i] is not None and e2[i] is not None:
            out[i] = 2.0 * e1[i] - e2[i]
    return out


@dataclass
class DemaResult:
    value: float
    close: float
    time: object = None

    def __float__(self) -> float:
        return float(self.value)


def dema_value(symbol=None, bar_size="15 mins", *, period=200, ib=None, bars=None,
               duration=None, use_rth=True, what="TRADES", exchange="SMART",
               currency="USD", throttle=None, completed=True):
    """Compute DEMA for one symbol/timeframe and return the value on the last (completed)
    bar as a DemaResult, or None if there is not enough history.

    Provide EITHER ``bars`` OR ``ib`` + ``symbol`` (see supertrend_value for the rationale)."""
    if bars is None:
        if ib is None or symbol is None:
            raise ValueError("dema_value needs bars=..., or ib=... and symbol=...")
        bars = fetch_bars(ib, symbol, bar_size, duration=duration, use_rth=use_rth,
                          what=what, exchange=exchange, currency=currency, throttle=throttle)
    i = len(bars) - (2 if completed else 1)
    if i < 1:
        return None
    series = dema([b.close for b in bars], period)
    val = series[i] if 0 <= i < len(series) else None
    if val is None:
        return None
    return DemaResult(value=val, close=bars[i].close, time=bars[i].date)
