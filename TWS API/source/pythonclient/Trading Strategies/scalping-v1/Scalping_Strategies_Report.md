# Top 3 Scalping Strategies — MNQ / MES / MGC
*Research + RTH backtest, 2026-10-05. Charts and monthly tables: `Scalping_Strategies_Report.html`.*

## How this was tested
- **Data:** 5-min RTH bars from `Historical Data/data/{SYM}_cont_5mins_rth.csv` plus `{SYM}_5m_recent.csv`, 09:30–16:00 ET, **2025-09-02 → 2026-10-05** (~275 sessions per symbol). Earlier bars are forward-fill padding, so they were dropped. MGC's roll gap between the two files was back-adjusted.
- **Split:** in-sample is Sep 2025 – Apr 2026; out-of-sample is May – Oct 2026.
- **Fills:**
  - Signals fire on the bar close; entry is a market order at the next bar's open.
  - Stops are stop-market orders.
  - Every market or stop fill costs 1 tick of slippage.
  - A limit target only fills if price trades 1 tick through it.
  - If the stop and target fall in the same bar, the stop is assumed to fill.
  - Commission is $0.62 per side for MNQ/MES and $0.80 for MGC.
  - Results are for 1 contract.
- **Search:** 10 strategy families from the research, 118 parameter sets × 3 symbols. Finalists were then checked on:
  - neighbouring parameters,
  - 2-tick slippage,
  - long/short split,
  - monthly P&L.

## Headline (read this first)
Classic indicator scalps lose after costs on all three contracts at 5-min resolution:
- VWAP-band fade
- EMA/VWAP pullback
- Bollinger squeeze
- PDH/PDL sweep-reclaim
- gap fill
- RSI(2)

