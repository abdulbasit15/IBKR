"""Shared historical-data helper for the indicator library.

Indicators can fetch their own bars (so a strategy can ask for an indicator value by just
passing a symbol + timeframe), or a strategy can fetch once and pass `bars=` to several
indicators to avoid duplicate IBKR requests.

`ib_async` is imported lazily inside fetch_bars() so the pure-math indicators stay importable
(and unit-testable) without a broker connection.
"""
from __future__ import annotations


def default_duration(bar_size: str) -> str:
    """A reasonable reqHistoricalData duration for a given bar size."""
    b = (bar_size or "").lower()
    if "month" in b:
        return "5 Y"
    if "week" in b:
        return "2 Y"
    if "day" in b:
        return "1 Y"
    if "hour" in b:
        return "30 D"
    return "10 D"   # minute bars


def fetch_bars(ib, symbol, bar_size="15 mins", *, duration=None, use_rth=True,
               what="TRADES", exchange="SMART", currency="USD", throttle=None):
    """Qualify `symbol` and pull historical bars via ib_async. `throttle`, if given, is a
    no-arg callable invoked right before the request (e.g. a rate limiter). Returns the
    bars list (possibly empty); never raises for a data error."""
    from ib_async import Stock
    if duration is None:
        duration = default_duration(bar_size)
    contract = Stock(symbol, exchange, currency)
    try:
        ib.qualifyContracts(contract)
    except Exception:
        pass
    if throttle is not None:
        try:
            throttle()
        except Exception:
            pass
    try:
        return ib.reqHistoricalData(contract, "", duration, bar_size, what, use_rth, 1) or []
    except Exception:
        return []
