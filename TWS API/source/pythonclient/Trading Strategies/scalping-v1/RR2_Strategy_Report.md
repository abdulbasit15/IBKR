# 2:1 Reward-to-Risk Strategy Study — MNQ / MES / MGC
*Deep research + backtest, 2026-10-09. Charts: `RR2_Strategy_Report.html`.*

## Test setup
- **Data:** 5-min RTH bars, 2025-09-02 → 2026-10-07 (~278 sessions). Overnight and London levels come from the ETH files.
- **Split:** in-sample is before 2026-05-01; out-of-sample is after.
- **Costs:** 1 contract, commission plus 1 tick of slippage on every market or stop fill.
- **Conservative fills:**
  - If the stop and target fall in the same bar, the stop is assumed to fill.
  - A limit order or target only fills if price trades 1 tick through it.
  - On an entry bar that triggers mid-bar, the target only counts if the bar closes through it.
- **Exits:** every trade has a structural stop and a fixed target of 2 × risk, measured from the actual fill. Otherwise it exits at 16:00.
- **Search size:** 18 strategy families and about 160 configs × 3 contracts. That was followed by an every-bar "2R before −1R" label study and a 40-variant robustness grid on the winner.

## Bottom line
1. **Tight-stop 2:1 scalps don't beat costs on these contracts.** A random entry hits 2R before −1R only about 30–32% of the time, and breakeven after costs is about 36%.
   - Of 16 families tested, none produced a 2R scalp edge that held across instruments. That includes ICT Silver Bullet, Judas/overnight sweeps, ORB retest, inside-bar/NR, Al Brooks H2/L2, open-drive pullback, noise-area 2R, Donchian, and the IB breakout with a 1×ATR stop.
   - The research agrees. A pre-registered study of 225 ORB variants across 9 futures found zero survivors ([SSRN 7428398](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=7428398)). A walk-forward test of 14 signal families on MNQ 5-min bars found none that passed ([arXiv 2605.04004](https://arxiv.org/abs/2605.04004)). Mechanical Silver Bullet tests show a 31% win rate with PF 0.64.
2. **The one consistent edge is trading the Initial Balance breakout only in the daily-trend direction.**
   - All 24 trend-filtered variants were profitable, with median +0.074R per trade.
   - The same rules without the filter made a median +0.011R; long-only made +0.028R. So the filter adds value beyond bull-market long bias.
3. **Nothing reached statistical significance on 13 months of data.** The best pooled t-stat was about 1.3. Paper-trade before going live.

## #1 — IB Trend Breakout (2R target) — the most profitable, on all three contracts
**Rules:**
1. **Daily trend:** yesterday's RTH close versus the 20-day EMA of RTH closes.
2. **Initial Balance (IB):** the 09:30–10:30 ET high and low.
3. **Entry:** at 11:00 ET, if the 10:55 bar closed beyond the IB in the trend direction, enter at the 11:00 open. The first IB break decides the day; if it is against the trend, there is no trade.
4. **Stop:** the IB midpoint. **Target:** 2R; otherwise exit at the 16:00 close. One trade per day.

| | Trades | Win% | 2R hit | PF | Net $ | Max DD | IS PF | OOS PF | PF @2-tick | Avg risk |
|---|---|---|---|---|---|---|---|---|---|---|
| MNQ | 43 | 44% | 5% | 1.38 | +1,620 | 2,192 | 1.64 | 1.21 | 1.37 | 144 pt ($288) |
| MES | 46 | 46% | 13% | 1.54 | +983 | 449 | 1.43 | 1.66 | 1.48 | 23 pt ($116) |
| MGC | 45 | 56% | 7% | **1.87** | **+2,391** | 766 | 2.02 | 1.66 | 1.83 | 23 pt ($232) |

**Caveat:**
- The stop is wide (half the IB), so the 2R target rarely fills. Most winners are closed at 16:00.
- It's a 2R-capped trend day-trade held for about 2–5 hours, not a quick scalp.
- It takes only about 1 trade every 6 sessions per contract.

## #2 — MNQ Trend-Confluence Pullback — the only true 2:1 scalp that worked (MNQ only)
**Rules:**
1. **Filters:** from 10:00 ET, all five must agree:
   - daily trend
   - first-30-min return (10:00 price vs the prior close)
   - price vs the prior close
   - price vs VWAP
   - price vs 30 minutes ago
2. **Trigger:** a 5-min bar dips to the EMA9 and closes back beyond it in the trend direction. Enter at the next open.
3. **Stop:** 1 × ATR(14, 5-min), about 42 MNQ points or $85. **Target:** 2R.
4. **Limits:** at most 4 trades per day; last entry at 15:00.

| Trades | Win% | 2R hit | Stopped | PF | Net $ | IS PF | OOS PF | PF @2-tick | Avg hold |
|---|---|---|---|---|---|---|---|---|---|
| 295 | 39% | 36% | 60% | 1.13 | +2,071 | 1.03 | 1.29 | 1.12 | 54 min |

The same rules lose on MES and MGC: PF 0.87 and 0.90.

## Everything else tested (2R targets, net of costs)
| Family | % of runs profitable | Median PF |
|---|---|---|
| ORB second break (double break) | 67% | 1.22 (too few trades: 29–74 per contract) |
| IB breakout confirmed at 11:00 | 67% | 1.10 |
| IB breakout, first close | 67% | 1.06 |
| IB shallow retest, limit entry | 50% | 1.00 |
| Intraday Donchian breakout | 48% | 0.98 |
| ORB with overnight/London midpoint filter | 33% | 0.94 |
| Wide-OR continuation | 44% | 0.92 |
| Overnight high/low sweep (Judas) | 17% | 0.91 |
| Trend confluence (all contracts) | 29% | 0.90 |
| Opening candle 2R | 17% | 0.90 |
| Al Brooks H2/L2 | 21% | 0.89 |
| Overnight-range breakout | 33% | 0.85 |
| ORB break-retest-go | 12% | 0.84 |
| Noise-area momentum 2R | 0% | 0.82 |
| ICT Silver Bullet | 42% | 0.81 |
| Inside-bar breakout | 0% | 0.71 |
| Open-drive pullback | 12% | 0.63 |

## Files (all in `scalping-v1/`)
| File | Purpose |
|---|---|
| `rr2_strategies.py`, `rr2_strategies2.py` | All 18 families |
| `rr2_run.py` | Grid runner |
| `rr2_label_study.py`, `rr2_feature_scan.py`, `rr2_event_scan.py` | Every-bar 2R study |
| `rr2_final.py` | Robustness grid and centre config for #1 |
| `make_rr2_report.py` | Builds the HTML report |
| `eth_context.py` | Overnight, Asia and London levels |
| `scalp_engine.py` | Now supports stop-entry and limit-entry orders |
