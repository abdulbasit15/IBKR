# AI HANDOVER — Intraday Equity Bots (IBKR / ib_async)

Continuity doc for the next AI/engineer. Written 2026-09-05. Complements the older
operational [`../HANDOFF.md`](../HANDOFF.md) and [`../BUILD_AND_DEPLOY.md`](../BUILD_AND_DEPLOY.md);
where they disagree, **this file is newer**.

## 1. What this project is
Three **long-only, intraday-only** IBKR equity bots on **ib_async** (API 10.45.x),
config-driven by [`../equity.json`](../equity.json), defaulting to **paper account DU672616**,
**IB Gateway port 4002**. Entry point [`../runner.py`](../runner.py) runs one thread per active
strategy (own clientId 30/31/32; bootstrap clientId ~120). Long-only, ≤1% risk-at-stop,
hard EOD flatten.

## 2. Code map
| File | Role |
|---|---|
| [`../runner.py`](../runner.py) | bootstrap equity/vol-scale, shared risk/cache/journal, spawn one thread per active strategy |
| [`../equity_base.py`](../equity_base.py) | `EquityStrategyBase`: per-thread event loop, ET windows, sizing + min-stop floor, RVOL, VWAP-from-bars, ATR/ADR, regime gate, bracket placement, breakeven/trail, EOD-flatten-every-tick, reconnect, scanner, journaling |
| [`../equity_order.py`](../equity_order.py) | bracket builder; **entry modes** (MKT true-market / LMT marketable-limit chase); resize on partial; breakeven/trail modify; emergency+EOD flatten |
| [`../strategies/pdh_breakout.py`](../strategies/pdh_breakout.py) | PDH breakout (see [logic](pdh_breakout.logic.md)) |
| [`../strategies/orb_stocks_in_play.py`](../strategies/orb_stocks_in_play.py) | ORB stocks-in-play (see [logic](orb_stocks_in_play.logic.md)) |
| [`../strategies/nr7_compression.py`](../strategies/nr7_compression.py) | NR7 compression (see [logic](nr7_compression.logic.md)) |
| [`../portfolio_risk.py`](../portfolio_risk.py) | thread-safe risk book: 1% risk-at-stop, aggregate-risk cap, sector cap, same-symbol lock, daily-loss halt, persistence |
| [`../market_data.py`](../market_data.py) | global historical-data rate limiter, per-day JSON cache, vol-scale detection |
| [`../calendar_util.py`](../calendar_util.py) | ET tz + NYSE holiday/half-day calendar (static 2025–2027) |
| [`../reporting.py`](../reporting.py) | Excel analytics report (Trades/Daily/ByTicker/Summary) |
| [`../backtest.py`](../backtest.py) | faithful historical replay of the live engine → `reports/*.xlsx` (read-only; needs live IB Gateway) |
| [`../test_order.py`](../test_order.py) / [`../scanner_test.py`](../scanner_test.py) | 1-share bracket smoke test / scanner+data check |
| [`build_docs.py`](build_docs.py) | regenerate these docs (performance md/html from xlsx + render all md→html) |

## 3. Recent changes
### 2026-09-27 — backtest-parity config
- Per user: aligned the 4 active strategies to the faithful backtest's assumptions —
  **`entry_order_type: "LMT"`** (all 4; ORB/NR7/VWAP were `MKT`) and **`fixed_stocks: 0`**
  (all 4; was `1`) so sizing is 1% risk-at-stop on $100k, the same basis the backtest reports.
  Strategy params were already identical (backtest reads them from `equity.json`).
- **Parity is only partial by design.** `backtest.py` does NOT model several live safety gates,
  so live is MORE conservative than the reported numbers: (a) `max_position_notional` ($100k)
  caps size — with PDH's ~0.5% floored stop each trade *wants* ~$200k notional, so the cap
  roughly halves PDH size vs the (uncapped, ~2x-levered) backtest; (b) portfolio risk gates
  (`aggregate_open_risk_pct` 0.03, `max_concurrent_positions`, `max_positions_per_sector` 2,
  `daily_loss_limit_pct` 0.03 halt) and (c) the `regime` gate (SPY/VIX) can all skip trades the
  per-symbol backtest took. Closing that gap means relaxing risk controls — do NOT do so without
  explicit sign-off (removing the notional cap = intraday leverage).

