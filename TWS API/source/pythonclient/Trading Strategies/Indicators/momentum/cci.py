"""Commodity Channel Index (CCI) — shared, reusable by any strategy.

    typical price = (high + low + close) / 3
    CCI = (TP - SMA(TP, n)) / (0.015 * mean_abs_deviation(TP, n))

Oscillates around zero; > +100 strong up momentum / overbought, < -100 strong down /
oversold. Default period 20.

Two layers:

1. Pure math: ``cci(highs, lows, closes, period)`` -> list aligned to inputs.
2. Config-driven value: ``cci_value(...)`` -> CCIResult on the last completed bar.

Pure-Python (no numpy/pandas) so it bundles cleanly into a PyInstaller one-file exe.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..market_data import fetch_bars


def cci(highs, lows, closes, period=20):
    """CCI series aligned to inputs; None for the first period-1 bars."""
    period = int(period)
    n = len(closes)
    out = [None] * n
    if period <= 0:
        return out
    tp = [(highs[i] + lows[i] + closes[i]) / 3.0 for i in range(n)]
    for i in range(n):
        if i >= period - 1:
            window = tp[i - period + 1:i + 1]
            mean = sum(window) / period
            mad = sum(abs(x - mean) for x in window) / period
            out[i] = (tp[i] - mean) / (0.015 * mad) if mad else 0.0
    return out


@dataclass
class CCIResult:
    value: float
    overbought: bool       # value >= +100
    oversold: bool         # value <= -100
    close: float
    time: object = None

    def __float__(self) -> float:
        return float(self.value)


def cci_value(symbol=None, bar_size="15 mins", *, period=20, level=100.0, ib=None, bars=None,
              duration=None, use_rth=True, what="TRADES", exchange="SMART", currency="USD",
              throttle=None, completed=True):
    """CCI of one symbol/timeframe on the last (completed) bar as a CCIResult, or None if there
    is not enough history. Provide EITHER ``bars`` OR ``ib`` + ``symbol``."""
    if bars is None:
        if ib is None or symbol is None:
            raise ValueError("cci_value needs bars=..., or ib=... and symbol=...")
        bars = fetch_bars(ib, symbol, bar_size, duration=duration, use_rth=use_rth,
                          what=what, exchange=exchange, currency=currency, throttle=throttle)
    highs = [b.high for b in bars]
    lows = [b.low for b in bars]
    closes = [b.close for b in bars]
    series = cci(highs, lows, closes, period)
    i = len(bars) - (2 if completed else 1)
    if i < 1 or series[i] is None:
        return None
    val = series[i]
    return CCIResult(value=val, overbought=val >= level, oversold=val <= -level,
                     close=closes[i], time=bars[i].date)
