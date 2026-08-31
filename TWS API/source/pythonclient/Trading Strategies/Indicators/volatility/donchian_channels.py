"""Donchian Channels — shared, reusable by any strategy.

    upper = highest(high, length)              (length = 20)
    lower = lowest(low, length)
    basis = (upper + lower) / 2

The basis of breakout systems (Turtle trading): a close at the upper channel is an N-bar
high breakout, at the lower channel an N-bar low breakdown.

Two layers:

1. Pure math: ``donchian_channels(highs, lows, length)`` -> (basis, upper, lower) lists.
2. Config-driven value: ``donchian_value(...)`` -> DonchianResult on the last completed bar.

Pure-Python (no numpy/pandas) so it bundles cleanly into a PyInstaller one-file exe.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..market_data import fetch_bars


def donchian_channels(highs, lows, length=20):
    """Return (basis, upper, lower) series aligned to inputs."""
    length = int(length)
    n = len(highs)
    basis = [None] * n
    upper = [None] * n
    lower = [None] * n
    for i in range(n):
        if i >= length - 1:
            hh = max(highs[i - length + 1:i + 1])
            ll = min(lows[i - length + 1:i + 1])
            upper[i] = hh
            lower[i] = ll
            basis[i] = (hh + ll) / 2.0
    return basis, upper, lower


@dataclass
class DonchianResult:
    basis: float
    upper: float
    lower: float
    at_upper: bool        # close >= upper (N-bar high breakout)
    at_lower: bool        # close <= lower (N-bar low breakdown)
    close: float
    time: object = None

    @property
    def value(self) -> float:
        return float(self.basis)

    def __float__(self) -> float:
        return float(self.basis)


def donchian_value(symbol=None, bar_size="15 mins", *, length=20, ib=None, bars=None,
                   duration=None, use_rth=True, what="TRADES", exchange="SMART",
                   currency="USD", throttle=None, completed=True):
    """Donchian Channels of one symbol/timeframe on the last (completed) bar as a
    DonchianResult, or None if there is not enough history. Provide EITHER ``bars`` OR
    ``ib`` + ``symbol``."""
    if bars is None:
        if ib is None or symbol is None:
            raise ValueError("donchian_value needs bars=..., or ib=... and symbol=...")
        bars = fetch_bars(ib, symbol, bar_size, duration=duration, use_rth=use_rth,
                          what=what, exchange=exchange, currency=currency, throttle=throttle)
    highs = [b.high for b in bars]
    lows = [b.low for b in bars]
    closes = [b.close for b in bars]
    basis, upper, lower = donchian_channels(highs, lows, length)
    i = len(bars) - (2 if completed else 1)
    if i < 1 or basis[i] is None:
        return None
    return DonchianResult(basis=basis[i], upper=upper[i], lower=lower[i],
                          at_upper=closes[i] >= upper[i], at_lower=closes[i] <= lower[i],
                          close=closes[i], time=bars[i].date)
