# Scalping v2 strategies on liquid stocks & ETFs
*2026-10-09. Full tables are in `Stocks_Report.html`. Code: `download_stocks_5m_rth.py`, `backtest_stocks.py`,
`crosscheck_etf_vs_futures.py`, `make_stock_report.py`.*

## Test setup
- **Symbols (13):**
  - ETFs: SPY, QQQ, IWM, DIA
  - Stocks: AAPL, MSFT, NVDA, AMZN, META, GOOGL, TSLA, AMD, AVGO
- **Data:** IB 5-min RTH bars, **2024-10-10 → 2026-10-09** (501 sessions).
- **Strategy rules:** the same engine, windows and parameters as `scalping_v2.json`, with every strategy run on every symbol.
- **Costs:** 1¢ slippage per fill plus $0.0035/share per side. A stress test doubles this to 2¢ plus $0.005/share.
- **Periods:** Y1 is Oct 2024–Sep 2025. The futures research never saw that year, so it's a true out-of-sample test. Y2 is Oct 2025–Oct 2026, which overlaps the period used to pick the strategies.

## Answer: not as-is — 2 of the 4 strategies partly transfer
| Strategy | Index ETFs: avg R/trade (Y1 / Y2) | Single stocks: avg R/trade (Y1 / Y2) | Verdict |
|---|---|---|---|
| **IB Trend Breakout** | −0.030 (−0.07 / +0.02) | **+0.064 (+0.06 / +0.07)**, PF 1.18, n=501 | ✅ works on large-cap **stocks** in both years; mixed on ETFs (SPY ✓, QQQ ✓, DIA/IWM ✗) |
| **ORB Second Break** | **+0.054 (+0.01 / +0.09)**, PF 1.19, n=343 | −0.008 (−0.11 / +0.09) | ✅ on QQQ & IWM; ✗ on SPY; stocks only in Y2 |
| H2/L2 Trend Pullback | −0.094 | −0.078 | ❌ negative in both years |
| Trend-Confluence Pullback | −0.064 | −0.122 (t = −4.5) | ❌ clearly negative on stocks |
| **All 4 combined** | | | −0.069R/trade → **loses money** |

With higher costs, IB Trend on stocks still makes +0.054R per trade and ORB second break on ETFs still makes +0.040R.

**Combinations positive in both years (≥30 trades):**

| Strategy | Symbol | Avg R/trade |
|---|---|---|
| IB Trend | MSFT | +0.24 |
| ORB 2nd break | IWM | +0.23 |
| ORB 2nd break | QQQ | +0.19 |
| IB Trend | SPY | +0.11 |
| IB Trend | AAPL | +0.10 |
| IB Trend | META | +0.09 |
| IB Trend | AMD | +0.07 |

A few others are near zero. About 52 combinations were tested, so some of these are luck.

## Why the futures results looked better: regime, not the instrument
On the **same dates** as the futures backtest, the breakout strategies fire on the same days and in the same direction on SPY/MES and QQQ/MNQ (95–100% of the time), with similar R:

| Strategy | ETF R/trade | Futures R/trade |
|---|---|---|
| QQQ ORB 2nd break vs MNQ | +0.23 | +0.30 |
| SPY IB Trend vs MES | +0.15 | +0.09 |

So the strategies transfer to ETFs mechanically. The weak part is the **older year (Oct 2024–Sep 2025)**, where most of the edge disappears. That also means the futures bot would probably have struggled in 2024-25. This is the most important caveat for the futures bot too.

## If you want to trade stocks
- **Candidate configuration:** **IB Trend** on large caps (MSFT, AAPL, META, AMD, NVDA, SPY, QQQ) plus **ORB second break** on QQQ/IWM. Drop H2/L2 and Confluence for stocks.
- **The bot needs changes first:** it is futures-only today (ContFuture/roll, contract multipliers). It would need stock contracts, share sizing (risk $/stop distance) and SMART routing. That's a moderate change, and the engine is reusable as-is.
- **Before going live:** paper-trade first. Even the survivors have only ~30–60 trades per year per symbol.
