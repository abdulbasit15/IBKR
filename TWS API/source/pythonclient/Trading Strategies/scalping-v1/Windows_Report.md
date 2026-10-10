# 2:1 RR Strategies by RTH Time Window — MNQ / MES / MGC
*2026-10-09. Full colour heatmaps (hourly buckets and per-instrument tables): `Windows_Report.html`. Code: `rr2_windows.py`.*

## Test setup
- **RTH only:** 5-min bars from 09:30–16:00 ET, 2025-09-02 → 2026-10-07. No overnight data is used; the daily trend comes from RTH closes.
- **Strategies:** 13 strategies with a 2R target. Each was run in 3 sessions plus 7 hourly buckets, in two modes:
  - **Window-only:** enter inside the window and be flat by the window's end.
  - **Hold:** enter inside the window, then hold to 2R, the stop, or 16:00.
- **Costs:** 1 contract per instrument, net of commission plus 1 tick of slippage. "Pooled" means MNQ + MES + MGC trades combined. In-sample (IS) is before 2026-05-01; out-of-sample (OOS) is after.

## Random-entry baseline: how often a 2R target hits before a 1×ATR stop
| Window | MNQ | MES | MGC |
|---|---|---|---|
| 09:30–11:30 | 32.2% | 31.5% | 32.0% |
| 11:30–13:30 | 30.2% | 29.3% | 30.4% |
| 13:30–16:00 | 28.8% | 27.8% | 26.7% |

Breakeven is about 36%. A 2R target is easiest to reach in the morning and hardest late in the day.

## Pooled profit factor by window — Hold mode
| Strategy | 09:30–11:30 | 11:30–13:30 | 13:30–16:00 | Full RTH |
|---|---|---|---|---|
| **IB Trend Breakout (11:00 confirm)** | **1.57** (134) | – | – | 1.57 |
| **Al Brooks H2/L2 (trend)** | **1.54** (113) | 0.67 | 0.89 | 1.05 |
| ORB second break | 1.27 (163) | 1.17 (83) | 0.68 | 1.16 |
| IB Trend Breakout (first break) | 1.24 (230) | 1.23 (71) | 0.52 | 1.20 |
| VWAP/EMA Pullback | 1.21 (428) | 0.73 | 0.86 | 0.94 |
| Inside-bar breakout (trend) | 1.15 (124) | 0.55 | 0.63 | 0.70 |
| Donchian 48-bar breakout | 1.11 (697) | 0.97 | 0.87 | 1.05 |
| ORB 15-min breakout | 1.01 (748) | – | – | 1.00 |
| **Trend-Confluence Pullback** | 0.98 | 1.00 | **1.16** (456) | 0.99 |
| Noise-band momentum | 0.71 | 1.09 (346) | 1.09 (334) | 0.89 |
| Opening candle | 0.97 | – | – | 0.97 |
| PDH/PDL sweep-reclaim | 0.78 | 0.86 | 0.56 | 0.77 |
| Bollinger squeeze | <20 trades | 0.68 | 0.95 | 0.86 |

## Pooled profit factor by window — Window-only mode
| Strategy | 09:30–11:30 | 11:30–13:30 | 13:30–16:00 |
|---|---|---|---|
| **ORB second break** | **1.92** (158) | 1.19 (80) | 0.78 |
| **Al Brooks H2/L2 (trend)** | **1.59** (104) | 0.45 | 0.93 |
| Inside-bar breakout (trend) | 1.25 (116) | 0.53 | 0.57 |
| IB Trend (11:00 confirm) | 1.18 (134) | – | – |
| VWAP/EMA Pullback | 1.13 (402) | 0.78 | 0.86 |
| IB Trend (first break) | 1.11 (220) | 1.06 (69) | 0.67 |
| Donchian | 1.08 (688) | 1.01 | 0.86 |
| **Trend-Confluence Pullback** | 0.94 | 0.94 | **1.12** (539) |
| Noise-band momentum | 0.70 | 1.06 | 1.04 |

## Best strategy per window (must be profitable in-sample, out-of-sample, and on most instruments)
| Window | Pick | PF | IS / OOS PF | MNQ / MES / MGC PF | 2R hit |
|---|---|---|---|---|---|
| **09:30–11:30** | IB Trend Breakout (11:00 confirm), hold | 1.57 | 1.74 / 1.41 | 1.38 / 1.54 / 1.87 | 8% |
| 09:30–11:30 (true 2:1) | Al Brooks H2/L2 with daily trend, hold | 1.54 | 1.33 / 1.89 | 1.90 / 0.90 / 1.56 | **36%** |
| 09:30–11:30 (window-only) | ORB second break | 1.92 | 2.99 / 1.36 | 2.90 / 0.97 / 1.88 | 7% |
| **11:30–13:30** | Nothing robust: best cells fail OOS (IB first break OOS 0.50, ORB 2nd OOS 0.45). Noise-band momentum is PF 1.09 (IS 1.11 / OOS 1.05), but only on MNQ (1.39). | — | — | — | — |
| **13:30–16:00** | Trend-Confluence Pullback, hold | 1.16 | 1.20 / 1.08 | 1.25 / **0.73** / 1.33 | 31% |

**Hourly detail (see HTML):**
- 10:30–11:30 is the single best hour. H2/L2 has PF 1.83–2.06 there, and the IB/ORB entries cluster there.
- 11:30–12:30 and 12:30–13:30 are negative for almost everything.
- 14:30–15:30 is the best afternoon hour (Confluence PF 1.45–1.49; noise-band PF 1.44–1.59).

## Takeaways
1. **Trade 2:1 setups in the morning (09:30–11:30, especially 10:30–11:30).** In Hold mode, 8 of the 12 strategies with enough trades are profitable there, versus 3 at midday and 2 in the afternoon.
2. **Skip midday (11:30–13:30).** Random 2R odds drop, and no strategy held up out-of-sample.
3. **The afternoon only works for trend continuation (14:30–15:30) on MNQ and MGC.** MES loses in every afternoon cell, in both modes.
4. **Selection-bias warning:** this is 13 strategies × 10 windows × 2 modes = 260 cells, so some green cells are luck. Trust the patterns that repeat across strategies, like "morning good, midday bad", more than any single cell. Paper-trade before going live.
