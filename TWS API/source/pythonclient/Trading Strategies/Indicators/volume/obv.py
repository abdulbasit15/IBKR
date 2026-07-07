"""On-Balance Volume (OBV) — shared, reusable by any strategy.

Running total of volume: add the bar's volume when the close rises, subtract it when the
close falls, leave it unchanged when flat. A rising OBV confirms buying pressure; OBV
diverging from price is the classic divergence signal.

Two layers:

1. Pure math: ``obv(closes, volumes)`` -> list aligned to inputs (starts at 0).
2. Config-driven value: ``obv_value(...)`` -> OBVResult on the last completed bar.

Pure-Python (no numpy/pandas) so it bundles cleanly into a PyInstaller one-file exe.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..market_data import fetch_bars


def obv(closes, volumes):
    """OBV series aligned to inputs; out[0] = 0."""
    n = len(closes)
    out = [0.0] * n
    for i in range(1, n):
        v = volumes[i] or 0.0
        if closes[i] > closes[i - 1]:
            out[i] = out[i - 1] + v
        elif closes[i] < closes[i - 1]:
            out[i] = out[i - 1] - v
        else:
            out[i] = out[i - 1]
    return out


@dataclass
class OBVResult:
    value: float
    rising: bool       # OBV greater than the prior bar
    close: float
    time: object = None

    def __float__(self) -> float:
        return float(self.value)


def obv_value(symbol=None, bar_size="15 mins", *, ib=None, bars=None, duration=None,
              use_rth=True, what="TRADES", exchange="SMART", currency="USD", throttle=None,
              completed=True):
    """OBV of one symbol/timeframe on the last (completed) bar as an OBVResult, or None if there
    is not enough history. Provide EITHER ``bars`` OR ``ib`` + ``symbol``."""
    if bars is None:
        if ib is None or symbol is None:
            raise ValueError("obv_value needs bars=..., or ib=... and symbol=...")
        bars = fetch_bars(ib, symbol, bar_size, duration=duration, use_rth=use_rth,
                          what=what, exchange=exchange, currency=currency, throttle=throttle)
    closes = [b.close for b in bars]
    volumes = [getattr(b, "volume", 0.0) for b in bars]
    series = obv(closes, volumes)
    i = len(bars) - (2 if completed else 1)
    if i < 1:
        return None
    return OBVResult(value=series[i], rising=series[i] > series[i - 1],
                     close=closes[i], time=bars[i].date)