**Mean-reversion was the worst group.** Only 6–8% of VWAP-fade and sweep-fade runs made money. This matches the independent research: a 2026 walk-forward study of 14 signal families on MNQ 5-min bars found none that cleared costs ([arXiv 2605.04004](https://arxiv.org/abs/2605.04004)).

What did survive is short-hold **momentum around session structure**. The edges are real but small: about $500–$3,000 per contract per year.

## Scorecard (1 contract, net of all costs)
| Strategy | Sym | Use? | Trades | Win% | PF | Net $ | Max DD | IS PF | OOS PF | PF @2-tick slip | Neighbour params profitable |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **1. IB Breakout** | MNQ | ✅ | 117 | 62% | 1.16 | +1,146 | 927 | 1.11 | 1.26 | 1.15 | 56% |
| | MES | ✅ best fit | 134 | 66% | 1.22 | +754 | 483 | 1.18 | 1.28 | 1.15 | **97%** |
| | MGC | ⚠ small | 133 | 67% | 1.06 | +462 | 1,365 | 1.03 | 1.12 | 1.04 | 62% |
| **2. Last-Half-Hour Momentum** | MGC | ✅ best fit | 201 | 51% | **1.63** | **+3,007** | 836 | 1.58 | 1.73 | 1.52 | **100%** |
| | MNQ | ✅ | 175 | 49% | 1.22 | +1,464 | 1,376 | 1.01 | 1.49 | 1.19 | 50% |
| | MES | ❌ | 166 | 43% | 0.82 | −653 | 938 | 0.72 | 0.97 | 0.73 | 0% |
| **3. Opening-Candle Momentum** | MNQ | ✅ | 271 | 25% | 1.12 | +1,875 | 3,164 | 1.11 | 1.12 | 1.10 | 67% |
| | MGC | ❌ | 266 | 25% | 1.06 | +856 | 2,339 | 1.15 | 0.91 | 1.02 | 25% |
| | MES | ❌ | 271 | 23% | 0.84 | −1,199 | 2,293 | 1.05 | 0.54 | 0.77 | 0% |

**What to trade on each instrument:**
- **MNQ:** all three strategies.
- **MES:** #1 only. This fits the research: ES rotates more and NQ trends more.
- **MGC:** #2 primarily, with #1 as a small secondary.

## The 3 strategies (exact rules)

### 1. Initial Balance (60-min) Breakout → 50% extension
*Research basis:* about 97% of sessions break the IB, and the median extension is 56–64% of the IB range ([tradingstats IB study](https://tradingstats.net/initial-balance-breakout-statistics/)). 5- and 15-min ORBs tested about flat after costs, here and in published work ([QuantifiedStrategies](https://www.quantifiedstrategies.com/opening-range-breakout-strategy/)).
- **IB:** the high and low of 09:30–10:30 ET. Skip the day if the IB is wider than 0.6 × the 14-day average RTH range.
- **Entry:** take the first 5-min close above the IB high (long) or below the IB low (short). Enter at the next bar's open. No entries after 12:00 ET. One trade per day.
- **Stop:** the opposite side of the IB.
- **Target:** the IB edge + 50% of the IB width, as a limit order. Time exit after 2 hours.
- **Robustness:**
  - MES was profitable in 31 of 32 neighbouring settings (IB 45–90 min, stop at the midpoint or the opposite side, extension 0.3–1.0×).
  - Win rate is about 62–67%. The average hold is about 1 hour.
- **MES variant:** stop at the IB midpoint with a 1R target. PF 1.63 in-sample and 1.44 out-of-sample, +$1,823 total.

### 2. Last-Half-Hour Momentum (Gao et al. / Baltussen et al.)
*Research basis:* the first-half-hour return predicts the last-half-hour return. This has been documented on SPY ([Gao et al.](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2440866)) and on 60+ futures including commodities ([Baltussen et al., JFE 2021](https://academicweb.nd.edu/~zda/intramom.pdf)).
- **Signal:** at 15:30 ET, take the 10:00 close minus the prior RTH close. Trade only if the move is at least 0.25 × the 14-day average RTH range.
- **Entry:** in the direction of that move, at the 15:30 open.
- **Stop:** 0.15 × the 14-day average range.
- **Exit:** at the 16:00 close.
- **Results:**
  - **MGC** was profitable in every neighbouring setting, in-sample and out-of-sample, and at 2-tick slippage, with Sharpe about 2.0.
  - **MNQ** made its gains almost entirely out-of-sample, so size it smaller.

### 3. Opening-Candle Momentum (Zarattini & Aziz 5-min ORB, scalp exit)
*Research basis:* "Can Day Trading Really Be Profitable?" ([SSRN](https://static1.squarespace.com/static/5983d931579fb366729580d8/t/643ed6765176b45506e41a01/1681839734183/SSRN-id4416622.pdf)). Replications find the edge only on Nasdaq ([MQL5 replication](https://www.mql5.com/en/blogs/post/776235)), which is also what this test found.
- **Direction:** the direction of the 09:30–09:35 candle. Skip the day if that candle is a doji.
- **Entry:** at the 09:35 open.
- **Stop:** 0.10 × the 14-day average RTH range.
- **Exit:** time exit after 60 minutes.
- **Profile:** about 25% win rate with fat winners, +4.1 MNQ points per trade.
- **Drawdown:** max drawdown ($3.2k) exceeds the 13-month profit, so it needs patience and small size. **MNQ only.**

## Caveats
- **Short sample.** About 13 months of clean 5-min data. Each symbol and strategy has roughly 120–270 trades. Treat PF values of 1.1–1.2 as "small positive edge", not certainty.
- **Strong bull market.** The test period was a strong bull year. Long and short P&L are reported separately in the HTML; none of the three relies only on longs.
- **Bar resolution.** 5-min bars cannot model true tick scalps (targets under about 8 ticks). Those die to costs anyway, per the research.
- **Next steps:**
  - paper-trade, or
  - build TradingView `strategy()` or IBKR bot versions of #1 and #2.

## Files
| File | Purpose |
|---|---|
| `scalp_engine.py` | Data loader, indicators, fill simulator, metrics |
| `strategies.py` | All 10 families with their parameter grids |
| `run_backtest.py` | Full grid run → `results/all_configs.csv` |
| `robustness.py` | Finalist checks → `results/finalists.json` |
| `make_report.py` | Builds the HTML report |
