"""Parabolic SAR (Stop And Reverse, Wilder) — shared, reusable by any strategy.

A trailing stop / reversal dot that accelerates toward price as a trend extends. When price
crosses the SAR the trend flips and the SAR jumps to the prior extreme point (EP). Commonly
used as a trailing stop and as a trend-direction filter.

    af (acceleration factor) starts at `step` (0.02), increases by `step` each time a new
    extreme is made, capped at `max_step` (0.2).

Two layers:

1. Pure math: ``parabolic_sar(highs, lows, step, max_step)`` -> (sar, bull) lists.
2. Config-driven value: ``parabolic_sar_value(...)`` -> SARResult on the last completed bar.

Pure-Python (no numpy/pandas) so it bundles cleanly into a PyInstaller one-file exe.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..market_data import fetch_bars


def parabolic_sar(highs, lows, step=0.02, max_step=0.2):
    """Return (sar, bull): sar[i] is the SAR value, bull[i] True if the trend is up."""
    n = len(highs)
    sar = [None] * n
    bull_out = [None] * n
    if n < 2:
        return sar, bull_out

    uptrend = highs[1] >= highs[0]
    af = step
    ep = highs[0] if uptrend else lows[0]
    sar_val = lows[0] if uptrend else highs[0]
    sar[0] = sar_val
    bull_out[0] = uptrend

    for i in range(1, n):
        prior = sar_val
        sar_val = prior + af * (ep - prior)
        if uptrend:
            # SAR may not exceed the prior two lows
            sar_val = min(sar_val, lows[i - 1], lows[i - 2] if i >= 2 else lows[i - 1])
            if lows[i] < sar_val:
                uptrend = False
                sar_val = ep
                ep = lows[i]
                af = step
            elif highs[i] > ep:
                ep = highs[i]
                af = min(af + step, max_step)
        else:
            sar_val = max(sar_val, highs[i - 1], highs[i - 2] if i >= 2 else highs[i - 1])
            if highs[i] > sar_val:
                uptrend = True
                sar_val = ep
                ep = highs[i]
                af = step
            elif lows[i] < ep:
                ep = lows[i]
                af = min(af + step, max_step)
        sar[i] = sar_val
        bull_out[i] = uptrend
    return sar, bull_out


@dataclass
class SARResult:
    value: float       # the SAR (the active trailing stop level)
    bull: bool         # True if trend is up (SAR below price)
    prev_bull: bool    # trend on the prior bar (for flip detection)
    close: float
    time: object = None

    def __float__(self) -> float:
        return float(self.value)


def parabolic_sar_value(symbol=None, bar_size="15 mins", *, step=0.02, max_step=0.2, ib=None,
                        bars=None, duration=None, use_rth=True, what="TRADES", exchange="SMART",
                        currency="USD", throttle=None, completed=True):
    """Parabolic SAR of one symbol/timeframe on the last (completed) bar as a SARResult, or
    None if there is not enough history. Provide EITHER ``bars`` OR ``ib`` + ``symbol``."""
    if bars is None:
        if ib is None or symbol is None:
            raise ValueError("parabolic_sar_value needs bars=..., or ib=... and symbol=...")
        bars = fetch_bars(ib, symbol, bar_size, duration=duration, use_rth=use_rth,
                          what=what, exchange=exchange, currency=currency, throttle=throttle)
    if len(bars) < 3:
        return None
    highs = [b.high for b in bars]
    lows = [b.low for b in bars]
    closes = [b.close for b in bars]
    sar, bull = parabolic_sar(highs, lows, step, max_step)
    i = len(bars) - (2 if completed else 1)
    if i < 1 or sar[i] is None:
        return None
    return SARResult(value=sar[i], bull=bool(bull[i]), prev_bull=bool(bull[i - 1]),
                     close=closes[i], time=bars[i].date)
