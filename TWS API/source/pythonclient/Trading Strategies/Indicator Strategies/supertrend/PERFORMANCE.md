# Supertrend v1 — Performance & Backtest

**Bottom line:** v1 is the **production line**. Its stack — raw Supertrend →
+ DEMA + regime gate → + partial-take-profit — improves at every step in
backtest. The regime gate roughly **halves max drawdown**; the partial-TP adds
another **~+$7.6k** on the deployed 15-min futures pair. This is the branch to run
live (after paper validation + LPL pre-clearance).

---

## Provenance of these numbers

- **Data:** fresh IB pulls / continuous back-adjusted futures (`TRADES`,
  `useRTH=False`, `volume>0` filtered) in `../../Historical Data/data/`.
- **Scripts:** `../../Historical Data/Futures/scripts/` — notably
  `backtest_partial.py`, `backtest_tranche.py`, `backtest_regime.py`,
  `backtest_compare.py`.
- **Result files:** `../../Historical Data/Futures/results/` — notably
  `mnq_mes_real_backtest_evolution.txt`, `mnq_mes_partial_tp.txt`,
  `mnq_mes_tranche_scaleout.txt`, `mnq_mes_regime_gate.txt`,
  `mnq_mes_st_dema_regime.txt`.
- **Contract P/L:** MNQ = $2/point, MES = $5/point. Stops/targets modelled as
  exact fills (**no slippage / commissions**).
- **Windows:** `CHOPPY` = Nov-2025 → Mar-2026, `TREND` = Apr → Jul-2026,
  `BOTH`/`FULL` = the full window (up to ~2026-07-20).

> ⚠️ **In-sample and frictionless.** These compare *configurations on the same
> history*. They are directional evidence, **not** a live-P/L forecast. Real
> fills, commissions, and slippage will be worse. Paper-trade first.

---

## 1. Strategy evolution (the money chart)

From `mnq_mes_real_backtest_evolution.txt` — `long_short`, Q=4 contracts, fresh
IB data through 2026-07-20. Three stages:
`PLAIN_ST` → `PREVIOUS` (ST + DEMA + regime stand-aside) → `CURRENT` (+ partial-TP
50%@2R, runner trails 1R).

**Per series — Net P/L $ / Profit Factor / Max Drawdown $:**

| Series | PLAIN_ST | PREVIOUS (ST+DEMA+regime) | CURRENT (+partial-TP) |
|---|---|---|---|
| MNQ 15m | +30,660 · PF 1.09 · DD −47,201 | +45,536 · 1.32 · −11,184 | **+49,953 · 1.35 · −9,800** |
| MNQ 30m | +14,628 · 1.03 · −37,514 | −442 · 1.00 · −35,321 | −6,940 · 0.97 · −39,954 |
| MNQ 1h  | +39,658 · 1.10 · −26,605 | +56,509 · 1.27 · −19,044 | **+65,035 · 1.29 · −17,971** |
| MES 15m | +4,781 · 1.03 · −21,752 | +8,920 · 1.12 · −12,473 | **+12,072 · 1.17 · −11,098** |
| MES 30m | −23,249 · 0.91 · −33,762 | −14,101 · 0.89 · −25,088 | −14,046 · 0.89 · −24,663 |
| MES 1h  | +9,288 · 1.05 · −16,017 | +11,761 · 1.11 · −16,762 | **+14,431 · 1.12 · −18,149** |

**Deployed 15m totals (MNQ + MES, Q=4), Net P/L $:**

| Stack | Net P/L $ |
|---|--:|
| PLAIN_ST | +35,440 |
| + DEMA + regime | +54,456  (**+19,016** vs plain) |
| + partial-TP (**deployed**) | **+62,025**  (**+7,569** vs regime-only) |

Two clear lessons:
- **The regime gate is the biggest single win** (+$19k on 15m) and it roughly
  **halves drawdown** (e.g. MNQ 15m −47k → −11k). It's *defence in chop, offence
  in trends* — it doesn't profit in chop, it **avoids** it.
- **Partial-TP adds a further +$7.6k** on 15m and cuts drawdown a bit more.
- **Timeframe matters:** the regime gate wins big on **15m**; higher timeframes
  are already cleaner, so the gate over-filters (raw ST / ST+DEMA are best on 1h).
  → the deployed strategies run on **15m**.

---

## 2. Partial take-profit, isolated

From `mnq_mes_partial_tp.txt` — trim ½ @2R, runner trails 1R, vs the plain exit.
`long_short`, Q=10 (half = 5), Nov25–Jul26. Totals across all six series, Net P/L $:

| Phase | EXISTING (plain exit) | PARTIAL (½@2R) | Δ |
|---|--:|--:|--:|
| CHOPPY Nov25–Mar26 | +76,651 | **+91,013** | +14,362 |
| TREND  Apr–Jul26 | −38,073 | **−9,799** | +28,273 |
| **BOTH   Nov25–Jul26** | +44,191 | **+85,400** | **+41,210** |

Partial-TP helped in **both** regimes and roughly **doubled** full-window P/L at
Q=10 — the biggest relief in the losing trend window, because banking half at 2R
and trailing the runner rescues give-backs.

**Tranche design (from `mnq_mes_tranche_scaleout.txt`):** trimming **50%@2R** (or
33/33@2R,3R) beats the plain exit; **laddering into smaller/earlier 1R trims does
NOT help** — the edge is trimming at 2R+ and keeping a runner. Needs
`fixed_stocks ≥ 2` (so half a contract isn't 0).

---

## 3. Why each filter is (or isn't) on

From the filter/regime comparison reports:

1. **Raw Supertrend alone is marginal** — whipsaws in chop (win rate ~30%,
   PF often < 1.1). Matches the literature.
2. **RSI > 50 / < 50 momentum** helps win rate (+6–10 pts) and drawdown, mostly
   on 30m/1h. MACD similar but more mixed.
3. **DEMA / ADX trend gates mostly just delay entries** (redundant with the
   Supertrend) and can hurt in clean trends. DEMA on top of the regime gate is
   ≈ a wash — kept **on** for the small drawdown benefit / user preference.
4. **Regime gate (stand-aside in chop) is the biggest win** — see §1. When
   enabled it **supersedes** the always-on RSI/MACD gates (applies momentum by
   regime instead); it does not override DEMA.

The deployed 15m futures strategies therefore run **DEMA(200) ON + regime gate ON
(stand-aside) + partial-TP ON**, RSI/MACD present but off.

---

## 4. Verdict

- **v1 is the branch to run.** Every stage of its stack backtests positive on the
  deployed 15m timeframe, and it has the `_safe_sleep()` Gateway-restart fix.
- **Deploy on 15m**, not 30m (30m is the weak timeframe in every series above).
- v1's counterpart **v2** swaps partial-TP for a mean-reversion fade that
  backtests flat-to-negative at its defaults — see
  [`../supertrendv2/PERFORMANCE.md`](../supertrendv2/PERFORMANCE.md). Prefer v1
  for production.
- All numbers here are **in-sample, frictionless** — **paper-validate and get LPL
  pre-clearance before any live use.**
