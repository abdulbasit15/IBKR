# Scalping v2 Bot — Session Handover

_Last updated: 2026-10-09 (late): switched to full-size NQ/ES/GC, added MYM/YM, added % return/DD to the reports. Read this before changing anything._

## Latest changes (2026-10-09, night 3): supertrend-style logs / trades / reports
- **Strategy instance name:** `<account>_<symbol>_<strategy>` (`_sname()`), e.g. `DU672616_NQ_ib_trend`, mirroring supertrend's `DU672616_MNQ_5m`.
- **Logs:** per instance per day in `logs/scalping_v2_<name>_<date>.log`, plus the combined `logs/scalping_v2_<date>.log`.
- **Trade CSV:** one per instance, `scalping_v2_trades_<name>.csv`.
  - Columns are supertrend's: `time,strategy,account,symbol,side,qty,entry,exit,stop,pnl,ret_pct,reason,hold`, plus `r_mult,entry_time,trade_id,commission`.
  - `pnl` is true $ net of commission. NOTE: supertrend's own `pnl` omits the contract multiplier (points × qty).
- **`scalping_v2_reports.py`:** a port of supertrend `reports.py`. It writes `reports/eod_report_<date>.html` and `reports/performance_report.html`, broken down by instance, instrument and strategy, with % of `account_size_usd`.
  - The bot calls it automatically once per day after the session (all flat, ≥ session end + 5 min).
  - Also available as `--reports [--date]` and `.\scalping.ps1 -Reports [-Date]`.
- **Sim test:** updated to the new CSV format; 105/105 trades matched.

## Earlier changes (2026-10-09, night 2): one PowerShell script
- `scalping.ps1` now does everything: it builds when needed, runs paper with auto-restart, and `-Live` runs the live config.
- `scalping_v2_build.ps1` and `scalping_live.ps1` were deleted.
- A rebuild no longer deletes `dist`, so logs, CSVs, state and edited configs survive. Use `-ResetConfig` to overwrite the dist configs.

## Earlier changes (2026-10-09, night): time windows + CL
- **New `scalping_v2_windows.py`:** re-runs each strategy with entries limited to each window: 3 sessions, full RTH, and hourly buckets. Each window runs in two modes: hold (to 2R / stop / 16:00) and flat (out at the window end). Parameters are unchanged.
  - Rendered in `backtest_results.html` ("Time windows").
  - Rendered in `stocks/Stocks_Report.html`: futures NQ/ES/GC, CL, YM, index ETFs and large-cap stocks, with Y1/Y2 columns.
  - ★ marks the bot's current window.
- **Futures window results** (1 lot standalone, % of $150k):
  - IB Trend 11:00 hold +31%/yr (flat at 11:30 only +6%).
  - ORB 09:30–11:30 flat +32%/yr with DD 5% (afternoon negative).
  - H2/L2 09:30–11:30 hold +20% (best hour 10:30–11:30 +23%; midday −8% to −13%).
  - Confluence 13:30–16:00 hold +20.5% (best hour 14:30–15:30; morning negative).
  - The configured windows are the best or near-best for every strategy. On stocks/ETFs, no window rescues H2/L2 or Confluence.
- **CL (crude) added, `enabled:false`:**
  - Data: `Historical Data/data/CL_cont_5mins_eth.csv`, a full-session 2Y ContFuture pull, clean from about Jul 2025.
  - `load_csv_bars` falls back to `_eth.csv`, and `prepare_bars` trims it to 09:30–16:00.
  - SPECS: CL $1000/pt, tick 0.01; MCL $100/pt. Both have `use_rth=False`.
  - Bot: the per-symbol `use_rth` flag makes history/today bars come from the full session, and the session end comes from `tradingHours`.
  - Results: IB Trend PF 0.87, H2/L2 0.76, Confluence 0.79, ORB 1.60 (but +0.03R/trade, IS PF 1.07). Not good enough, so it stays off.
  - CL rolls MONTHLY (CLX6 expires 2026-10-20); the bot re-resolves the front month daily.
- Parity re-checked (PASS); exe rebuilt.

## Earlier changes (2026-10-09, late)
- **Contracts switched to full-size NQ / ES / GC** (`scalping_v2.json` and `scalping_v2_live.json`). The reason: `supertrend_bot` trades MNQ/MES/MGC on the same paper account, and different contracts don't net, so the two bots no longer interfere.
  - The strategy symbol lists are now ib_trend [NQ, ES, GC] and the other three [NQ, GC].
  - `max_risk_usd` scaled up 10×. Commissions are $2.25/side (GC $2.42).
  - Live config: daily breaker $3,000.
  - Micros still work: just use the MNQ/MES/MGC keys.
