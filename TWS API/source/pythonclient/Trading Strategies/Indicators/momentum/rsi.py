"""Relative Strength Index (RSI) — shared, reusable by any strategy.

Wilder's RSI: average gains / losses are smoothed with Wilder's method (seeded with the
SMA of the first `period` changes), matching TradingView's ta.rsi. RSI = 100 - 100/(1+RS),
RS = avg_gain / avg_loss (RSI = 100 when there are no losses in the window).

Two layers (same pattern as the other indicators):

1. Pure math: ``rsi(closes, period)`` -> list aligned to `closes` (None during warmup).
2. Config-driven value: ``rsi_value(...)`` — symbol + timeframe + period (and an `ib` to
   fetch with, OR pre-fetched `bars`) -> RSIResult on the last completed bar, e.g.::

       res = rsi_value(ib=ib, symbol="SOXL", bar_size="15 mins", period=14)
       res.value         # the RSI (0..100)
       res.overbought    # value >= overbought level (default 70)
       res.oversold      # value <= oversold level (default 30)

Pure-Python (no numpy/pandas) so it bundles cleanly into a PyInstaller one-file exe.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..market_data import fetch_bars


def rsi(closes, period=14):
    """Wilder RSI series aligned to `closes`; None for the first `period` bars."""
    period = int(period)
    n = len(closes)
    out = [None] * n
    if period <= 0 or n < period + 1:
        return out
    gains = [0.0] * n
    losses = [0.0] * n
    for i in range(1, n):
        ch = closes[i] - closes[i - 1]
        gains[i] = ch if ch > 0 else 0.0
        losses[i] = -ch if ch < 0 else 0.0

    def to_rsi(ag, al):
        if al == 0:
            return 100.0 if ag > 0 else 50.0   # flat or only-gains window
        rs = ag / al
        return 100.0 - 100.0 / (1.0 + rs)

    avg_gain = sum(gains[1:period + 1]) / period
    avg_loss = sum(losses[1:period + 1]) / period
    out[period] = to_rsi(avg_gain, avg_loss)
    alpha = 1.0 / period
    for i in range(period + 1, n):
        avg_gain = avg_gain + alpha * (gains[i] - avg_gain)
        avg_loss = avg_loss + alpha * (losses[i] - avg_loss)
        out[i] = to_rsi(avg_gain, avg_loss)
    return out


@dataclass
class RSIResult:
    value: float
    overbought: bool
    oversold: bool
    close: float
    time: object = None

    def __float__(self) -> float:
        return float(self.value)


def rsi_value(symbol=None, bar_size="15 mins", *, period=14, overbought=70.0, oversold=30.0,
              ib=None, bars=None, duration=None, use_rth=True, what="TRADES",
              exchange="SMART", currency="USD", throttle=None, completed=True):
    """RSI of one symbol/timeframe on the last (completed) bar as an RSIResult, or None if
    there is not enough history. Provide EITHER ``bars`` OR ``ib`` + ``symbol``."""
    if bars is None:
        if ib is None or symbol is None:
            raise ValueError("rsi_value needs bars=..., or ib=... and symbol=...")
        bars = fetch_bars(ib, symbol, bar_size, duration=duration, use_rth=use_rth,
                          what=what, exchange=exchange, currency=currency, throttle=throttle)
    closes = [b.close for b in bars]
    series = rsi(closes, period)
    i = len(bars) - (2 if completed else 1)
    if i < 1:
        return None
    val = series[i] if 0 <= i < len(series) else None
    if val is None:
        return None
    return RSIResult(value=val, overbought=val >= overbought, oversold=val <= oversold,
                     close=closes[i], time=bars[i].date)
