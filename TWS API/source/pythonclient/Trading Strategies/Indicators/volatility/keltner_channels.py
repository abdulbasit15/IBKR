"""Keltner Channels — shared, reusable by any strategy.

    basis = EMA(close, length)                 (length = 20)
    upper = basis + mult * ATR(atr_length)     (mult = 2.0)
    lower = basis - mult * ATR(atr_length)

An ATR-based volatility envelope (smoother than Bollinger). Used for breakout/mean-reversion
and, together with Bollinger Bands, to define the TTM "squeeze".

Two layers:

1. Pure math: ``keltner_channels(highs, lows, closes, length, mult, atr_length)``
   -> (basis, upper, lower) lists.
2. Config-driven value: ``keltner_value(...)`` -> KeltnerResult on the last completed bar.

Pure-Python (no numpy/pandas) so it bundles cleanly into a PyInstaller one-file exe.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..market_data import fetch_bars
from ..moving_average import ema
from .atr import atr


def keltner_channels(highs, lows, closes, length=20, mult=2.0, atr_length=10):
    """Return (basis, upper, lower) series aligned to inputs."""
    basis = ema(closes, length)
    a = atr(highs, lows, closes, atr_length)
    n = len(closes)
    upper = [None] * n
    lower = [None] * n
    for i in range(n):
        if basis[i] is not None and a[i] is not None:
            upper[i] = basis[i] + mult * a[i]
            lower[i] = basis[i] - mult * a[i]
    return basis, upper, lower


@dataclass
class KeltnerResult:
    basis: float
    upper: float
    lower: float
    close: float
    time: object = None

    @property
    def value(self) -> float:
        return float(self.basis)

    def __float__(self) -> float:
        return float(self.basis)


def keltner_value(symbol=None, bar_size="15 mins", *, length=20, mult=2.0, atr_length=10,
                  ib=None, bars=None, duration=None, use_rth=True, what="TRADES",
                  exchange="SMART", currency="USD", throttle=None, completed=True):
    """Keltner Channels of one symbol/timeframe on the last (completed) bar as a KeltnerResult,
    or None if there is not enough history. Provide EITHER ``bars`` OR ``ib`` + ``symbol``."""
    if bars is None:
        if ib is None or symbol is None:
            raise ValueError("keltner_value needs bars=..., or ib=... and symbol=...")
        bars = fetch_bars(ib, symbol, bar_size, duration=duration, use_rth=use_rth,
                          what=what, exchange=exchange, currency=currency, throttle=throttle)
    highs = [b.high for b in bars]
    lows = [b.low for b in bars]
    closes = [b.close for b in bars]
    basis, upper, lower = keltner_channels(highs, lows, closes, length, mult, atr_length)
    i = len(bars) - (2 if completed else 1)
    if i < 1 or basis[i] is None or upper[i] is None:
        return None
    return KeltnerResult(basis=basis[i], upper=upper[i], lower=lower[i],
                         close=closes[i], time=bars[i].date)
