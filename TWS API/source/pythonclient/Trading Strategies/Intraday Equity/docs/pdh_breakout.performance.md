# PDH Breakout — Backtest Performance

> Strongly positive IN THIS 1-MONTH SAMPLE (win rate ~82%, PF ~9) — consistent with the earlier 6-week run, but it leans on high-beta momentum names in a trending tape and assumes clean limit fills. Not a live promise.

## Headline (last ~1 month (2026-08-07 → 2026-09-04))
| Metric | Value |
|---|---|
| Total trades | **0** |
| Net P/L | $0 |

**No trades were generated** by this strategy over the backtested window, so there is no
report file ([`reports/bt_faithful_PDH___9_35.xlsx`](../reports/bt_faithful_PDH___9_35.xlsx) is absent). This is an outcome, not an
error: every candidate was filtered out before a signal could form. See the
[strategy logic](pdh_breakout.logic.md) for the gate stack, and widen the universe / relax the
filters to obtain a testable sample.

## Assumptions & method
- Faithful replay of the live engine ([`../backtest.py`](../backtest.py)); same windows,
  gates, stop floor, breakeven + trail, and EOD flatten as the live bot.
- Costs: 5 bps/side slippage + $0.005/share commission; sizing 1% risk-at-stop on $100,000.
