"""Local AI-assisted futures trading journal.

A self-contained, TradeZella-style journal that runs entirely on your machine:
- Excel (ZTH Trade Tracker) is the source of truth for trades.
- Auto-imports Tradovate order CSVs into round-trip trades.
- Fetches market context (Yahoo) and economic news (ForexFactory).
- Computes offline behavior/performance analytics.
- Uses the Claude API for narrative coaching and suggestions.
- Produces an HTML dashboard and writes analysis back into the workbook.

Depends only on: pandas, openpyxl, and the Python standard library.
"""

__version__ = "1.0.0"
