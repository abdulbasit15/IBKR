"""ATR Trailing Stop (the engine behind the popular "UT Bot") — shared, reusable.

A self-adjusting stop that trails price by a multiple of ATR and only moves in the trade's
favour until price closes through it, at which point it flips sides:

    loss = mult * ATR(period)
    if close > prev_stop and prev_close > prev_stop:  stop = max(prev_stop, close - loss)
    elif close < prev_stop and prev_close < prev_stop: stop = min(prev_stop, close + loss)
    elif close > prev_stop:                            stop = close - loss   (flip to long)
    else:                                              stop = close + loss   (flip to short)

bull = close > stop (long side). Defaults period 10, multiplier 3.0.

Two layers:

1. Pure math: ``atr_trailing_stop(highs, lows, closes, period, mult)`` -> (stop, bull) lists.
2. Config-driven value: ``atr_trailing_stop_value(...)`` -> ATRStopResult on the last bar.

Pure-Python (no numpy/pandas) so it bundles cleanly into a PyInstaller one-file exe.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..market_data import fetch_bars
from ..volatility.atr import atr


def atr_trailing_stop(highs, lows, closes, period=10, mult=3.0):
    """Return (stop, bull): stop[i] is the trailing stop, bull[i] True when price is above it.
    None during the ATR warmup."""
    n = len(closes)
    stop = [None] * n
    bull = [None] * n
    a = atr(highs, lows, closes, period)
    prev_stop = None
    for i in range(n):
        if a[i] is None:
            continue
        loss = mult * a[i]
        c = closes[i]
        if prev_stop is None:
            prev_stop = c - loss if c >= 0 else c + loss
            stop[i] = prev_stop
            bull[i] = c > prev_stop
            continue
        pc = closes[i - 1]
        if c > prev_stop and pc > prev_stop:
            cur = max(prev_stop, c - loss)
        elif c < prev_stop and pc < prev_stop:
            cur = min(prev_stop, c + loss)
        elif c > prev_stop:
            cur = c - loss
        else:
            cur = c + loss
        stop[i] = cur
        bull[i] = c > cur
        prev_stop = cur
    return stop, bull


@dataclass
class ATRStopResult:
    value: float        # the trailing stop level
    bull: bool          # price above the stop (long side)
    prev_bull: bool     # side on the prior valid bar (for flip detection)
    close: float
    time: object = None

    def __float__(self) -> float:
        return float(self.value)


def atr_trailing_stop_value(symbol=None, bar_size="15 mins", *, period=10, mult=3.0, ib=None,
                            bars=None, duration=None, use_rth=True, what="TRADES",
                            exchange="SMART", currency="USD", throttle=None, completed=True):
    """ATR trailing stop of one symbol/timeframe on the last (completed) bar as an
    ATRStopResult, or None if there is not enough history. Provide EITHER ``bars`` OR
    ``ib`` + ``symbol``."""
    if bars is None:
        if ib is None or symbol is None:
            raise ValueError("atr_trailing_stop_value needs bars=..., or ib=... and symbol=...")
        bars = fetch_bars(ib, symbol, bar_size, duration=duration, use_rth=use_rth,
                          what=what, exchange=exchange, currency=currency, throttle=throttle)
    highs = [b.high for b in bars]
    lows = [b.low for b in bars]
    closes = [b.close for b in bars]
    stop, bull = atr_trailing_stop(highs, lows, closes, period, mult)
    i = len(bars) - (2 if completed else 1)
    if i < 1 or stop[i] is None:
        return None
    prev_bull = bull[i - 1] if bull[i - 1] is not None else bull[i]
    return ATRStopResult(value=stop[i], bull=bool(bull[i]), prev_bull=bool(prev_bull),
                         close=closes[i], time=bars[i].date)
