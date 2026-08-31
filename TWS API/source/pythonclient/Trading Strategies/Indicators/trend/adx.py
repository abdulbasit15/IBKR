"""ADX / DMI (Average Directional Index, Wilder) — shared, reusable by any strategy.

Measures trend STRENGTH (ADX) and DIRECTION (+DI vs -DI):

    +DM / -DM -> Wilder-smoothed -> +DI / -DI
    DX  = 100 * |+DI - -DI| / (+DI + -DI)
    ADX = Wilder average of DX

Rule of thumb: ADX >= 25 is a trending market, < 20 is choppy/range-bound; +DI > -DI is
bullish direction. Matches the classic Wilder implementation.

Two layers:

1. Pure math: ``adx(highs, lows, closes, period)`` -> (plus_di, minus_di, adx) lists.
2. Config-driven value: ``adx_value(...)`` -> ADXResult on the last completed bar.

Pure-Python (no numpy/pandas) so it bundles cleanly into a PyInstaller one-file exe.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..market_data import fetch_bars


def adx(highs, lows, closes, period=14):
    """Return (plus_di, minus_di, adx) series aligned to inputs (None during warmup)."""
    period = int(period)
    n = len(closes)
    plus_di = [None] * n
    minus_di = [None] * n
    adx_out = [None] * n
    if period <= 0 or n < period + 1:
        return plus_di, minus_di, adx_out

    tr = [0.0] * n
    plus_dm = [0.0] * n
    minus_dm = [0.0] * n
    for i in range(1, n):
        up = highs[i] - highs[i - 1]
        dn = lows[i - 1] - lows[i]
        plus_dm[i] = up if (up > dn and up > 0) else 0.0
        minus_dm[i] = dn if (dn > up and dn > 0) else 0.0
        tr[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))

    s_tr = [None] * n
    s_pdm = [None] * n
    s_mdm = [None] * n
    s_tr[period] = sum(tr[1:period + 1])
    s_pdm[period] = sum(plus_dm[1:period + 1])
    s_mdm[period] = sum(minus_dm[1:period + 1])
    for i in range(period + 1, n):
        s_tr[i] = s_tr[i - 1] - s_tr[i - 1] / period + tr[i]
        s_pdm[i] = s_pdm[i - 1] - s_pdm[i - 1] / period + plus_dm[i]
        s_mdm[i] = s_mdm[i - 1] - s_mdm[i - 1] / period + minus_dm[i]

    dx = [None] * n
    for i in range(period, n):
        rng = s_tr[i]
        if rng:
            pdi = 100.0 * s_pdm[i] / rng
            mdi = 100.0 * s_mdm[i] / rng
            plus_di[i] = pdi
            minus_di[i] = mdi
            denom = pdi + mdi
            dx[i] = 100.0 * abs(pdi - mdi) / denom if denom else 0.0

    first = period * 2 - 1
    if first < n:
        seed_vals = [dx[j] for j in range(period, first + 1) if dx[j] is not None]
        if len(seed_vals) == period:
            adx_out[first] = sum(seed_vals) / period
            for i in range(first + 1, n):
                if dx[i] is not None and adx_out[i - 1] is not None:
                    adx_out[i] = (adx_out[i - 1] * (period - 1) + dx[i]) / period
    return plus_di, minus_di, adx_out


@dataclass
class ADXResult:
    value: float          # ADX (trend strength, 0..100)
    plus_di: float
    minus_di: float
    bull: bool            # +DI > -DI
    trending: bool        # ADX >= trend_level
    close: float
    time: object = None

    def __float__(self) -> float:
        return float(self.value)


def adx_value(symbol=None, bar_size="15 mins", *, period=14, trend_level=25.0, ib=None,
              bars=None, duration=None, use_rth=True, what="TRADES", exchange="SMART",
              currency="USD", throttle=None, completed=True):
    """ADX/DMI of one symbol/timeframe on the last (completed) bar as an ADXResult, or None if
    there is not enough history. Provide EITHER ``bars`` OR ``ib`` + ``symbol``."""
    if bars is None:
        if ib is None or symbol is None:
            raise ValueError("adx_value needs bars=..., or ib=... and symbol=...")
        bars = fetch_bars(ib, symbol, bar_size, duration=duration, use_rth=use_rth,
                          what=what, exchange=exchange, currency=currency, throttle=throttle)
    highs = [b.high for b in bars]
    lows = [b.low for b in bars]
    closes = [b.close for b in bars]
    pdi, mdi, ax = adx(highs, lows, closes, period)
    i = len(bars) - (2 if completed else 1)
    if i < 1 or i >= len(ax) or ax[i] is None or pdi[i] is None:
        return None
    return ADXResult(value=ax[i], plus_di=pdi[i], minus_di=mdi[i], bull=pdi[i] > mdi[i],
                     trending=ax[i] >= trend_level, close=closes[i], time=bars[i].date)
