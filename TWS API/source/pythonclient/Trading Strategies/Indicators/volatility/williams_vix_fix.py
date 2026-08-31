"""Williams Vix Fix (CM_Williams_Vix_Fix, ChrisMoody) — shared, reusable by any strategy.

A synthetic "VIX" derived from price that spikes on capitulation, used to find market
BOTTOMS:

    wvf        = (highest(close, pd) - low) / highest(close, pd) * 100
    midLine    = SMA(wvf, bb_length)
    upperBand  = midLine + mult * stdev(wvf, bb_length)
    rangeHigh  = highest(wvf, lookback) * ph

A bottom signal fires when wvf >= upperBand OR wvf >= rangeHigh (a fear spike). Defaults
pd=22, bb_length=20, mult=2.0, lookback=50, ph=0.85 (ChrisMoody's defaults).

Two layers:

1. Pure math: ``williams_vix_fix(highs, lows, closes, ...)`` -> (wvf, upper_band, range_high).
2. Config-driven value: ``williams_vix_fix_value(...)`` -> WVFResult on the last completed bar.

Pure-Python (no numpy/pandas) so it bundles cleanly into a PyInstaller one-file exe.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..market_data import fetch_bars


def williams_vix_fix(highs, lows, closes, pd=22, bb_length=20, mult=2.0, lookback=50, ph=0.85):
    """Return (wvf, upper_band, range_high) series aligned to inputs (None during warmup)."""
    pd = int(pd)
    bb_length = int(bb_length)
    lookback = int(lookback)
    n = len(closes)
    wvf = [None] * n
    for i in range(n):
        if i >= pd - 1:
            hc = max(closes[i - pd + 1:i + 1])
            wvf[i] = ((hc - lows[i]) / hc) * 100.0 if hc else 0.0
    upper = [None] * n
    range_high = [None] * n
    for i in range(n):
        if i >= bb_length - 1 and all(wvf[j] is not None for j in range(i - bb_length + 1, i + 1)):
            window = wvf[i - bb_length + 1:i + 1]
            m = sum(window) / bb_length
            sd = (sum((x - m) ** 2 for x in window) / bb_length) ** 0.5
            upper[i] = m + mult * sd
        if i >= lookback - 1 and all(wvf[j] is not None for j in range(i - lookback + 1, i + 1)):
            range_high[i] = max(wvf[i - lookback + 1:i + 1]) * ph
    return wvf, upper, range_high


@dataclass
class WVFResult:
    value: float          # the Williams Vix Fix
    upper_band: float
    range_high: float
    bottom: bool          # wvf >= upper_band or wvf >= range_high (capitulation / bottom)
    close: float
    time: object = None

    def __float__(self) -> float:
        return float(self.value)


def williams_vix_fix_value(symbol=None, bar_size="1 day", *, pd=22, bb_length=20, mult=2.0,
                           lookback=50, ph=0.85, ib=None, bars=None, duration=None, use_rth=True,
                           what="TRADES", exchange="SMART", currency="USD", throttle=None,
                           completed=True):
    """Williams Vix Fix of one symbol/timeframe on the last (completed) bar as a WVFResult, or
    None if there is not enough history. Provide EITHER ``bars`` OR ``ib`` + ``symbol``."""
    if bars is None:
        if ib is None or symbol is None:
            raise ValueError("williams_vix_fix_value needs bars=..., or ib=... and symbol=...")
        bars = fetch_bars(ib, symbol, bar_size, duration=duration, use_rth=use_rth,
                          what=what, exchange=exchange, currency=currency, throttle=throttle)
    highs = [b.high for b in bars]
    lows = [b.low for b in bars]
    closes = [b.close for b in bars]
    wvf, upper, range_high = williams_vix_fix(highs, lows, closes, pd, bb_length, mult, lookback, ph)
    i = len(bars) - (2 if completed else 1)
    if i < 1 or wvf[i] is None:
        return None
    ub = upper[i]
    rh = range_high[i]
    bottom = (ub is not None and wvf[i] >= ub) or (rh is not None and wvf[i] >= rh)
    return WVFResult(value=wvf[i], upper_band=ub if ub is not None else float("nan"),
                     range_high=rh if rh is not None else float("nan"), bottom=bottom,
                     close=closes[i], time=bars[i].date)