### 2026-09-27 — persistent daemon (dormant between sessions)
- **[`../runner.py`](../runner.py) no longer exits** on a non-trading day / outside the window.
  It now runs as a **daemon**: `main()` loops `wait_for_session()` → `run_one_session()`. It stays
  **dormant (no broker connection)** on weekends/holidays, before a per-day pre-open lead, and
  after the day's EOD flatten; it wakes ~`preopen_lead_min` (default 10) minutes before the
  earliest active-strategy window, runs that session (bootstrap + one thread per strategy, which
  self-flatten at EOD), then returns to dormancy for the next trading day.
- New optional top-level config keys: `preopen_lead_min` (default 10), `dormant_poll_sec`
  (default 60). Lifecycle logs go to `logs/equity_daemon.log`; per-session trading logs stay
  date-stamped. Ctrl+C stops the daemon cleanly. (The old per-thread `is_trading_day` guard in
  [`../equity_base.py`](../equity_base.py) remains as a redundant safety net but no longer fires.)

### 2026-09-05
1. **Diagnosed the 2026-07-16 PDH live run** ([`../logs/logs/PDH___9_35_20260716.log`](../logs/logs/PDH___9_35_20260716.log)):
   4 of 5 entries filled **above** their own take-profit. Root cause = `market_data_type: 3`
   (15-min **delayed** data) + `entry_order_type: "MKT"`. The signal fired on stale bars; the
   unbounded market order filled at the true price 5–6% past the level (IR level ~79.58 →
   filled @ 84.64), so the TP `LMT SELL` was instantly marketable and dumped for a small loss.
2. **`equity_order.py`** — documented and preserved the two entry modes; `MKT` is a true
   market order (no ceiling), `LMT` is the marketable-limit **chase walk** bounded by
   `max_chase_pct` (rests at entry, steps up, no-fills if price ran away).
3. **`equity_base.py`** — added a startup **WARNING** when `market_data_type` is 3/4 explaining
   the delayed-data execution risk for both modes.
4. **`equity.json`** — per user decision: **PDH → `entry_order_type: "LMT"`** and
   **`market_data_type: 1` (live)** for all strategies. ORB and NR7 remain `MKT`.

   > ⚠️ `market_data_type: 1` requires the paper account to have a **live data subscription
   > shared** to it (Client Portal → Settings → Account Config → Paper Trading Account →
   > "Share real-time market data"). Without it, ticker fields are **NaN** and the VWAP gate
   > silently blocks every entry (a known past failure). If you see NaN prices / zero trades,
   > that's the cause — either share the sub or set `market_data_type: 3` and expect delayed.

## 4. Data-entitlement — the key operational fact
- Paper `DU672616` historically had **no live data sub**. `market_data_type: 3` (delayed)
  makes historical bars + VWAP-from-bars work but makes every intraday signal ~15 min stale.
- The bots compute VWAP **from bars** (`session_vwap_from_bars`) precisely so the VWAP gate
  survives delayed feeds; the live RTVolume `ticker.vwap` (tick 233) is NaN without entitlement.
- Net: to trade the levels for real you need **live data (type 1)** *and* the subscription
  shared. This is the single biggest gating item.

## 5. Backtest & performance status
- [`../backtest.py`](../backtest.py) faithfully mirrors the engine (windows, VWAP-from-bars,
  gates, stop floor, breakeven+trail, EOD, slippage 5bps/side + $0.005/sh) on IBKR historical
  bars. It needs a live IB Gateway to pull data; **it cannot run in a sandbox**.
