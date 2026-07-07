"""WaveTrend Oscillator (LazyBear) — shared, reusable by any strategy.

A smoothed momentum oscillator built on the average price channel:

    ap   = hlc3
    esa  = EMA(ap, channel_len)                  (channel_len = 10)
    d    = EMA(|ap - esa|, channel_len)
    ci   = (ap - esa) / (0.015 * d)
    tci  = EMA(ci, average_len)                   (average_len = 21)
    wt1  = tci
    wt2  = SMA(wt1, 4)

Overbought ~ +60 (extreme +53/+60), oversold ~ -60. A wt1/wt2 cross in an extreme zone is
the classic signal.

Two layers:

1. Pure math: ``wavetrend(highs, lows, closes, channel_len, average_len)`` -> (wt1, wt2).
2. Config-driven value: ``wavetrend_value(...)`` -> WaveTrendResult on the last completed bar.

Pure-Python (no numpy/pandas) so it bundles cleanly into a PyInstaller one-file exe.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..market_data import fetch_bars
from ..moving_average import ema, sma


def wavetrend(highs, lows, closes, channel_len=10, average_len=21):
    """Return (wt1, wt2) series aligned to inputs."""
    n = len(closes)
    ap = [(highs[i] + lows[i] + closes[i]) / 3.0 for i in range(n)]
    esa = ema(ap, channel_len)
    dev = ema([abs(ap[i] - esa[i]) for i in range(n)], channel_len)
    ci = [0.0] * n
    for i in range(n):
        denom = 0.015 * dev[i] if dev[i] else 0.0
        ci[i] = (ap[i] - esa[i]) / denom if denom else 0.0
    wt1 = ema(ci, average_len)
    wt2 = sma(wt1, 4)
    return wt1, wt2


@dataclass
class WaveTrendResult:
    wt1: float
    wt2: float
    overbought: bool
    oversold: bool
    bull: bool          # wt1 > wt2
    close: float
    time: object = None

    @property
    def value(self) -> float:
        return float(self.wt1)

    def __float__(self) -> float:
        return float(self.wt1)


def wavetrend_value(symbol=None, bar_size="15 mins", *, channel_len=10, average_len=21,
                    overbought=60.0, oversold=-60.0, ib=None, bars=None, duration=None,
                    use_rth=True, what="TRADES", exchange="SMART", currency="USD",
                    throttle=None, completed=True):
    """WaveTrend of one symbol/timeframe on the last (completed) bar as a WaveTrendResult, or
    None if there is not enough history. Provide EITHER ``bars`` OR ``ib`` + ``symbol``."""
    if bars is None:
        if ib is None or symbol is None:
            raise ValueError("wavetrend_value needs bars=..., or ib=... and symbol=...")
        bars = fetch_bars(ib, symbol, bar_size, duration=duration, use_rth=use_rth,
                          what=what, exchange=exchange, currency=currency, throttle=throttle)
    closes = [b.close for b in bars]
    highs = [b.high for b in bars]
    lows = [b.low for b in bars]
    wt1, wt2 = wavetrend(highs, lows, closes, channel_len, average_len)
    i = len(bars) - (2 if completed else 1)
    if i < 1 or wt1[i] is None or wt2[i] is None:
        return None
    return WaveTrendResult(wt1=wt1[i], wt2=wt2[i], overbought=wt1[i] >= overbought,
                           oversold=wt1[i] <= oversold, bull=wt1[i] > wt2[i],
                           close=closes[i], time=bars[i].date)
