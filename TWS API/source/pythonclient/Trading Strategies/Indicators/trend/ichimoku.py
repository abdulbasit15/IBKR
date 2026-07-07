"""Ichimoku Kinko Hyo (Ichimoku Cloud) — shared, reusable by any strategy.

Components (default 9 / 26 / 52, displacement 26):

    Tenkan-sen (conversion) = (HH + LL) / 2 over `conversion` periods
    Kijun-sen  (base)       = (HH + LL) / 2 over `base` periods
    Senkou A   (lead 1)     = (Tenkan + Kijun) / 2, plotted `displacement` bars ahead
    Senkou B   (lead 2)     = (HH + LL) / 2 over `span_b`, plotted `displacement` bars ahead
    Chikou     (lagging)    = close, plotted `displacement` bars behind

The "cloud" overhead at the current bar is Senkou A/B computed `displacement` bars ago.
Bullish bias: price above the cloud and Tenkan above Kijun.

Two layers:

1. Pure math: ``ichimoku(highs, lows, closes, ...)`` -> dict of aligned series.
2. Config-driven value: ``ichimoku_value(...)`` -> IchimokuResult on the last completed bar.

Pure-Python (no numpy/pandas) so it bundles cleanly into a PyInstaller one-file exe.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..market_data import fetch_bars


def _midpoint(highs, lows, period):
    n = len(highs)
    out = [None] * n
    for i in range(n):
        if i >= period - 1:
            hh = max(highs[i - period + 1:i + 1])
            ll = min(lows[i - period + 1:i + 1])
            out[i] = (hh + ll) / 2.0
    return out


def ichimoku(highs, lows, closes, conversion=9, base=26, span_b=52, displacement=26):
    """Return a dict with 'tenkan', 'kijun', 'senkou_a', 'senkou_b' (all unshifted, aligned to
    inputs). The cloud overhead at bar i is senkou_a[i-displacement] / senkou_b[i-displacement]."""
    tenkan = _midpoint(highs, lows, conversion)
    kijun = _midpoint(highs, lows, base)
    n = len(closes)
    senkou_a = [None] * n
    for i in range(n):
        if tenkan[i] is not None and kijun[i] is not None:
            senkou_a[i] = (tenkan[i] + kijun[i]) / 2.0
    senkou_b = _midpoint(highs, lows, span_b)
    return {"tenkan": tenkan, "kijun": kijun, "senkou_a": senkou_a, "senkou_b": senkou_b,
            "displacement": displacement}


@dataclass
class IchimokuResult:
    tenkan: float
    kijun: float
    senkou_a: float       # current cloud edge (projected from `displacement` bars ago)
    senkou_b: float       # current cloud edge (projected from `displacement` bars ago)
    cloud_top: float
    cloud_bottom: float
    above_cloud: bool
    below_cloud: bool
    bull: bool            # above cloud AND tenkan > kijun
    close: float
    time: object = None

    @property
    def value(self) -> float:
        return float(self.kijun)

    def __float__(self) -> float:
        return float(self.kijun)


def ichimoku_value(symbol=None, bar_size="15 mins", *, conversion=9, base=26, span_b=52,
                   displacement=26, ib=None, bars=None, duration=None, use_rth=True,
                   what="TRADES", exchange="SMART", currency="USD", throttle=None, completed=True):
    """Ichimoku of one symbol/timeframe on the last (completed) bar as an IchimokuResult, or
    None if there is not enough history. Provide EITHER ``bars`` OR ``ib`` + ``symbol``."""
    if bars is None:
        if ib is None or symbol is None:
            raise ValueError("ichimoku_value needs bars=..., or ib=... and symbol=...")
        bars = fetch_bars(ib, symbol, bar_size, duration=duration, use_rth=use_rth,
                          what=what, exchange=exchange, currency=currency, throttle=throttle)
    highs = [b.high for b in bars]
    lows = [b.low for b in bars]
    closes = [b.close for b in bars]
    d = ichimoku(highs, lows, closes, conversion, base, span_b, displacement)
    i = len(bars) - (2 if completed else 1)
    if i < 1 or d["tenkan"][i] is None or d["kijun"][i] is None:
        return None
    j = i - displacement
    sa = d["senkou_a"][j] if j >= 0 else None
    sb = d["senkou_b"][j] if j >= 0 else None
    if sa is None or sb is None:
        return None
    top = max(sa, sb)
    bottom = min(sa, sb)
    close = closes[i]
    above = close > top
    below = close < bottom
    return IchimokuResult(tenkan=d["tenkan"][i], kijun=d["kijun"][i], senkou_a=sa, senkou_b=sb,
                          cloud_top=top, cloud_bottom=bottom, above_cloud=above, below_cloud=below,
                          bull=above and d["tenkan"][i] > d["kijun"][i], close=close, time=bars[i].date)
