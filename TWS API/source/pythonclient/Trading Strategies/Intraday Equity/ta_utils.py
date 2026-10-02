"""Small, dependency-free technical-indicator helpers shared by the live strategies and the
backtest so both use IDENTICAL math. All functions take a list of floats and return a list
of the same length (leading None where the indicator has no value yet)."""
from __future__ import annotations


def sma(vals, period):
    out = [None] * len(vals)
    if period <= 0:
        return out
    run = 0.0
    for i, v in enumerate(vals):
        run += v
        if i >= period:
            run -= vals[i - period]
        if i >= period - 1:
            out[i] = run / period
    return out


def ema(vals, period):
    """Standard EMA seeded with the first value (common for intraday use)."""
    out = [None] * len(vals)
    if not vals or period <= 0:
        return out
    k = 2.0 / (period + 1)
    prev = vals[0]
    out[0] = prev
    for i in range(1, len(vals)):
        prev = vals[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def rsi(closes, period=14):
    """Wilder RSI. out[i] valid for i >= period."""
    n = len(closes)
    out = [None] * n
    if n < period + 1:
        return out
    gains = 0.0
    losses = 0.0
    for i in range(1, period + 1):
        ch = closes[i] - closes[i - 1]
        gains += max(ch, 0.0)
        losses += max(-ch, 0.0)
    ag = gains / period
    al = losses / period
    out[period] = 100.0 - 100.0 / (1.0 + (ag / al if al else float("inf")))
    for i in range(period + 1, n):
        ch = closes[i] - closes[i - 1]
        ag = (ag * (period - 1) + max(ch, 0.0)) / period
        al = (al * (period - 1) + max(-ch, 0.0)) / period
        rs = ag / al if al else float("inf")
        out[i] = 100.0 - 100.0 / (1.0 + rs)
    return out


def true_range_atr(highs, lows, closes, period=14):
    """Wilder ATR array (out[i] valid for i >= period)."""
    n = len(closes)
    out = [None] * n
    if n < period + 1:
        return out
    trs = [0.0] * n
    for i in range(1, n):
        trs[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
    a = sum(trs[1:period + 1]) / period
    out[period] = a
    for i in range(period + 1, n):
        a = (a * (period - 1) + trs[i]) / period
        out[i] = a
    return out
