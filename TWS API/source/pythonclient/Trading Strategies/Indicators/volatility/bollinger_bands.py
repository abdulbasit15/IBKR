"""Bollinger Bands — shared, reusable by any strategy.

    basis = SMA(close, length)                 (length = 20)
    dev   = mult * stdev(close, length)        (mult = 2.0)
    upper = basis + dev
    lower = basis - dev

%B = (close - lower) / (upper - lower) locates price within the bands; bandwidth =
(upper - lower) / basis measures volatility (a low bandwidth is a "squeeze").

Two layers:

1. Pure math: ``bollinger_bands(closes, length, mult)`` -> (basis, upper, lower) lists.
2. Config-driven value: ``bollinger_value(...)`` -> BollingerResult on the last completed bar.

Pure-Python (no numpy/pandas) so it bundles cleanly into a PyInstaller one-file exe.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..market_data import fetch_bars
from ..moving_average import sma, stdev


def bollinger_bands(closes, length=20, mult=2.0):
    """Return (basis, upper, lower) series aligned to `closes`."""
    basis = sma(closes, length)
    sd = stdev(closes, length)
    n = len(closes)
    upper = [None] * n
    lower = [None] * n
    for i in range(n):
        if basis[i] is not None and sd[i] is not None:
            upper[i] = basis[i] + mult * sd[i]
            lower[i] = basis[i] - mult * sd[i]
    return basis, upper, lower


@dataclass
class BollingerResult:
    basis: float
    upper: float
    lower: float
    percent_b: float       # (close - lower) / (upper - lower)
    bandwidth: float       # (upper - lower) / basis
    close: float
    time: object = None

    @property
    def value(self) -> float:
        return float(self.basis)

    def __float__(self) -> float:
        return float(self.basis)


def bollinger_value(symbol=None, bar_size="15 mins", *, length=20, mult=2.0, ib=None, bars=None,
                    duration=None, use_rth=True, what="TRADES", exchange="SMART",
                    currency="USD", throttle=None, completed=True):
    """Bollinger Bands of one symbol/timeframe on the last (completed) bar as a BollingerResult,
    or None if there is not enough history. Provide EITHER ``bars`` OR ``ib`` + ``symbol``."""
    if bars is None:
        if ib is None or symbol is None:
            raise ValueError("bollinger_value needs bars=..., or ib=... and symbol=...")
        bars = fetch_bars(ib, symbol, bar_size, duration=duration, use_rth=use_rth,
                          what=what, exchange=exchange, currency=currency, throttle=throttle)
    closes = [b.close for b in bars]
    basis, upper, lower = bollinger_bands(closes, length, mult)
    i = len(bars) - (2 if completed else 1)
    if i < 1 or basis[i] is None:
        return None
    rng = upper[i] - lower[i]
    pb = (closes[i] - lower[i]) / rng if rng else 0.0
    bw = rng / basis[i] if basis[i] else 0.0
    return BollingerResult(basis=basis[i], upper=upper[i], lower=lower[i], percent_b=pb,
                           bandwidth=bw, close=closes[i], time=bars[i].date)