- **Current** outputs in [`../reports/`](../reports) are the **1-month run (2026-08-07 → 2026-09-04)**,
  run 2026-09-05 on live data via Gateway 4002 (BT_DAYS=21):
  - **PDH** — 66 trades, 81.8% win, PF 9.1, **+$71,384** *(regime/selection-biased; see perf doc)*.
  - **ORB** — 2 trades, 50% win, +$94 *(too few to judge this window)*.
  - **NR7** — **0 trades** (no report file written; stacked daily filters didn't fire).
  - **VWAP PB** — 36 trades, 30.6% win, PF 0.44, **−$9,625** (failed reclaims in chop).
- **Earlier** ~6-week run (≈2026-06-03 → 2026-07-17) is archived in `reports/_prev_20260905/`
  (PDH 137 trades PF 11.43 +$159.7k; ORB 321 trades −$54.3k; VWAP 24 trades; NR7 3 trades).
- The performance docs derive their numbers from these files via [`build_docs.py`](build_docs.py).
- **Big caveat:** backtests assume clean **limit fills at the computed entry**. The live
  2026-07-16 run showed the real execution gap when using MKT on delayed data. Backtested
  edge ≠ live edge until data + execution match the backtest assumptions.

## 6. Known discrepancies / gotchas
- **VWAP Pullback is now a 4th active strategy** (added externally ~2026-09-05):
  `active_strategies` now lists `"VWAP PB - 9.45"`, [`../strategies/vwap_pullback.py`](../strategies/vwap_pullback.py)
  now exists, and it has a config block. (This resolves the earlier "vwap_pullback.py missing"
  note.) Its `entry_order_type` is still `MKT` — consider `LMT` like PDH. Its
  [logic](vwap_pullback.logic.md) / [performance](vwap_pullback.performance.md) docs are included.
- **`TradeReporter` ACCUMULATES** — `backtest.py` writes via it, so re-running a backtest
  *appends* to any existing `reports/bt_faithful_*.xlsx` (blending old + new). **Delete the
  target report(s) before a fresh run**, or slice off the new rows afterward (the 2026-09-05
  1-month run did the latter; July originals are archived in `reports/_prev_20260905/`).
- **Stale `dist/intraday_equity.exe`** — built before recent fixes. **Rebuild** before any
  deployment (`build_and_deploy.ps1`; see [`../BUILD_AND_DEPLOY.md`](../BUILD_AND_DEPLOY.md)).
- **`fixed_stocks: 1`** on all strategies ⇒ every trade is exactly 1 share (P&L is tiny by
  design during validation). Set to `0` for real 1%-risk sizing when ready.
- **Static calendar** (2025–2027) in `calendar_util.py` — extend yearly.
- **Polling engine** — `reqHistoricalData` each tick (rate-limited). Fine for a few names;
  move to `reqRealTimeBars` for large universes.

## 7. Open items / TODO
1. **Live data confirmed working 2026-09-05** (historical bars flowed on Gateway 4002 once a
   duplicate session was closed — Error 162 "connected from a different IP address" clears when
   only one session is logged in). Still TODO: verify a real *order fill* end-to-end with
   `market_data_type: 1` during RTH (watch for NaN quotes → zero trades if the sub lapses).
2. Decide whether to also switch **ORB/NR7 to `LMT`** (recommended, same slippage rationale).
3. ~~Flip `fixed_stocks` 1 → 0~~ **DONE 2026-09-27** (all 4 active now `fixed_stocks: 0`, `LMT`).
   Positions are now real-sized (1% risk-at-stop) — validate a real fill before trusting size.
4. **Run at the open (~09:35 ET)** on live data to see genuine breakout entries.
5. **NR7 needs a bigger universe** to produce a testable trade count.
6. Resolve the **`vwap_pullback.py`** discrepancy.
7. **Rebuild the exe** before deploy.
8. Re-run `backtest.py` on live Gateway to refresh `reports/*.xlsx`, then `python docs/build_docs.py`.

## 8. Environment constraints (LPL)
- **pypi.org blocked (403)** → install via Aliyun mirror `https://mirrors.aliyun.com/pypi/simple/`.
- Python 3.12; project `.venv` present (has `openpyxl`; no `pandas`/`matplotlib`/`markdown`,
  hence `build_docs.py` is dependency-free).
- Do **not** consider SOXL for this work (explicitly excluded by the user).
- Never point at a live account without LPL pre-clearance.

## 9. How to pick up quickly
1. Read [`../README.md`](../README.md) (setup) → this file → the three [logic docs](README.md).
2. Start IB Gateway (paper, port 4002, API on). `python runner.py` from the project root.
3. For a safe order-path check: `python test_order.py AAPL` (places a 1-share bracket — flatten it after).
4. To refresh docs after a new backtest: `python docs/build_docs.py`.
