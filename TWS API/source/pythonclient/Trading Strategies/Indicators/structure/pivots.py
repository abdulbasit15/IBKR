"""Pivot highs / lows (swing points) — the foundation for price-action structure.

A pivot high at bar i is a high that is strictly greater than the `left` highs before it and
the `right` highs after it (a swing high); a pivot low is the mirror image. Equivalent to
Pine's ``ta.pivothigh`` / ``ta.pivotlow``. A pivot is only CONFIRMED `right` bars later, so the
most recent confirmable pivot is at least `right` bars back.

These swing points underpin support/resistance, market-structure (BOS/CHoCH) and order blocks.

Two layers:

1. Pure math: ``pivot_highs(highs, left, right)`` / ``pivot_lows(lows, left, right)`` -> lists
   with the pivot price at the pivot bar (None elsewhere).
2. Config-driven value: ``pivots_value(...)`` -> PivotsResult with the most recent confirmed
   swing high and low.

Pure-Python (no numpy/pandas) so it bundles cleanly into a PyInstaller one-file exe.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..market_data import fetch_bars


def pivot_highs(highs, left=5, right=5):
    """Pivot-high series: out[i] = highs[i] when bar i is a swing high, else None."""
    left = int(left)
    right = int(right)
    n = len(highs)
    out = [None] * n
    for i in range(left, n - right):
        v = highs[i]
        if all(v > highs[i - k] for k in range(1, left + 1)) and \
           all(v > highs[i + k] for k in range(1, right + 1)):
            out[i] = v
    return out


def pivot_lows(lows, left=5, right=5):
    """Pivot-low series: out[i] = lows[i] when bar i is a swing low, else None."""
    left = int(left)
    right = int(right)
    n = len(lows)
    out = [None] * n
    for i in range(left, n - right):
        v = lows[i]
        if all(v < lows[i - k] for k in range(1, left + 1)) and \
           all(v < lows[i + k] for k in range(1, right + 1)):
            out[i] = v
    return out


@dataclass
class PivotsResult:
    last_high: float            # price of the most recent confirmed swing high
    last_high_index: int        # bar index of that swing high
    bars_since_high: int
    last_low: float
    last_low_index: int
    bars_since_low: int
    close: float
    time: object = None


def pivots_value(symbol=None, bar_size="15 mins", *, left=5, right=5, ib=None, bars=None,
                 duration=None, use_rth=True, what="TRADES", exchange="SMART", currency="USD",
                 throttle=None, completed=True):
    """Most recent confirmed swing high/low of one symbol/timeframe as a PivotsResult, or None
    if no pivots are confirmed yet. Provide EITHER ``bars`` OR ``ib`` + ``symbol``."""
    if bars is None:
        if ib is None or symbol is None:
            raise ValueError("pivots_value needs bars=..., or ib=... and symbol=...")
        bars = fetch_bars(ib, symbol, bar_size, duration=duration, use_rth=use_rth,
                          what=what, exchange=exchange, currency=currency, throttle=throttle)
    highs = [b.high for b in bars]
    lows = [b.low for b in bars]
    closes = [b.close for b in bars]
    ph = pivot_highs(highs, left, right)
    pl = pivot_lows(lows, left, right)
    e = len(bars) - (2 if completed else 1)
    if e < 1:
        return None
    hi_i = next((j for j in range(e, -1, -1) if ph[j] is not None), None)
    lo_i = next((j for j in range(e, -1, -1) if pl[j] is not None), None)
    if hi_i is None or lo_i is None:
        return None
    return PivotsResult(last_high=ph[hi_i], last_high_index=hi_i, bars_since_high=e - hi_i,
                        last_low=pl[lo_i], last_low_index=lo_i, bars_since_low=e - lo_i,
                        close=closes[e], time=bars[e].date)