- **Backtest data for full-size:** `scalping_v2_core.SPECS` has NQ/ES/GC/YM/MYM, each with a `data` key (NQ←MNQ, ES←MES, GC←MGC, YM←MYM). `scalping_v2_backtest` loads that micro CSV because it's the same underlying. A per-symbol `data_symbol` override is supported.
- **New config key `account_size_usd`** (150000). It's only used for the % figures in the reports.
- **YM added but `enabled:false`.** All four strategies lose on the Dow, with PF 0.62–0.96 in-sample and out-of-sample.
  - Data: `Historical Data/data/MYM_cont_5mins_rth.csv` (ContFuture 2Y pull; clean from Sep 2025).
- **Reports:**
  - `backtest_results.html` now shows yearly $/% and max DD $/% per strategy, per symbol and per variant, plus a Dow section.
  - `stocks/Stocks_Report.html` now contains everything in one place:
    - futures (NQ/ES/GC/YM matrix)
    - the strategy comparison: futures vs ETFs vs stocks
    - yearly R/% and DD R/% (at 0.5% risk per trade)
    - the futures bot portfolio
- **Results as configured (1 full-size contract per signal):** +$115k/yr = **+77%/yr on $150k, max DD $15.5k = 10.3%**, PF 1.57. With risk sizing at 0.5% per trade that becomes +35%/yr with an 8.5% DD (from 70.8R/yr and 17R max DD).
- **Re-verified after the switch:**
  - Parity 623/623 PASS.
  - Simulation: 510/510 trades matched (507 identical exits).
  - `--status` on the gateway: NQZ6 conId 563947726, ESZ6 515416632, GCZ6 462941472. History loads, GC is no longer blocked, and the supertrend MGC +4 position is correctly ignored.
  - `--test-orders NQ`: OK.
  - The exe needs rebuilding (`.\scalping.ps1 -Build`) to pick up all of this.

