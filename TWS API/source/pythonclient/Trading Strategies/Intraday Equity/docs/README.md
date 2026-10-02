# Intraday Equity Bots — Documentation

Documentation set for the long-only intraday IBKR equity bots (PDH · ORB · NR7). This folder
complements the project [`../README.md`](../README.md) (setup/run/build) and the operational
handoff. For deep code/operational context see [`AI_HANDOVER.md`](AI_HANDOVER.md).

## Contents

| Strategy | Logic | Performance |
|---|---|---|
| **PDH Breakout** | [md](pdh_breakout.logic.md) · [html](pdh_breakout.logic.html) | [md](pdh_breakout.performance.md) · [html](pdh_breakout.performance.html) |
| **ORB Stocks-in-Play** | [md](orb_stocks_in_play.logic.md) · [html](orb_stocks_in_play.logic.html) | [md](orb_stocks_in_play.performance.md) · [html](orb_stocks_in_play.performance.html) |
| **NR7 Compression** | [md](nr7_compression.logic.md) · [html](nr7_compression.logic.html) | [md](nr7_compression.performance.md) · [html](nr7_compression.performance.html) |
| **VWAP Pullback / Reclaim** | [md](vwap_pullback.logic.md) · [html](vwap_pullback.logic.html) | [md](vwap_pullback.performance.md) · [html](vwap_pullback.performance.html) |

- **Logic** docs explain the edge thesis, universe, entry/stop/target math, management, and config keys, cross-linked to the source.
- **Performance** docs summarize the faithful backtest ([`../backtest.py`](../backtest.py)) output stored in [`../reports/`](../reports), with equity curves and daily P&L. **Read the caveats** — these are regime- and selection-biased samples, not live guarantees.

## The four strategies at a glance

| | PDH Breakout | ORB Stocks-in-Play | NR7 Compression | VWAP Pullback |
|---|---|---|---|---|
| Setup | break of prior-day high | break of 09:30–09:35 opening range on a gapper | break of OR on a compressed (NR7) trend name | retest & reclaim of rising VWAP |
| Trigger bar | 5-min close | 1-min close | 5-min close | 5-min close |
| Stop | floored 0.05%-below-PDH | ORB low / mid | max(ORB_low−0.5·ATR5, VWAP−buf), floored | below pullback low, floored |
| Target | 2R | entry + 2 × OR height | 2.2R | 2R |
| Windows (ET) | 09:35–11:30, 14:00–15:30 | 09:35–11:00 | 09:35–11:00 | 09:45–11:30, 14:00–15:30 |
| Entry order | **LMT** (chase) | MKT | MKT | MKT |
| 1-month verdict | strongly positive *in sample* | too few trades (2) | zero trades | net negative |

> **Backtest window:** the current performance pages cover the **last ~1 month (2026-08-07 → 2026-09-04)**.
> Earlier ~6-week runs (through 2026-07-17) are archived in [`../reports/_prev_20260905/`](../reports/_prev_20260905).

## Regenerating the performance docs
The performance `.md`/`.html` are generated from the Excel reports:
```bash
python docs/build_docs.py
```
It reads `reports/bt_faithful_*.xlsx` (and `reports/backtest_*.xlsx`), rebuilds each
performance page, and re-renders **all** `.md` in this folder to matching `.html`
(self-contained, no external assets or JS). Re-run [`../backtest.py`](../backtest.py) first
(needs a live IB Gateway) to refresh the underlying numbers.

## Honest-status banner
The bots are a **paper-validation candidate, not live-ready**. The backtests assume clean
limit fills at the computed entry; the real 2026-07-16 paper run used market orders on
*delayed* data and filled 5–6% past the level — the execution gap that motivated switching
PDH to `LMT` and the feed to live data. Treat all performance numbers accordingly.
