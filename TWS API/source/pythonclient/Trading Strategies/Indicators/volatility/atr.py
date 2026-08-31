"""Average True Range (ATR) — shared, reusable by any strategy.

True Range = max(high-low, |high-prev_close|, |low-prev_close|) (first bar = high-low).
ATR = Wilder's smoothing of TR (rma, seeded with the SMA of the first `period` TRs),
matching TradingView's ta.atr.

Two layers (same pattern as the other indicators):

1. Pure math: ``true_range(highs, lows, closes)`` and ``atr(highs, lows, closes, period)``.
2. Config-driven value: ``atr_value(...)`` -> ATRResult on the last completed bar, e.g.::

       res = atr_value(ib=ib, symbol="SOXL", bar_size="15 mins", period=14)
       res.value     # the ATR (in price units)
       res.atr_pct   # ATR as a % of close (volatility, comparable across symbols)

Pure-Python (no numpy/pandas) so it bundles cleanly into a PyInstaller one-file exe.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..market_data import fetch_bars
from ..moving_average import rma


def true_range(highs, lows, closes):
    """True Range series aligned to inputs (first bar = high - low)."""
    n = len(closes)
    tr = [0.0] * n
    if n == 0:
        return tr
    tr[0] = highs[0] - lows[0]
    for i in range(1, n):
        tr[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
    return tr


def atr(highs, lows, closes, period=14):
    """Wilder ATR series aligned to inputs; None before the seed index (period-1)."""
    return rma(true_range(highs, lows, closes), period)


@dataclass
class ATRResult:
    value: float        # ATR in price units
    atr_pct: float      # ATR / close * 100
    close: float
    time: object = None

    def __float__(self) -> float:
        return float(self.value)


def atr_value(symbol=None, bar_size="15 mins", *, period=14, ib=None, bars=None,
              duration=None, use_rth=True, what="TRADES", exchange="SMART", currency="USD",
              throttle=None, completed=True):
    """ATR of one symbol/timeframe on the last (completed) bar as an ATRResult, or None if
    there is not enough history. Provide EITHER ``bars`` OR ``ib`` + ``symbol``."""
    if bars is None:
        if ib is None or symbol is None:
            raise ValueError("atr_value needs bars=..., or ib=... and symbol=...")
        bars = fetch_bars(ib, symbol, bar_size, duration=duration, use_rth=use_rth,
                          what=what, exchange=exchange, currency=currency, throttle=throttle)
    highs = [b.high for b in bars]
    lows = [b.low for b in bars]
    closes = [b.close for b in bars]
    series = atr(highs, lows, closes, period)
    i = len(bars) - (2 if completed else 1)
    if i < 1:
        return None
    val = series[i] if 0 <= i < len(series) else None
    if val is None:
        return None
    close = closes[i]
    atr_pct = (val / close * 100.0) if close else 0.0
    return ATRResult(value=val, atr_pct=atr_pct, close=close, time=bars[i].date)
