"""HalfTrend (everget) — shared, reusable by any strategy.

A low-lag trend indicator that plots a stair-stepping line which stays flat until price makes
a confirmed swing in the opposite direction, then flips. It hugs price more tightly than a
moving average and is popular as a trend filter / trailing reference.

    trend == 0  -> bullish (line acts as support below price)
    trend == 1  -> bearish (line acts as resistance above price)

Faithful port of everget's HalfTrend (the channel-deviation bands, which only affect the
optional ATR arrows, are omitted; the core HalfTrend line is reproduced exactly).

Two layers:

1. Pure math: ``halftrend(highs, lows, closes, amplitude)`` -> (line, trend) lists.
2. Config-driven value: ``halftrend_value(...)`` -> HalfTrendResult on the last completed bar.

Pure-Python (no numpy/pandas) so it bundles cleanly into a PyInstaller one-file exe.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..market_data import fetch_bars


def halftrend(highs, lows, closes, amplitude=2):
    """Return (line, trend): line[i] is the HalfTrend value, trend[i] = 0 bullish / 1 bearish."""
    n = len(closes)
    line = [None] * n
    trend_out = [None] * n
    if n == 0:
        return line, trend_out

    amplitude = max(1, int(amplitude))
    trend = 0
    next_trend = 0
    max_low = lows[0]
    min_high = highs[0]
    up = 0.0
    down = 0.0
    prev_trend = None
    prev_up = None
    prev_down = None

    for i in range(n):
        lo = i - amplitude + 1
        if lo < 0:
            lo = 0
        window_h = highs[lo:i + 1]
        window_l = lows[lo:i + 1]
        high_price = max(window_h)
        low_price = min(window_l)
        highma = sum(window_h) / len(window_h)
        lowma = sum(window_l) / len(window_l)
        low_prev = lows[i - 1] if i >= 1 else lows[i]
        high_prev = highs[i - 1] if i >= 1 else highs[i]

        if next_trend == 1:
            max_low = max(low_price, max_low)
            if highma < max_low and closes[i] < low_prev:
                trend = 1
                next_trend = 0
                min_high = high_price
        else:
            min_high = min(high_price, min_high)
            if lowma > min_high and closes[i] > high_prev:
                trend = 0
                next_trend = 1
                max_low = low_price

        if trend == 0:
            if prev_trend is not None and prev_trend != 0:
                up = prev_down if prev_down is not None else down
            else:
                up = max_low if prev_up is None else max(max_low, prev_up)
            cur = up
        else:
            if prev_trend is not None and prev_trend != 1:
                down = prev_up if prev_up is not None else up
            else:
                down = min_high if prev_down is None else min(min_high, prev_down)
            cur = down

        line[i] = cur
        trend_out[i] = trend
        prev_trend = trend
        prev_up = up
        prev_down = down
    return line, trend_out


@dataclass
class HalfTrendResult:
    value: float        # the HalfTrend line
    bull: bool          # True if trend is up (line below price)
    prev_bull: bool     # trend on the prior bar (for flip detection)
    close: float
    time: object = None

    def __float__(self) -> float:
        return float(self.value)


def halftrend_value(symbol=None, bar_size="15 mins", *, amplitude=2, ib=None, bars=None,
                    duration=None, use_rth=True, what="TRADES", exchange="SMART",
                    currency="USD", throttle=None, completed=True):
    """HalfTrend of one symbol/timeframe on the last (completed) bar as a HalfTrendResult, or
    None if there is not enough history. Provide EITHER ``bars`` OR ``ib`` + ``symbol``."""
    if bars is None:
        if ib is None or symbol is None:
            raise ValueError("halftrend_value needs bars=..., or ib=... and symbol=...")
        bars = fetch_bars(ib, symbol, bar_size, duration=duration, use_rth=use_rth,
                          what=what, exchange=exchange, currency=currency, throttle=throttle)
    if len(bars) < amplitude + 2:
        return None
    highs = [b.high for b in bars]
    lows = [b.low for b in bars]
    closes = [b.close for b in bars]
    line, trend = halftrend(highs, lows, closes, amplitude)
    i = len(bars) - (2 if completed else 1)
    if i < 1 or line[i] is None:
        return None
    return HalfTrendResult(value=line[i], bull=trend[i] == 0, prev_bull=trend[i - 1] == 0,
                           close=closes[i], time=bars[i].date)
