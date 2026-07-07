"""VWAP (Volume Weighted Average Price) — shared, reusable by any strategy.

VWAP = cumulative(typical_price * volume) / cumulative(volume), where typical price is hlc3.
By default the cumulator RESETS at each new session (calendar day of the bar timestamp), which
matches the intraday VWAP traders watch; pass ``anchored=False`` for a single running VWAP
over all supplied bars.

Two layers:

1. Pure math: ``vwap(highs, lows, closes, volumes, session_ids=None)`` -> list aligned to inputs.
2. Config-driven value: ``vwap_value(...)`` -> VWAPResult on the last completed bar.

Pure-Python (no numpy/pandas) so it bundles cleanly into a PyInstaller one-file exe.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..market_data import fetch_bars


def vwap(highs, lows, closes, volumes, session_ids=None):
    """VWAP series aligned to inputs. If `session_ids` is given, the cumulator resets whenever
    the session id changes (use the calendar day for an intraday session VWAP)."""
    n = len(closes)
    out = [None] * n
    cum_pv = 0.0
    cum_v = 0.0
    prev_sid = None
    for i in range(n):
        sid = session_ids[i] if session_ids is not None else None
        if session_ids is not None and sid != prev_sid:
            cum_pv = 0.0
            cum_v = 0.0
            prev_sid = sid
        tp = (highs[i] + lows[i] + closes[i]) / 3.0
        v = volumes[i] or 0.0
        cum_pv += tp * v
        cum_v += v
        out[i] = cum_pv / cum_v if cum_v else tp
    return out


def _session_id(bar):
    """Calendar-day key from a bar's timestamp (date or datetime)."""
    d = getattr(bar, "date", None)
    if d is None:
        return None
    return getattr(d, "date", lambda: d)()


@dataclass
class VWAPResult:
    value: float
    above: bool        # close >= VWAP (bullish intraday bias)
    close: float
    time: object = None

    def __float__(self) -> float:
        return float(self.value)


def vwap_value(symbol=None, bar_size="5 mins", *, anchored=True, ib=None, bars=None,
               duration=None, use_rth=True, what="TRADES", exchange="SMART", currency="USD",
               throttle=None, completed=True):
    """Session VWAP of one symbol/timeframe on the last (completed) bar as a VWAPResult, or
    None if there is not enough history. Provide EITHER ``bars`` OR ``ib`` + ``symbol``.
    With ``anchored`` True the VWAP resets each calendar day (intraday VWAP)."""
    if bars is None:
        if ib is None or symbol is None:
            raise ValueError("vwap_value needs bars=..., or ib=... and symbol=...")
        bars = fetch_bars(ib, symbol, bar_size, duration=duration, use_rth=use_rth,
                          what=what, exchange=exchange, currency=currency, throttle=throttle)
    if not bars:
        return None
    highs = [b.high for b in bars]
    lows = [b.low for b in bars]
    closes = [b.close for b in bars]
    volumes = [getattr(b, "volume", 0.0) for b in bars]
    sids = [_session_id(b) for b in bars] if anchored else None
    series = vwap(highs, lows, closes, volumes, sids)
    i = len(bars) - (2 if completed else 1)
    if i < 1 or series[i] is None:
        return None
    return VWAPResult(value=series[i], above=closes[i] >= series[i],
                      close=closes[i], time=bars[i].date)
