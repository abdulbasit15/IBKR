"""Shared technical-indicator library for ALL Trading Strategies bots.

Lives at ``Trading Strategies/Indicators`` so any strategy family (Indicator Strategies,
Intraday Equity, ...) can reuse the same indicators. Add this folder's PARENT
(``Trading Strategies``) to sys.path, then::

    from Indicators.supertrend import supertrend_value
    from Indicators.dema import dema_value

Each indicator exposes two layers:
  * a pure-math function (e.g. ``supertrend``, ``dema``) on price lists, and
  * a config-driven ``*_value`` helper that takes a symbol + timeframe + params (and an
    `ib` to fetch with, or pre-fetched `bars`) and returns the value on the last bar.

Pure-Python (no numpy/pandas); ib_async is imported lazily only when fetching data.
"""
from __future__ import annotations

from .dema import DemaResult, dema, dema_value, ema
from .market_data import default_duration, fetch_bars
from .supertrend import SupertrendResult, supertrend, supertrend_value

__all__ = [
    "supertrend", "supertrend_value", "SupertrendResult",
    "dema", "ema", "dema_value", "DemaResult",
    "fetch_bars", "default_duration",
]
