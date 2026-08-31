"""Chandelier Exit (Chuck LeBeau) — shared, reusable by any strategy.

An ATR trailing stop hung from the highest high (long) / lowest low (short):

    long_stop  = highest(close, length) - mult * ATR(length)
    short_stop = lowest(close, length)  + mult * ATR(length)

The stop only ratchets in the trade's favour; a close through the opposite stop flips the
direction. Defaults length 22, multiplier 3.0 (LeBeau / everget). The everget ``useClose``
behaviour is reproduced (highs/lows of close); set ``use_close=False`` for high/low extremes.

Two layers:

1. Pure math: ``chandelier_exit(highs, lows, closes, length, mult, use_close)`` -> (stop, direction).
2. Config-driven value: ``chandelier_value(...)`` -> ChandelierResult on the last completed bar.

Pure-Python (no numpy/pandas) so it bundles cleanly into a PyInstaller one-file exe.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..market_data import fetch_bars
from ..volatility.atr import atr


def chandelier_exit(highs, lows, closes, length=22, mult=3.0, use_close=True):
    """Return (stop, direction): direction +1 long / -1 short; stop[i] is the active trailing
    stop for that direction. None during the ATR warmup."""
    length = int(length)
    n = len(closes)
    stop = [None] * n
    direction = [None] * n
    a = atr(highs, lows, closes, length)

    long_prev = None
    short_prev = None
    dir_cur = 1
    for i in range(n):
        if a[i] is None or i < length - 1:
            continue
        hi_src = max((closes if use_close else highs)[i - length + 1:i + 1])
        lo_src = min((closes if use_close else lows)[i - length + 1:i + 1])
        loss = mult * a[i]
        long_stop = hi_src - loss
        short_stop = lo_src + loss
        if long_prev is not None and closes[i - 1] > long_prev:
            long_stop = max(long_stop, long_prev)
        if short_prev is not None and closes[i - 1] < short_prev:
            short_stop = min(short_stop, short_prev)
        if short_prev is not None and closes[i] > short_prev:
            dir_cur = 1
        elif long_prev is not None and closes[i] < long_prev:
            dir_cur = -1
        stop[i] = long_stop if dir_cur == 1 else short_stop
        direction[i] = dir_cur
        long_prev = long_stop
        short_prev = short_stop
    return stop, direction


@dataclass
class ChandelierResult:
    value: float        # the active trailing stop
    bull: bool          # direction is long
    prev_bull: bool     # direction on the prior valid bar (for flip detection)
    close: float
    time: object = None

    def __float__(self) -> float:
        return float(self.value)


def chandelier_value(symbol=None, bar_size="15 mins", *, length=22, mult=3.0, use_close=True,
                     ib=None, bars=None, duration=None, use_rth=True, what="TRADES",
                     exchange="SMART", currency="USD", throttle=None, completed=True):
    """Chandelier Exit of one symbol/timeframe on the last (completed) bar as a
    ChandelierResult, or None if there is not enough history. Provide EITHER ``bars`` OR
    ``ib`` + ``symbol``."""
    if bars is None:
        if ib is None or symbol is None:
            raise ValueError("chandelier_value needs bars=..., or ib=... and symbol=...")
        bars = fetch_bars(ib, symbol, bar_size, duration=duration, use_rth=use_rth,
                          what=what, exchange=exchange, currency=currency, throttle=throttle)
    highs = [b.high for b in bars]
    lows = [b.low for b in bars]
    closes = [b.close for b in bars]
    stop, direction = chandelier_exit(highs, lows, closes, length, mult, use_close)
    i = len(bars) - (2 if completed else 1)
    if i < 1 or stop[i] is None:
        return None
    prev_dir = direction[i - 1] if direction[i - 1] is not None else direction[i]
    return ChandelierResult(value=stop[i], bull=direction[i] == 1, prev_bull=prev_dir == 1,
                            close=closes[i], time=bars[i].date)
