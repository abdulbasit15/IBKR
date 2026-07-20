"""Choppiness Index (CHOP) — shared, reusable by any strategy.

Measures whether the market is TRENDING or CHOPPING/consolidating (it says nothing about
direction). Range 0..100:

    CHOP = 100 * log10( sum(TR, n) / (maxHigh(n) - minLow(n)) ) / log10(n)

Rule of thumb: CHOP >= ~61.8 = choppy / range-bound (sideways), CHOP <= ~38.2 = trending
(directional). It is the natural companion to ADX for regime classification: ADX gives trend
STRENGTH, CHOP gives range-vs-directional — together they gate a trend-follower to only trade
when the tape is actually trending.

Two layers (same pattern as the other indicators):

1. Pure math: ``choppiness(highs, lows, closes, period)`` -> list aligned to inputs (None warmup).
2. Config-driven value: ``choppiness_value(...)`` -> CHOPResult on the last completed bar.

Pure-Python (no numpy/pandas) so it bundles cleanly into a PyInstaller one-file exe.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from ..market_data import fetch_bars


def _true_range(highs, lows, closes):
    tr = [highs[0] - lows[0]]
    for i in range(1, len(closes)):
        tr.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])))
    return tr


def choppiness(highs, lows, closes, period=14):
    """Choppiness Index series aligned to inputs; None for the first `period` bars."""
    period = int(period)
    n = len(closes)
    out = [None] * n
    if period <= 1 or n < period + 1:
        return out
    tr = _true_range(highs, lows, closes)
    ln = math.log10(period)
    for i in range(period, n):
        sum_tr = sum(tr[i - period + 1:i + 1])
        hi = max(highs[i - period + 1:i + 1])
        lo = min(lows[i - period + 1:i + 1])
        rng = hi - lo
        if rng > 0 and sum_tr > 0:
            out[i] = 100.0 * math.log10(sum_tr / rng) / ln
    return out


@dataclass
class CHOPResult:
    value: float           # Choppiness Index (0..100)
    choppy: bool           # value >= range_level (sideways/consolidating)
    trending: bool         # value <= trend_level (directional)
    close: float
    time: object = None

    def __float__(self) -> float:
        return float(self.value)


def choppiness_value(symbol=None, bar_size="15 mins", *, period=14, trend_level=38.2,
                     range_level=61.8, ib=None, bars=None, duration=None, use_rth=True,
                     what="TRADES", exchange="SMART", currency="USD", throttle=None,
                     completed=True):
    """Choppiness Index of one symbol/timeframe on the last (completed) bar as a CHOPResult, or
    None if there is not enough history. Provide EITHER ``bars`` OR ``ib`` + ``symbol``."""
    if bars is None:
        if ib is None or symbol is None:
            raise ValueError("choppiness_value needs bars=..., or ib=... and symbol=...")
        bars = fetch_bars(ib, symbol, bar_size, duration=duration, use_rth=use_rth,
                          what=what, exchange=exchange, currency=currency, throttle=throttle)
    highs = [b.high for b in bars]
    lows = [b.low for b in bars]
    closes = [b.close for b in bars]
    series = choppiness(highs, lows, closes, period)
    i = len(bars) - (2 if completed else 1)
    if i < 1:
        return None
    val = series[i] if 0 <= i < len(series) else None
    if val is None:
        return None
    return CHOPResult(value=val, choppy=val >= range_level, trending=val <= trend_level,
                      close=closes[i], time=bars[i].date)
