"""Fair Value Gaps (FVG / imbalance) — a core Smart-Money-Concepts component.

A 3-candle imbalance where price moved so fast it left a gap that was not traded through:

  * bullish FVG at bar i:  low[i] > high[i-2]   -> gap = (high[i-2] .. low[i])
  * bearish FVG at bar i:  high[i] < low[i-2]   -> gap = (high[i] .. low[i-2])

A gap is "filled" once a later bar trades back across it. These zones often act as support /
resistance on a retest.

Two layers:

1. Pure math: ``fair_value_gaps(highs, lows)`` -> list of (bar_index, direction, top, bottom).
2. Config-driven value: ``fvg_value(...)`` -> FVGResult for the most recent (optionally still
   unfilled) gap as of the last completed bar.

Pure-Python (no numpy/pandas) so it bundles cleanly into a PyInstaller one-file exe.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..market_data import fetch_bars


def fair_value_gaps(highs, lows):
    """Return a chronological list of (bar_index, direction, top, bottom): direction +1 bullish
    / -1 bearish; top/bottom are the gap edges. The gap is detected on bar i (the 3rd candle)."""
    n = len(highs)
    gaps = []
    for i in range(2, n):
        if lows[i] > highs[i - 2]:
            gaps.append((i, 1, lows[i], highs[i - 2]))
        elif highs[i] < lows[i - 2]:
            gaps.append((i, -1, lows[i - 2], highs[i]))
    return gaps


def _is_filled(gap, highs, lows, end):
    _, direction, top, bottom = gap
    idx = gap[0]
    for j in range(idx + 1, end + 1):
        if direction == 1 and lows[j] <= bottom:
            return True
        if direction == -1 and highs[j] >= top:
            return True
    return False


@dataclass
class FVGResult:
    direction: int        # +1 bullish gap / -1 bearish gap
    top: float
    bottom: float
    bar_index: int        # bar where the gap was detected (3rd candle)
    bars_ago: int
    filled: bool          # a later bar has traded back across the gap
    close: float
    time: object = None

    @property
    def value(self) -> float:
        return float((self.top + self.bottom) / 2.0)


def fvg_value(symbol=None, bar_size="15 mins", *, only_unfilled=True, ib=None, bars=None,
              duration=None, use_rth=True, what="TRADES", exchange="SMART", currency="USD",
              throttle=None, completed=True):
    """Most recent Fair Value Gap as of the last (completed) bar as an FVGResult, or None if
    there is none. With ``only_unfilled`` True the most recent STILL-OPEN gap is returned.
    Provide EITHER ``bars`` OR ``ib`` + ``symbol``."""
    if bars is None:
        if ib is None or symbol is None:
            raise ValueError("fvg_value needs bars=..., or ib=... and symbol=...")
        bars = fetch_bars(ib, symbol, bar_size, duration=duration, use_rth=use_rth,
                          what=what, exchange=exchange, currency=currency, throttle=throttle)
    highs = [b.high for b in bars]
    lows = [b.low for b in bars]
    closes = [b.close for b in bars]
    e = len(bars) - (2 if completed else 1)
    if e < 2:
        return None
    gaps = [g for g in fair_value_gaps(highs, lows) if g[0] <= e]
    for g in reversed(gaps):
        filled = _is_filled(g, highs, lows, e)
        if only_unfilled and filled:
            continue
        idx, direction, top, bottom = g
        return FVGResult(direction=direction, top=top, bottom=bottom, bar_index=idx,
                         bars_ago=e - idx, filled=filled, close=closes[e], time=bars[e].date)
    return None
