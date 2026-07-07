"""Awesome Oscillator (Bill Williams) — shared, reusable by any strategy.

    median price = (high + low) / 2
    AO = SMA(median, fast) - SMA(median, slow)     (default fast 5, slow 34)

Momentum histogram around zero; the colour ("up" = current bar > prior bar) drives the
classic zero-line cross and saucer signals. AO > 0 is bullish momentum.

Two layers:

1. Pure math: ``awesome_oscillator(highs, lows, fast, slow)`` -> list aligned to inputs.
2. Config-driven value: ``ao_value(...)`` -> AOResult on the last completed bar.

Pure-Python (no numpy/pandas) so it bundles cleanly into a PyInstaller one-file exe.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..market_data import fetch_bars
from ..moving_average import sma


def awesome_oscillator(highs, lows, fast=5, slow=34):
    """AO series aligned to inputs; None until the slow SMA is available."""
    n = len(highs)
    median = [(highs[i] + lows[i]) / 2.0 for i in range(n)]
    f = sma(median, fast)
    s = sma(median, slow)
    out = [None] * n
    for i in range(n):
        if f[i] is not None and s[i] is not None:
            out[i] = f[i] - s[i]
    return out


@dataclass
class AOResult:
    value: float
    bull: bool        # AO > 0
    rising: bool      # AO greater than the prior bar (histogram colour)
    close: float
    time: object = None

    def __float__(self) -> float:
        return float(self.value)


def ao_value(symbol=None, bar_size="15 mins", *, fast=5, slow=34, ib=None, bars=None,
             duration=None, use_rth=True, what="TRADES", exchange="SMART", currency="USD",
             throttle=None, completed=True):
    """Awesome Oscillator of one symbol/timeframe on the last (completed) bar as an AOResult,
    or None if there is not enough history. Provide EITHER ``bars`` OR ``ib`` + ``symbol``."""
    if bars is None:
        if ib is None or symbol is None:
            raise ValueError("ao_value needs bars=..., or ib=... and symbol=...")
        bars = fetch_bars(ib, symbol, bar_size, duration=duration, use_rth=use_rth,
                          what=what, exchange=exchange, currency=currency, throttle=throttle)
    highs = [b.high for b in bars]
    lows = [b.low for b in bars]
    closes = [b.close for b in bars]
    series = awesome_oscillator(highs, lows, fast, slow)
    i = len(bars) - (2 if completed else 1)
    if i < 1 or series[i] is None:
        return None
    rising = series[i - 1] is not None and series[i] > series[i - 1]
    return AOResult(value=series[i], bull=series[i] > 0, rising=rising,
                    close=closes[i], time=bars[i].date)
