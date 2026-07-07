"""Order Blocks (Smart-Money-Concepts style) — shared, reusable.

Generic, author-neutral order-block detector (the named LuxAlgo / EmreKb scripts use the same
idea with proprietary tweaks):

  * a BULLISH order block is the last DOWN candle before an up-impulse that breaks structure
    (a bullish BOS/CHoCH). Its high..low range is the demand zone.
  * a BEARISH order block is the last UP candle before a down-impulse that breaks structure.
    Its high..low range is the supply zone.

A block is "mitigated" once price trades back into its zone.

Two layers:

1. Pure math: ``order_blocks(opens, highs, lows, closes, left, right)`` -> list of
   ``(ob_index, direction, top, bottom, break_index)``.
2. Config-driven value: ``order_block_value(...)`` -> OrderBlockResult for the most recent
   (optionally unmitigated) block as of the last completed bar.

Pure-Python (no numpy/pandas) so it bundles cleanly into a PyInstaller one-file exe.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..market_data import fetch_bars
from .market_structure import market_structure


def order_blocks(opens, highs, lows, closes, left=5, right=5):
    """Return a chronological list of (ob_index, direction, top, bottom, break_index)."""
    events = market_structure(highs, lows, closes, left, right)
    obs = []
    for (idx, _kind, direction, _level) in events:
        if direction == 1:
            j = idx
            while j >= 0 and not (closes[j] < opens[j]):
                j -= 1
        else:
            j = idx
            while j >= 0 and not (closes[j] > opens[j]):
                j -= 1
        if j >= 0:
            obs.append((j, direction, highs[j], lows[j], idx))
    return obs


def _is_mitigated(ob, highs, lows, end):
    idx, direction, top, bottom, _bi = ob
    for k in range(idx + 1, end + 1):
        if lows[k] <= top and highs[k] >= bottom:
            return True
    return False


@dataclass
class OrderBlockResult:
    direction: int        # +1 bullish (demand) / -1 bearish (supply)
    top: float
    bottom: float
    ob_index: int         # bar index of the order-block candle
    bars_ago: int
    mitigated: bool       # price has traded back into the zone
    close: float
    time: object = None

    @property
    def value(self) -> float:
        return float((self.top + self.bottom) / 2.0)


def order_block_value(symbol=None, bar_size="15 mins", *, left=5, right=5, only_unmitigated=True,
                      ib=None, bars=None, duration=None, use_rth=True, what="TRADES",
                      exchange="SMART", currency="USD", throttle=None, completed=True):
    """Most recent order block as of the last (completed) bar as an OrderBlockResult, or None if
    there is none. With ``only_unmitigated`` True the most recent untouched block is returned.
    Provide EITHER ``bars`` OR ``ib`` + ``symbol``."""
    if bars is None:
        if ib is None or symbol is None:
            raise ValueError("order_block_value needs bars=..., or ib=... and symbol=...")
        bars = fetch_bars(ib, symbol, bar_size, duration=duration, use_rth=use_rth,
                          what=what, exchange=exchange, currency=currency, throttle=throttle)
    opens = [b.open for b in bars]
    highs = [b.high for b in bars]
    lows = [b.low for b in bars]
    closes = [b.close for b in bars]
    e = len(bars) - (2 if completed else 1)
    if e < 1:
        return None
    obs = [ob for ob in order_blocks(opens, highs, lows, closes, left, right) if ob[4] <= e]
    for ob in reversed(obs):
        mit = _is_mitigated(ob, highs, lows, e)
        if only_unmitigated and mit:
            continue
        idx, direction, top, bottom, _bi = ob
        return OrderBlockResult(direction=direction, top=top, bottom=bottom, ob_index=idx,
                                bars_ago=e - idx, mitigated=mit, close=closes[e], time=bars[e].date)
    return None
