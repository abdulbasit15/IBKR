"""Chaikin Money Flow (CMF) — shared, reusable by any strategy.

    money flow multiplier = ((close - low) - (high - close)) / (high - low)
    money flow volume      = multiplier * volume
    CMF = sum(money flow volume, period) / sum(volume, period)        (period = 20)

Oscillates between -1 and +1; > 0 indicates net accumulation (buying pressure), < 0
distribution. Crossing the zero line is the common signal.

Two layers:

1. Pure math: ``chaikin_money_flow(highs, lows, closes, volumes, period)`` -> list.
2. Config-driven value: ``cmf_value(...)`` -> CMFResult on the last completed bar.

Pure-Python (no numpy/pandas) so it bundles cleanly into a PyInstaller one-file exe.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..market_data import fetch_bars


def chaikin_money_flow(highs, lows, closes, volumes, period=20):
    """CMF series aligned to inputs; None for the first period-1 bars."""
    period = int(period)
    n = len(closes)
    out = [None] * n
    if period <= 0:
        return out
    mfv = [0.0] * n
    for i in range(n):
        rng = highs[i] - lows[i]
        v = volumes[i] or 0.0
        mult = (((closes[i] - lows[i]) - (highs[i] - closes[i])) / rng) if rng else 0.0
        mfv[i] = mult * v
    for i in range(n):
        if i >= period - 1:
            vol_sum = sum((volumes[j] or 0.0) for j in range(i - period + 1, i + 1))
            out[i] = (sum(mfv[i - period + 1:i + 1]) / vol_sum) if vol_sum else 0.0
    return out


@dataclass
class CMFResult:
    value: float
    bull: bool        # CMF > 0 (accumulation)
    close: float
    time: object = None

    def __float__(self) -> float:
        return float(self.value)


def cmf_value(symbol=None, bar_size="15 mins", *, period=20, ib=None, bars=None, duration=None,
              use_rth=True, what="TRADES", exchange="SMART", currency="USD", throttle=None,
              completed=True):
    """CMF of one symbol/timeframe on the last (completed) bar as a CMFResult, or None if there
    is not enough history. Provide EITHER ``bars`` OR ``ib`` + ``symbol``."""
    if bars is None:
        if ib is None or symbol is None:
            raise ValueError("cmf_value needs bars=..., or ib=... and symbol=...")
        bars = fetch_bars(ib, symbol, bar_size, duration=duration, use_rth=use_rth,
                          what=what, exchange=exchange, currency=currency, throttle=throttle)
    highs = [b.high for b in bars]
    lows = [b.low for b in bars]
    closes = [b.close for b in bars]
    volumes = [getattr(b, "volume", 0.0) for b in bars]
    series = chaikin_money_flow(highs, lows, closes, volumes, period)
    i = len(bars) - (2 if completed else 1)
    if i < 1 or series[i] is None:
        return None
    return CMFResult(value=series[i], bull=series[i] > 0, close=closes[i], time=bars[i].date)
