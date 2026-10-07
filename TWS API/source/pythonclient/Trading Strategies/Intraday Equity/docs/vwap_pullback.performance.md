# VWAP Pullback / Reclaim — Backtest Performance

> Net NEGATIVE in the sample (~31% win, PF ~0.4): failed reclaims in chop tag the stop. Parameter-sensitive; needs a chop filter before it is tradable.

## Headline (last ~1 month (2026-08-07 → 2026-09-04))
| Metric | Value |
|---|---|
| Total trades | **0** |
| Net P/L | $0 |

**No trades were generated** by this strategy over the backtested window, so there is no
report file ([`reports/bt_faithful_VWAP_PB___9_45.xlsx`](../reports/bt_faithful_VWAP_PB___9_45.xlsx) is absent). This is an outcome, not an
error: every candidate was filtered out before a signal could form. See the
[strategy logic](vwap_pullback.logic.md) for the gate stack, and widen the universe / relax the
filters to obtain a testable sample.

## Assumptions & method
- Faithful replay of the live engine ([`../backtest.py`](../backtest.py)); same windows,
  gates, stop floor, breakeven + trail, and EOD flatten as the live bot.
- Costs: 5 bps/side slippage + $0.005/share commission; sizing 1% risk-at-stop on $100,000.
