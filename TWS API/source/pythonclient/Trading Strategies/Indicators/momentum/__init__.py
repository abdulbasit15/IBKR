"""Momentum / oscillator indicators.

    RSI                relative strength index
    MACD               moving-average convergence/divergence
    Squeeze Momentum   LazyBear squeeze + momentum histogram
    Stochastic         %K / %D oscillator
    Stochastic RSI     stochastic applied to RSI
    WaveTrend          LazyBear smoothed momentum oscillator
    CCI                commodity channel index
    Awesome Oscillator Bill Williams momentum histogram
"""
from .awesome_oscillator import AOResult, ao_value, awesome_oscillator
from .cci import CCIResult, cci, cci_value
from .macd import MACDResult, macd, macd_value
from .rsi import RSIResult, rsi, rsi_value
from .squeeze_momentum import SqueezeResult, squeeze_momentum, squeeze_value
from .stochastic import (StochResult, stochastic, stochastic_value, stoch_rsi,
                         stoch_rsi_value)
from .wavetrend import WaveTrendResult, wavetrend, wavetrend_value

__all__ = [
    "AOResult", "ao_value", "awesome_oscillator",
    "CCIResult", "cci", "cci_value",
    "MACDResult", "macd", "macd_value",
    "RSIResult", "rsi", "rsi_value",
    "SqueezeResult", "squeeze_momentum", "squeeze_value",
    "StochResult", "stochastic", "stochastic_value", "stoch_rsi", "stoch_rsi_value",
    "WaveTrendResult", "wavetrend", "wavetrend_value",
]