## Location
`...\TWS API\source\pythonclient\Trading Strategies\scalping-v2\`

The research behind it lives in `Trading Strategies\scalping-v1\`:
- `RR2_Strategy_Report.md`: the 2:1 study, 18 families
- `Windows_Report.md`: the RTH time-window study
- `Scalping_Strategies_Report.md`: the earlier scalping study

## TL;DR — current state
- **Built:** an intraday IBKR bot for MNQ/MES/MGC on RTH 5-min bars, running 4 strategies with 2:1 targets:
  - `ib_trend`: 11:00-confirmed IB breakout with the daily trend
  - `orb2nd`: ORB second break, flat by 11:30
  - `h2l2_trend`: Brooks H2/L2 with trend
  - `confluence_pb`: afternoon trend-confluence pullback
- **Single engine:** `scalping_v2_core.py` is the only strategy and simulator implementation. The bot replays today's bars through it every 5 minutes, so live == backtest by construction.
- **Verified offline:**
  - `scalping_v2_parity_test.py`: **PASS 617/617** trades (full history, every bar).
  - `scalping_v2_sim_test.py`: real bot code against a fake broker. Over the full year, **505/506** trades matched and **502** had identical exits. P&L was $12,127 vs the backtest's $12,013; the 3 differences are tick-rounded MGC confluence targets. This test caught and fixed the early-close bug: the bot now flattens before the 13:00/13:15 early close on half-days, using `contractDetails.liquidHours`. Output is in `sim_full.txt`.
  - `--check` passes for both configs.
- **Verified on IB Gateway paper (DU672616), Fri 2026-10-09 evening (market closed):**
  - `--status` resolved MNQZ6 (conId 815824267), MESZ6 (815824257) and MGCZ6 (751494403), loaded ~80 sessions of RTH history, and replayed the 10/09 session. MES `ib_trend` was long at 11:00; MNQ `confluence_pb` had 2 trades.
  - `--test-orders MNQ`: the 3-leg bracket was accepted (PreSubmitted) and cancelled. Order plumbing OK.
  - The foreign-exposure guard **blocked MGC**, because the account holds +4 MGCZ6 from the supertrend bot.
- **Exe built** with the build script, now `.\scalping.ps1 -Build` (`dist\scalping_v2_bot.exe`, ~30 MB, pandas/numpy bundled; pip used the Aliyun fallback). `--check` and `--status`
  verified from dist.
- **NOT yet run through a live RTH session.** First real test: Monday 2026-10-12. Things to watch:
  - fills
  - the target re-anchor on fill
  - h2l2 stop-entry expiry
  - window/EOD flatten
  - CSV rows

## Backtest (as configured, portfolio rules on), 2025-09-02 → 2026-10-07
Portfolio result: **PF 1.54, +$11.9k / 1-lot set, max DD $1.6k, Sharpe 2.9, 507 trades.** PF in-sample 1.82, out-of-sample 1.25.

| Strategy | Portfolio PF | Notes |
|---|---|---|
| ib_trend | 1.30 | MNQ 0.92 in portfolio mode (often blocked by an earlier orb2nd MNQ trade; 1.38 standalone) |
| orb2nd | 2.67 | |
| h2l2_trend | 1.65 | |
| confluence_pb | 1.25 | |

With strategies independent (`--no-portfolio`): PF 1.60, +$16.3k. See `backtest_results.html`.

**Caveats:**
- Only 13 months of data.
- The strategies and windows were *selected* from a 260-cell study, so expect live results to be weaker.
- Nothing is individually significant (t≈1.3).

## Files
| File | What |
|---|---|
| `scalping_v2_core.py` | `prepare_bars`, `add_indicators` (ATR/EMA/VWAP/daily trend/14d range, all causal); strategies `IBTrend`, `H2L2`, `ORB2nd`, `Confluence`; `Windowed` (entry window + flat/hold); `_run_day` (one engine: backtest mode, plus live mode `upto=L` → returns signal/busy/pending); `simulate`, `live_decision`, `metrics`. |
| `scalping_v2_bot.py` | `ScalpingV2Bot`; see Architecture below. |
| `scalping_v2_backtest.py` | Loads `../Historical Data/data/{SYM}_cont_5mins_rth.csv` + `_5m_recent.csv` (roll gap back-adjusted, start 2025-09-02), runs the config, applies the portfolio rules, writes `backtest_out/scalping_v2_bt_<strategy>.csv` (journal format), `scalping_v2_bt_summary.csv` and `scalping_v2_bt_all_signals.csv`. |
| `scalping_v2_report.py` | `backtest_results.html` (scorecard, equity SVG, monthly, variants incl. 2-tick slippage, validation). |
| `scalping_v2_parity_test.py` | Bar-by-bar live replay vs backtest; exit code 1 on mismatch. |
| `scalping_v2_sim_test.py` | FakeIB broker (MKT at open, STP trigger, stop-first, 1-tick target trade-through, OCA, parent→child activation) driving the real `ScalpingV2Bot`; compares the trade CSV with the backtest. |
| `scalping_v2.json` | Paper: port 4002, client 60, `dry_run` false. |
| `scalping_v2_live.json` | Live: port 4001, account "" (must set), breaker $300, tighter `max_risk_usd`, separate state/logs. |
| `configuration.html`, `README_BOT.md`, `backtest_results.html` | Docs. |
| `scalping.ps1`, `requirements.txt` | The ONE script for build + run (replaced 3 Qullamaggie-style scripts on 2026-10-09). <ul><li>Default: build if missing, then run paper supervised.</li><li>Switches: `-Build`, `-NoRun`, `-Live` (type LIVE), `-ResetConfig`, `-IndexUrl`.</li><li>A build never wipes `dist`; configs are copied only when missing.</li><li>The exe is self-tested with `--check` and rebuilt once if it comes out corrupt.</li><li>Requirements add pandas + numpy.</li></ul> |

## Architecture (bot)
- **`run_loop`:**
  1. `ensure_connected` (fresh `IB()` per attempt; same pattern as QM/supertrend).
  2. Weekday ≥ 09:00 → `day_init`:
     - `resolve_contracts`: ContFuture → Future(conId) front month, minTick and multiplier from IB.
     - `load_history` (`history_days` of 5-min RTH bars from the ContFuture).
     - `sync_from_ib`.
     - Flatten stale trades from earlier sessions.
     - `check_foreign`.
  3. Every 5-min boundary + `bar_delay_sec` from 09:35 to 16:00 → `evaluate(boundary)`:
     - `refresh_today`: "1 D" bars, keeps only complete bars, retries until the expected last bar is present, else skips.
     - For each symbol × strategy in `strategy_priority`: `C.live_decision` → on `signal`, call `place_trade`.
  4. Every tick, `manage_timers`: expire h2l2 stop-entries after 1 bar, cancel unfilled entries at the window end, flatten open trades at `exit_at`.
- **`place_trade`:**
  - Dedupe by trade id `SYM-strategy-YYYYMMDD-HHMM` (signal bar).
  - Checks: blocked, one-per-symbol, max trades, breaker, risk ≥ 4 ticks, size ≥ 1, `max_risk_usd`.
  - Places a bracket: parent MKT/STP plus children LMT tp and STP sl, GTC, OCA, `orderRef sv2|id|role`.
  - Writes the state first, then the orders.
- **`_apply_fill`** (from `execDetailsEvent` and from `reqExecutions` on sync; idempotent by execId):
  - On an entry fill: average price, status open, `_reanchor_target` (2R from the fill).
  - On an exit fill: once filled ≥ entry, `_close_trade` (CSV row, `day_pnl`).
  - Commission comes from `commissionReportEvent`, else the config estimate.
- **`flatten`:** cancel the children → `sync_from_ib` (a child may have just filled) → MKT for the remaining quantity of THIS trade, on the trade's own conId (`_contract_for`, roll-safe).
- **`check_foreign`:** blocks a symbol if the account position for that conId ≠ the bot's own open quantity, or if there are non-`sv2` working orders on it. It unblocks automatically when cleared. The guard exists because supertrend trades the same contracts on the same paper account (supertrend adopts positions it finds!).

## Known limitations / gotchas
- **Supertrend conflict (biggest):** `Indicator Strategies/supertrend` (client 40+) trades MNQ/MES/MGC 5m RTH on the same DU672616.
  - The guard blocks this bot's affected symbols, but supertrend may *adopt* this bot's positions.
  - Fix: run them on separate accounts, or remove the overlapping symbols from one of them.
- **IB error 321 at connect:** "Read-Only mode" on `ReqOpenOrders`/`ReqCompletedOrders` from ib_async's startup sync. It's harmless: `reqAllOpenOrders`, `reqExecutions` and `placeOrder` all work, as verified. If orders ever get rejected with 321, untick Gateway → Configure → Settings → API → "Read-Only API".
- **`history_days`=120:** IB returns ~80 sessions for this. That's enough for EMA20 trend + 14-day range; the backtest used longer warm-up, so tiny EMA differences are possible.
- **No back-fill:** if the bot starts after a signal bar, it does not chase that signal (by design).
- **Partial fills (qty > 1):** handled. On a stop-entry expiry the remainder is cancelled and the children are resized to the filled quantity, but this path is untested live.
- **`one_position_per_symbol=true`:** a pending h2l2 stop-entry also occupies the symbol for its 1-bar life. The backtest only counts filled trades, so there can be tiny differences.
- **H2L2 tick fix:** the research code guessed tick 0.25 for any price > 1000 (MGC should be 0.10). `scalping_v2_core` uses the real tick, so MGC h2l2 results differ slightly from `Windows_Report.md` (PF 1.52 vs 1.56).
- **Prices are rounded to the tick** for orders. The backtest uses raw levels, which causes a few-dollar P&L differences in the sim test.

## Suggested next steps
1. **Monday 10/12:** run `python scalping_v2_bot.py` (or the exe via `scalping.ps1`) through the session, after resolving the supertrend overlap.
2. **Daily:** check `logs/scalping_v2_<date>.log`, `scalping_v2_signals.csv` and `scalping_v2_trades_*.csv`. Compare with `python scalping_v2_bot.py --status` after the close (it shows what each strategy did that session).
3. **Weekly:** refresh the data CSVs (`Historical Data/Futures/scripts/download_recent_5m.py`), then compare `python scalping_v2_backtest.py` for the same dates with the live CSVs.
4. **Ideas** (backtest before enabling):
   - risk-based sizing
   - `one_position_per_symbol:false` (stacking)
   - `ib_trend` with `stop:"cap"`

## Test commands
```
python scalping_v2_bot.py --check
python scalping_v2_bot.py --check --config scalping_v2_live.json
python scalping_v2_parity_test.py            # ~3 min; must print PARITY PASS
python scalping_v2_sim_test.py --days 60     # must show bot trades == backtest trades
python scalping_v2_backtest.py --html
python scalping_v2_bot.py --status           # needs IB Gateway (read-only)
python scalping_v2_bot.py --test-orders MNQ  # paper only
```
