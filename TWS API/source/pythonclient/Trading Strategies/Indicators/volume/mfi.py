"""Money Flow Index (MFI) — shared, reusable by any strategy.

A volume-weighted RSI. Using the typical price (hlc3):

    raw money flow = TP * volume
    positive / negative flow accumulate depending on whether TP rose or fell
    MFI = 100 - 100 / (1 + positive_flow / negative_flow)   over `period` bars

Overbought ~ 80, oversold ~ 20. Default period 14.

Two layers:

1. Pure math: ``mfi(highs, lows, closes, volumes, period)`` -> list aligned to inputs.
2. Config-driven value: ``mfi_value(...)`` -> MFIResult on the last completed bar.

Pure-Python (no numpy/pandas) so it bundles cleanly into a PyInstaller one-file exe.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..market_data import fetch_bars


def mfi(highs, lows, closes, volumes, period=14):
    """MFI series aligned to inputs; None for the first `period` bars."""
    period = int(period)
    n = len(closes)
    out = [None] * n
    if period <= 0 or n < period + 1:
        return out
    tp = [(highs[i] + lows[i] + closes[i]) / 3.0 for i in range(n)]
    pos = [0.0] * n
    neg = [0.0] * n
    for i in range(1, n):
        rmf = tp[i] * (volumes[i] or 0.0)
        if tp[i] > tp[i - 1]:
            pos[i] = rmf
        elif tp[i] < tp[i - 1]:
            neg[i] = rmf
    for i in range(period, n):
        p = sum(pos[i - period + 1:i + 1])
        ng = sum(neg[i - period + 1:i + 1])
        if ng == 0:
            out[i] = 100.0 if p > 0 else 50.0
        else:
            out[i] = 100.0 - 100.0 / (1.0 + p / ng)
    return out


@dataclass
class MFIResult:
    value: float
    overbought: bool
    oversold: bool
    close: float
    time: object = None

    def __float__(self) -> float:
        return float(self.value)


def mfi_value(symbol=None, bar_size="15 mins", *, period=14, overbought=80.0, oversold=20.0,
              ib=None, bars=None, duration=None, use_rth=True, what="TRADES", exchange="SMART",
              currency="USD", throttle=None, completed=True):
    """MFI of one symbol/timeframe on the last (completed) bar as an MFIResult, or None if there
    is not enough history. Provide EITHER ``bars`` OR ``ib`` + ``symbol``."""
    if bars is None:
        if ib is None or symbol is None:
            raise ValueError("mfi_value needs bars=..., or ib=... and symbol=...")
        bars = fetch_bars(ib, symbol, bar_size, duration=duration, use_rth=use_rth,
                          what=what, exchange=exchange, currency=currency, throttle=throttle)
    highs = [b.high for b in bars]
    lows = [b.low for b in bars]
    closes = [b.close for b in bars]
    volumes = [getattr(b, "volume", 0.0) for b in bars]
    series = mfi(highs, lows, closes, volumes, period)
    i = len(bars) - (2 if completed else 1)
    if i < 1 or series[i] is None:
        return None
    val = series[i]
    return MFIResult(value=val, overbought=val >= overbought, oversold=val <= oversold,
                     close=closes[i], time=bars[i].date)
