"""Shared technical-indicator library for ALL Trading Strategies bots.

Lives at ``Trading Strategies/Indicators`` so any strategy family (Indicator Strategies,
Intraday Equity, ...) can reuse the same indicators. Add this folder's PARENT
(``Trading Strategies``) to sys.path, then import either from a category subpackage or from
the package root (everything is re-exported here for convenience)::

    from Indicators.trend.supertrend import supertrend_value
    from Indicators.momentum import rsi_value, macd_value
    from Indicators import supertrend_value, atr_value      # also works (root re-export)

Indicators are organised into category subpackages:

    trend/        supertrend, adx, parabolic_sar, halftrend, ichimoku
    momentum/     rsi, macd, squeeze_momentum, stochastic, stoch_rsi, wavetrend, cci,
                  awesome_oscillator
    volatility/   atr, bollinger_bands, keltner_channels, donchian_channels, williams_vix_fix
    volume/       vwap, obv, mfi, chaikin_money_flow
    exits/        chandelier_exit, atr_trailing_stop
    structure/    pivots, support_resistance, market_structure (BOS/CHoCH), fair_value_gaps,
                  order_blocks, smc (full LuxAlgo Smart Money Concepts port)
    sessions/     killzones (ICT)

Shared building blocks live at the package root: ``market_data`` (history fetch),
``moving_average`` (sma / ema / wma / rma / hma / stdev + ma_value), and ``dema``.

Each indicator exposes two layers:
  * a pure-math function (e.g. ``supertrend``, ``rsi``, ``macd``) on price lists, and
  * a config-driven ``*_value`` helper that takes a symbol + timeframe + params (and an
    `ib` to fetch with, or pre-fetched `bars`) and returns the value on the last bar.

Pure-Python (no numpy/pandas); ib_async is imported lazily only when fetching data.
"""
from __future__ import annotations

# --- shared building blocks (package root) ---
from .market_data import default_duration, fetch_bars
from .moving_average import (MAResult, ema, hma, ma_value, rma, sma, stdev, wma)
from .dema import DemaResult, dema, dema_value

# --- trend ---
from .trend import (ADXResult, HalfTrendResult, IchimokuResult, SARResult,
                    SupertrendResult, adx, adx_value, halftrend, halftrend_value,
                    ichimoku, ichimoku_value, parabolic_sar, parabolic_sar_value,
                    supertrend, supertrend_value)

# --- momentum ---
from .momentum import (AOResult, CCIResult, MACDResult, RSIResult, SqueezeResult,
                       StochResult, WaveTrendResult, ao_value, awesome_oscillator,
                       cci, cci_value, macd, macd_value, rsi, rsi_value,
                       squeeze_momentum, squeeze_value, stochastic, stochastic_value,
                       stoch_rsi, stoch_rsi_value, wavetrend, wavetrend_value)

# --- volatility ---
from .volatility import (ATRResult, BollingerResult, DonchianResult, KeltnerResult,
                         WVFResult, atr, atr_value, bollinger_bands, bollinger_value,
                         donchian_channels, donchian_value, keltner_channels,
                         keltner_value, true_range, williams_vix_fix, williams_vix_fix_value)

# --- volume ---
from .volume import (CMFResult, MFIResult, OBVResult, VWAPResult, chaikin_money_flow,
                     cmf_value, mfi, mfi_value, obv, obv_value, vwap, vwap_value)

# --- exits ---
from .exits import (ATRStopResult, ChandelierResult, atr_trailing_stop,
                    atr_trailing_stop_value, chandelier_exit, chandelier_value)

# --- structure (price action / smart money) ---
from .structure import (FVGResult, MarketStructureResult, OrderBlockResult, PivotsResult,
                        SMCEqual, SMCFairValueGap, SMCOrderBlock, SMCResult, SMCStructure,
                        SRResult, fair_value_gaps, fvg_value, market_structure,
                        market_structure_value, order_block_value, order_blocks,
                        pivot_highs, pivot_lows, pivots_value, smc, smc_value,
                        support_resistance, support_resistance_value)

# --- sessions ---
from .sessions import DEFAULT_ZONES, KillzoneResult, killzone_at, killzone_value

__all__ = [
    # shared
    "fetch_bars", "default_duration",
    "sma", "ema", "wma", "rma", "hma", "stdev", "ma_value", "MAResult",
    "dema", "dema_value", "DemaResult",
    # trend
    "supertrend", "supertrend_value", "SupertrendResult",
    "adx", "adx_value", "ADXResult",
    "parabolic_sar", "parabolic_sar_value", "SARResult",
    "halftrend", "halftrend_value", "HalfTrendResult",
    "ichimoku", "ichimoku_value", "IchimokuResult",
    # momentum
    "rsi", "rsi_value", "RSIResult",
    "macd", "macd_value", "MACDResult",
    "squeeze_momentum", "squeeze_value", "SqueezeResult",
    "stochastic", "stochastic_value", "stoch_rsi", "stoch_rsi_value", "StochResult",
    "wavetrend", "wavetrend_value", "WaveTrendResult",
    "cci", "cci_value", "CCIResult",
    "awesome_oscillator", "ao_value", "AOResult",
    # volatility
    "atr", "true_range", "atr_value", "ATRResult",
    "bollinger_bands", "bollinger_value", "BollingerResult",
    "keltner_channels", "keltner_value", "KeltnerResult",
    "donchian_channels", "donchian_value", "DonchianResult",
    "williams_vix_fix", "williams_vix_fix_value", "WVFResult",
    # volume
    "vwap", "vwap_value", "VWAPResult",
    "obv", "obv_value", "OBVResult",
    "mfi", "mfi_value", "MFIResult",
    "chaikin_money_flow", "cmf_value", "CMFResult",
    # exits
    "chandelier_exit", "chandelier_value", "ChandelierResult",
    "atr_trailing_stop", "atr_trailing_stop_value", "ATRStopResult",
    # structure (price action / smart money)
    "pivot_highs", "pivot_lows", "pivots_value", "PivotsResult",
    "support_resistance", "support_resistance_value", "SRResult",
    "market_structure", "market_structure_value", "MarketStructureResult",
    "fair_value_gaps", "fvg_value", "FVGResult",
    "order_blocks", "order_block_value", "OrderBlockResult",
    "smc", "smc_value", "SMCResult", "SMCStructure", "SMCOrderBlock",
    "SMCFairValueGap", "SMCEqual",
    # sessions
    "killzone_at", "killzone_value", "KillzoneResult", "DEFAULT_ZONES",
]
