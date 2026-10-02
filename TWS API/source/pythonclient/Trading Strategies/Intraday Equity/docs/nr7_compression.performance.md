# NR7 Compression — Backtest Performance

> ZERO trades in the 1-month window — the stacked daily filters (NR7 ∧ ADR>5 ∧ close>SMA20) rarely fire on the small fixed universe. No sample = no edge claim. Broaden the universe.

## Headline (last ~1 month (2026-08-07 → 2026-09-04))
| Metric | Value |
|---|---|
| Total trades | **0** |
| Net P/L | $0 |

**No trades were generated** by this strategy over the backtested window, so there is no
report file ([`reports/bt_faithful_NR7___9_35.xlsx`](../reports/bt_faithful_NR7___9_35.xlsx) is absent). This is an outcome, not an
error: every candidate was filtered out before a signal could form. See the
[strategy logic](nr7_compression.logic.md) for the gate stack, and widen the universe / relax the
filters to obtain a testable sample.

## Assumptions & method
- Faithful replay of the live engine ([`../backtest.py`](../backtest.py)); same windows,
  gates, stop floor, breakeven + trail, and EOD flatten as the live bot.
- Costs: 5 bps/side slippage + $0.005/share commission; sizing 1% risk-at-stop on $100,000.
