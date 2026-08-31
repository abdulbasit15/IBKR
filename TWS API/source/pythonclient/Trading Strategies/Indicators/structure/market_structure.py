"""Market Structure: BOS / CHoCH (Smart-Money-Concepts style) — shared, reusable.

Generic, author-neutral version of the structure engine behind the SMC / "Market Structure
Break & Order Blocks" scripts. Using confirmed swing pivots:

  * Trend is up when swings make higher highs AND higher lows; down on lower highs / lower lows.
  * BOS  (Break of Structure)      = price breaks the last swing in the SAME direction as the
                                      prevailing trend (trend continuation).
  * CHoCH (Change of Character)     = price breaks the last swing AGAINST the prevailing trend
                                      (the first sign of a reversal).

Two layers:

1. Pure math: ``market_structure(highs, lows, closes, left, right)`` -> list of events
   ``(bar_index, 'BOS'|'CHoCH', +1|-1, level)``.
2. Config-driven value: ``market_structure_value(...)`` -> MarketStructureResult on the last bar.

Pure-Python (no numpy/pandas) so it bundles cleanly into a PyInstaller one-file exe.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..market_data import fetch_bars
from .pivots import pivot_highs, pivot_lows


def market_structure(highs, lows, closes, left=5, right=5):
    """Return a chronological list of structure events: (bar_index, kind, direction, level),
    where kind is 'BOS' or 'CHoCH', direction is +1 (bullish) / -1 (bearish), and level is the
    swing price that was broken. A swing becomes usable `right` bars after it prints."""
    ph = pivot_highs(highs, left, right)
    pl = pivot_lows(lows, left, right)
    n = len(closes)
    # confirmation index -> swing price, per side (a pivot at i is known only at i+right)
    conf_high = {}
    conf_low = {}
    for i in range(n):
        if ph[i] is not None:
            conf_high[i + right] = ph[i]
        if pl[i] is not None:
            conf_low[i + right] = pl[i]

    events = []
    last_high = None
    last_low = None
    trend = 0  # +1 up, -1 down, 0 undetermined
    for i in range(n):
        if i in conf_high:
            last_high = conf_high[i]
        if i in conf_low:
            last_low = conf_low[i]
        c = closes[i]
        if last_high is not None and c > last_high:
            kind = "BOS" if trend == 1 else "CHoCH"
            events.append((i, kind, 1, last_high))
            trend = 1
            last_high = None  # consumed; wait for the next swing high
        elif last_low is not None and c < last_low:
            kind = "BOS" if trend == -1 else "CHoCH"
            events.append((i, kind, -1, last_low))
            trend = -1
            last_low = None
    return events


@dataclass
class MarketStructureResult:
    trend: int               # +1 up / -1 down / 0 undetermined (after the latest event)
    last_event: str          # 'BOS' | 'CHoCH' | '' (none yet)
    last_event_dir: int      # +1 / -1 / 0
    last_event_index: int    # bar index of the latest event (-1 if none)
    last_event_level: float  # the swing price that was broken (NaN if none)
    event_on_this_bar: bool  # the latest event occurred on the evaluated bar
    close: float
    time: object = None


def market_structure_value(symbol=None, bar_size="15 mins", *, left=5, right=5, ib=None,
                           bars=None, duration=None, use_rth=True, what="TRADES",
                           exchange="SMART", currency="USD", throttle=None, completed=True):
    """Market structure on the last (completed) bar as a MarketStructureResult, or None if no
    structure event has formed yet. Provide EITHER ``bars`` OR ``ib`` + ``symbol``."""
    if bars is None:
        if ib is None or symbol is None:
            raise ValueError("market_structure_value needs bars=..., or ib=... and symbol=...")
        bars = fetch_bars(ib, symbol, bar_size, duration=duration, use_rth=use_rth,
                          what=what, exchange=exchange, currency=currency, throttle=throttle)
    highs = [b.high for b in bars]
    lows = [b.low for b in bars]
    closes = [b.close for b in bars]
    events = market_structure(highs, lows, closes, left, right)
    e = len(bars) - (2 if completed else 1)
    if e < 1:
        return None
    past = [ev for ev in events if ev[0] <= e]
    if not past:
        return None
    idx, kind, direction, level = past[-1]
    return MarketStructureResult(trend=direction, last_event=kind, last_event_dir=direction,
                                 last_event_index=idx, last_event_level=level,
                                 event_on_this_bar=(idx == e), close=closes[e], time=bars[e].date)
