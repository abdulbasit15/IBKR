"""Support / Resistance from swing pivots, with break detection — shared, reusable.

Generic, author-neutral version of the popular pivot-based S/R scripts ("Support and
Resistance Levels with Breaks", "Support Resistance Channels", "Swing high low support &
resistance"):

  * resistance = the nearest confirmed swing high ABOVE the current close,
  * support    = the nearest confirmed swing low BELOW the current close,
  * a "break" is flagged when the close pushes through the most recent swing high (bullish
    breakout) or swing low (bearish breakdown).

Two layers:

1. Pure math: ``support_resistance(highs, lows, closes, left, right)`` -> (supports, resistances)
   lists of confirmed pivot levels (price, bar_index).
2. Config-driven value: ``support_resistance_value(...)`` -> SRResult on the last completed bar.

Pure-Python (no numpy/pandas) so it bundles cleanly into a PyInstaller one-file exe.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..market_data import fetch_bars
from .pivots import pivot_highs, pivot_lows


def support_resistance(highs, lows, closes, left=5, right=5):
    """Return (supports, resistances): each a list of (price, bar_index) for every confirmed
    swing low / swing high, in chronological order."""
    ph = pivot_highs(highs, left, right)
    pl = pivot_lows(lows, left, right)
    resistances = [(ph[i], i) for i in range(len(ph)) if ph[i] is not None]
    supports = [(pl[i], i) for i in range(len(pl)) if pl[i] is not None]
    return supports, resistances


@dataclass
class SRResult:
    support: float          # nearest swing low below price (NaN if none)
    resistance: float       # nearest swing high above price (NaN if none)
    last_swing_high: float
    last_swing_low: float
    broke_resistance: bool  # close pushed above the most recent swing high
    broke_support: bool     # close pushed below the most recent swing low
    close: float
    time: object = None


def support_resistance_value(symbol=None, bar_size="15 mins", *, left=5, right=5, ib=None,
                             bars=None, duration=None, use_rth=True, what="TRADES",
                             exchange="SMART", currency="USD", throttle=None, completed=True):
    """Nearest support/resistance + break flags on the last (completed) bar as an SRResult, or
    None if no pivots are confirmed yet. Provide EITHER ``bars`` OR ``ib`` + ``symbol``."""
    if bars is None:
        if ib is None or symbol is None:
            raise ValueError("support_resistance_value needs bars=..., or ib=... and symbol=...")
        bars = fetch_bars(ib, symbol, bar_size, duration=duration, use_rth=use_rth,
                          what=what, exchange=exchange, currency=currency, throttle=throttle)
    highs = [b.high for b in bars]
    lows = [b.low for b in bars]
    closes = [b.close for b in bars]
    supports, resistances = support_resistance(highs, lows, closes, left, right)
    e = len(bars) - (2 if completed else 1)
    if e < 1 or not supports or not resistances:
        return None
    c = closes[e]
    sup = [p for (p, idx) in supports if idx <= e]
    res = [p for (p, idx) in resistances if idx <= e]
    if not sup or not res:
        return None
    last_sh = res[-1]
    last_sl = sup[-1]
    nearest_res = min((p for p in res if p > c), default=float("nan"))
    nearest_sup = max((p for p in sup if p < c), default=float("nan"))
    return SRResult(support=nearest_sup, resistance=nearest_res, last_swing_high=last_sh,
                    last_swing_low=last_sl, broke_resistance=c > last_sh, broke_support=c < last_sl,
                    close=c, time=bars[e].date)
