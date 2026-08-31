"""MACD (Moving Average Convergence Divergence) — shared, reusable by any strategy.

    macd_line = EMA(close, fast) - EMA(close, slow)
    signal    = EMA(macd_line, signal)
    histogram = macd_line - signal

Defaults fast=12, slow=26, signal=9 (classic). EMA is the shared moving_average.ema (seeded
at the first value), so allow some warmup before relying on the values.

Two layers (same pattern as the other indicators):

1. Pure math: ``macd(closes, fast, slow, signal)`` -> (macd_line, signal_line, histogram).
2. Config-driven value: ``macd_value(...)`` -> MACDResult on the last completed bar, e.g.::

       res = macd_value(ib=ib, symbol="SOXL", bar_size="15 mins")
       res.macd, res.signal, res.hist
       res.positive   # histogram > 0 (macd above signal)
       res.rising     # histogram > previous bar's histogram

Pure-Python (no numpy/pandas) so it bundles cleanly into a PyInstaller one-file exe.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..market_data import fetch_bars
from ..moving_average import ema


def macd(closes, fast=12, slow=26, signal=9):
    """Return (macd_line, signal_line, histogram), each aligned to `closes`."""
    ema_fast = ema(closes, fast)
    ema_slow = ema(closes, slow)
    n = len(closes)
    macd_line = [None] * n
    for i in range(n):
        if ema_fast[i] is not None and ema_slow[i] is not None:
            macd_line[i] = ema_fast[i] - ema_slow[i]
    signal_line = ema(macd_line, signal)
    hist = [None] * n
    for i in range(n):
        if macd_line[i] is not None and signal_line[i] is not None:
            hist[i] = macd_line[i] - signal_line[i]
    return macd_line, signal_line, hist


@dataclass
class MACDResult:
    macd: float
    signal: float
    hist: float
    positive: bool      # hist > 0 (macd above signal)
    rising: bool        # hist > previous bar's hist
    close: float
    time: object = None

    def __float__(self) -> float:
        return float(self.hist)


def macd_value(symbol=None, bar_size="15 mins", *, fast=12, slow=26, signal=9, ib=None,
               bars=None, duration=None, use_rth=True, what="TRADES", exchange="SMART",
               currency="USD", throttle=None, completed=True):
    """MACD of one symbol/timeframe on the last (completed) bar as a MACDResult, or None if
    there is not enough history. Provide EITHER ``bars`` OR ``ib`` + ``symbol``."""
    if bars is None:
        if ib is None or symbol is None:
            raise ValueError("macd_value needs bars=..., or ib=... and symbol=...")
        bars = fetch_bars(ib, symbol, bar_size, duration=duration, use_rth=use_rth,
                          what=what, exchange=exchange, currency=currency, throttle=throttle)
    closes = [b.close for b in bars]
    macd_line, signal_line, hist = macd(closes, fast, slow, signal)
    i = len(bars) - (2 if completed else 1)
    if i < 1:
        return None
    if macd_line[i] is None or signal_line[i] is None or hist[i] is None:
        return None
    prev_hist = hist[i - 1] if (i - 1 >= 0 and hist[i - 1] is not None) else 0.0
    return MACDResult(macd=macd_line[i], signal=signal_line[i], hist=hist[i],
                      positive=hist[i] > 0, rising=hist[i] > prev_hist,
                      close=closes[i], time=bars[i].date)
