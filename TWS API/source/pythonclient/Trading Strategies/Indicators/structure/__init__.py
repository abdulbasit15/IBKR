"""Price-action / market-structure indicators (pivots, S/R, SMC building blocks).

    Pivots             swing highs / lows (ta.pivothigh / pivotlow)
    Support/Resistance pivot-based S/R levels with break detection
    Market Structure   BOS / CHoCH (smart-money structure events)
    Fair Value Gaps    3-candle imbalances (FVG)
    Order Blocks       last opposite candle before a structure break (demand/supply zones)
    SMC                full LuxAlgo Smart Money Concepts engine (faithful port)

The pivots/S-R/market-structure/FVG/order-block modules are generic, author-neutral building
blocks. ``smc`` is a faithful headless port of LuxAlgo's Smart Money Concepts indicator.
"""
from .fair_value_gaps import FVGResult, fair_value_gaps, fvg_value
from .market_structure import (MarketStructureResult, market_structure,
                               market_structure_value)
from .order_blocks import OrderBlockResult, order_block_value, order_blocks
from .pivots import PivotsResult, pivot_highs, pivot_lows, pivots_value
from .smc import (SMCEqual, SMCFairValueGap, SMCOrderBlock, SMCResult, SMCStructure,
                  smc, smc_value)
from .support_resistance import (SRResult, support_resistance,
                                 support_resistance_value)

__all__ = [
    "FVGResult", "fair_value_gaps", "fvg_value",
    "MarketStructureResult", "market_structure", "market_structure_value",
    "OrderBlockResult", "order_block_value", "order_blocks",
    "PivotsResult", "pivot_highs", "pivot_lows", "pivots_value",
    "SMCResult", "SMCStructure", "SMCOrderBlock", "SMCFairValueGap", "SMCEqual",
    "smc", "smc_value",
    "SRResult", "support_resistance", "support_resistance_value",
]
