"""Stochastic Oscillator and Stochastic RSI — shared, reusable by any strategy.

Stochastic: %K = 100 * (close - lowest_low(n)) / (highest_high(n) - lowest_low(n)),
optionally smoothed (smooth_k), and %D = SMA(%K, d_period). Classic overbought/oversold
momentum oscillator (80 / 20).

Stochastic RSI applies the same stochastic transform to the RSI series instead of price —
a more sensitive momentum reading.

Two layers each:

1. Pure math: ``stochastic(...)`` and ``stoch_rsi(...)`` -> (%K, %D) lists.
2. Config-driven values: ``stochastic_value(...)`` / ``stoch_rsi_value(...)`` -> result on the
   last completed bar.

Pure-Python (no numpy/pandas) so it bundles cleanly into a PyInstaller one-file exe.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..market_data import fetch_bars
from .rsi import rsi


def _sma(values, period):
    """SMA that returns None where the window is incomplete or contains a None."""
    period = int(period)
    n = len(values)
    out = [None] * n
    for i in range(n):
        if i >= period - 1:
            window = values[i - period + 1:i + 1]
            if all(v is not None for v in window):
                out[i] = sum(window) / period
    return out


def _raw_stoch(highs, lows, closes, period):
    n = len(closes)
    out = [None] * n
    for i in range(n):
        if i >= period - 1:
            hh = max(highs[i - period + 1:i + 1])
            ll = min(lows[i - period + 1:i + 1])
            rng = hh - ll
            out[i] = 100.0 * (closes[i] - ll) / rng if rng else 0.0
    return out


def stochastic(highs, lows, closes, k_period=14, smooth_k=3, d_period=3):
    """Return (k, d): %K (smoothed by smooth_k) and %D = SMA(%K, d_period)."""
    raw = _raw_stoch(highs, lows, closes, k_period)
    k = _sma(raw, smooth_k) if smooth_k and smooth_k > 1 else raw
    d = _sma(k, d_period)
    return k, d


def _stoch_of_series(values, period):
    n = len(values)
    out = [None] * n
    for i in range(n):
        if i >= period - 1:
            window = [v for v in values[i - period + 1:i + 1] if v is not None]
            if len(window) == period:
                hh = max(window)
                ll = min(window)
                rng = hh - ll
                out[i] = 100.0 * (values[i] - ll) / rng if rng else 0.0
    return out


def stoch_rsi(closes, rsi_period=14, stoch_period=14, smooth_k=3, smooth_d=3):
    """Stochastic RSI -> (k, d). RSI(rsi_period) run through a stochastic(stoch_period)."""
    r = rsi(closes, rsi_period)
    raw = _stoch_of_series(r, stoch_period)
    k = _sma(raw, smooth_k) if smooth_k and smooth_k > 1 else raw
    d = _sma(k, smooth_d)
    return k, d


@dataclass
class StochResult:
    k: float
    d: float
    overbought: bool
    oversold: bool
    close: float
    time: object = None

    @property
    def value(self) -> float:
        return float(self.k)

    def __float__(self) -> float:
        return float(self.k)


def stochastic_value(symbol=None, bar_size="15 mins", *, k_period=14, smooth_k=3, d_period=3,
                     overbought=80.0, oversold=20.0, ib=None, bars=None, duration=None,
                     use_rth=True, what="TRADES", exchange="SMART", currency="USD",
                     throttle=None, completed=True):
    """Stochastic of one symbol/timeframe on the last (completed) bar as a StochResult, or None
    if there is not enough history. Provide EITHER ``bars`` OR ``ib`` + ``symbol``."""
    if bars is None:
        if ib is None or symbol is None:
            raise ValueError("stochastic_value needs bars=..., or ib=... and symbol=...")
        bars = fetch_bars(ib, symbol, bar_size, duration=duration, use_rth=use_rth,
                          what=what, exchange=exchange, currency=currency, throttle=throttle)
    highs = [b.high for b in bars]
    lows = [b.low for b in bars]
    closes = [b.close for b in bars]
    k, d = stochastic(highs, lows, closes, k_period, smooth_k, d_period)
    i = len(bars) - (2 if completed else 1)
    if i < 1 or k[i] is None or d[i] is None:
        return None
    return StochResult(k=k[i], d=d[i], overbought=k[i] >= overbought, oversold=k[i] <= oversold,
                       close=closes[i], time=bars[i].date)


def stoch_rsi_value(symbol=None, bar_size="15 mins", *, rsi_period=14, stoch_period=14,
                    smooth_k=3, smooth_d=3, overbought=80.0, oversold=20.0, ib=None, bars=None,
                    duration=None, use_rth=True, what="TRADES", exchange="SMART",
                    currency="USD", throttle=None, completed=True):
    """Stochastic RSI of one symbol/timeframe on the last (completed) bar as a StochResult, or
    None if there is not enough history. Provide EITHER ``bars`` OR ``ib`` + ``symbol``."""
    if bars is None:
        if ib is None or symbol is None:
            raise ValueError("stoch_rsi_value needs bars=..., or ib=... and symbol=...")
        bars = fetch_bars(ib, symbol, bar_size, duration=duration, use_rth=use_rth,
                          what=what, exchange=exchange, currency=currency, throttle=throttle)
    closes = [b.close for b in bars]
    k, d = stoch_rsi(closes, rsi_period, stoch_period, smooth_k, smooth_d)
    i = len(bars) - (2 if completed else 1)
    if i < 1 or k[i] is None or d[i] is None:
        return None
    return StochResult(k=k[i], d=d[i], overbought=k[i] >= overbought, oversold=k[i] <= oversold,
                       close=closes[i], time=bars[i].date)
