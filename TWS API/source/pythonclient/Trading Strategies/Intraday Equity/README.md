# Intraday Equity Bots (IBKR / ib_async) — PDH · ORB Stocks-in-Play · NR7 Compression

Long-only, intraday-only, ≤1% risk-at-stop automated equity bots on Interactive Brokers
(`ib_async`), config-driven like the Iron Condor bot, defaulting to **paper account
`DU672616`**. Built from the ranked strategy research in `Intraday Trading Strategies/`,
then hardened against an adversarial design review and an adversarial code review.

> **STATUS: paper-validation candidate, NOT live-ready.** It compiles, imports, and passes
> the logic checks below, but it has **not** been run end-to-end against a live TWS. Do the
> paper-validation checklist before risking anything — and never point it at a live account
> without LPL pre-clearance.

## File map
| File | Purpose |
|---|---|
| `calendar_util.py` | ET timezone + NYSE holiday/half-day calendar; all wall-clock logic routes here |
| `market_data.py` | Global historical-data rate limiter, per-day JSON cache, volume-scale detection |
| `portfolio_risk.py` | Thread-safe risk manager: 1% risk-at-stop, aggregate-risk cap, sector cap, same-symbol lock, realized+unrealized daily-loss halt, persistence |
| `equity_order.py` | Limit-only entry (no market fallback) with atomically-attached TP+stop; native stop-market **and** stop-limit brackets; breakeven/trail modify; emergency flatten |
| `equity_base.py` | `EquityStrategyBase`: per-thread event loop, sizing w/ min-stop floor, RVOL, VWAP (tick 233), ATR/ADR, regime gate, EOD-flatten-every-tick, journal, run() template |
| `strategies/orb_stocks_in_play.py` | ORB "stocks in play" (#1) |
| `strategies/nr7_compression.py` | Volume/Compression NR7 (#2) |
| `strategies/pdh_breakout.py` | Previous Day High breakout (#5, simplest) |
| `runner.py` | Entry point: bootstrap equity snapshot + vol-scale, shared risk/cache/journal, one thread per active strategy |
| `equity.json` | Config (accounts, shared risk block, per-strategy params) |
| `requirements.txt` | Deps (install via the Aliyun mirror) |

## Run
```bash
# install deps (this machine: pypi.org is blocked, use the Aliyun mirror)
python -m pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/
# start TWS / IB Gateway (paper, port 7497, API enabled), then:
python runner.py
```

## Build and deploy
If you want a single-folder Windows deployment, run the local PowerShell script from this folder:
```powershell
.\build_and_deploy.ps1
```
This creates a local `.venv`, installs `requirements.txt`, builds `intraday_equity.exe` into `dist/`, and copies `equity.json` into the same folder.

PyInstaller one-file build (mirror the Iron Condor `.spec` pattern):
```bash
pyinstaller --onefile --name intraday_equity runner.py \
  --collect-all ib_async --copy-metadata ib_async --copy-metadata aeventkit \
  --collect-all tzdata
```
Keep `equity.json`, `cache_*.json`, `risk_state_*.json`, `logs/`, and the journal next to
the `.exe` (the code resolves paths from `sys.executable` when frozen).

## Per-strategy config & sizing (each strategy is its own book)
Every strategy block in `equity.json` carries:
| Key | Meaning |
|---|---|
| `strategy_capital` | The capital base this strategy sizes against (e.g. `100000`) — **independent of the account NetLiquidation**. ORB, NR7, PDH each treat their own 100k. |
| `risk_per_trade_pct` | Fraction of `strategy_capital` risked per trade per ticker (`0.01` = 1%). Used only when `fixed_stocks = 0`. |
| `fixed_stocks` | If `0`, size by 1% risk-at-stop. If `>0` (e.g. `2`), buy exactly that many shares per ticker (ignores % risk). |
| `max_concurrent_tickers` | Max simultaneous open tickers **for this strategy** (e.g. `5`). Each strategy has its own risk book + this cap. |

Sizing: `fixed_stocks>0 → qty = fixed_stocks`; else `qty = floor(strategy_capital × risk_per_trade_pct / (entry − stop))`. A shared `SymbolLock` still prevents two strategies from going long the same symbol at once.

## Logs & reports (per strategy, per day)
- **Daily log per strategy:** `logs/<Strategy>_<YYYYMMDD>.log` (one file per strategy per day).
- **Persistent analytics report per strategy:** `reports/report_<Strategy>.xlsx` — **accumulates across days** and is rewritten after every closed trade. Sheets:
  - `Trades` — every closed trade (date, time, ticker, sector, shares, entry/stop/target/exit, P/L, R-multiple, win/loss, reason).
  - `Daily` — per trading day: trades, wins, losses, win-rate %, gross P/L, avg R.
  - `ByTicker` — per (day, ticker): trades, wins, win-rate %, gross P/L, avg R.
  - `Summary` — overall strategy: total trades, win rate, total P/L, avg R, profit factor, largest win/loss, trading days.
- (`equity_journal_<date>.xlsx` still logs raw open/close events per strategy sheet.)

## How it works (per strategy thread)
`connect (own event loop)` → `wait for window` → `build_watchlist()` (universe/RVOL/gap or
nightly NR7 scan) → loop: **EOD-flatten check first every tick** → `manage_open` (breakeven
→ trail, detect TP/stop fills) → for each idle symbol `check_entry_signal()` → floor stop to
`min_stop_pct` → size at 1% risk-at-stop → portfolio risk gate → `place_protected_entry`
(limit entry + attached TP + stop) → register. Hard flat at `eod_flatten_time` (pulled
earlier on half-days).

## Adversarial code review — disposition of all 19 findings
**Fixed (all 6 high + all 6 med):** transmit=True on resize/modify (parked-modify bug);
no double market-data subscription + no wrong-feed `cancelMktData`; NR7 & PDH act on the
**last completed** 5-min bar (`bars[-2]`), not the forming bar; per-strategy unrealized
**summed** (not overwritten) in the halt check; locked reads in the risk manager;
`PendingCancel` guard on sibling cancel; NR7 target computed off the **floored** stop;
fractional VWAP stop buffer; EOD flatten waits for the real fill price + warns on non-fill;
rate limiter reserves-then-sleeps **outside** the lock.
**Fixed (correctness lows):** RVOL skips the forming bucket and returns `None` on missing
history (distinct from genuine 0, gated by `require_rvol`); ORB opening-range only cached
once the 09:35 bar exists; partial-fill protection failure → cancel children + flatten
(can't flip short).
**Deferred (documented, low):** `vol_scale` unit consistency (auto-detected, default 1 —
verify on your feed); `_spy`/`_vix` cache micro-race (benign redundant qualify); gate-vs-
register risk drift (mitigated: `max_chase_pct` defaults 0 so fill ≤ limit).

## Known limitations / next iteration
- **Single-target brackets** with breakeven + trailing stop. Multi-tranche scale-out
  (PDH 2R/3R, ORB 1.5x/3x) config keys are reserved but **not yet implemented**.
- **Market-data entitlement:** VWAP (tick 233) and live bid/ask only populate with a live
  data subscription. On delayed/frozen paper data the VWAP gate silently fails — set
  `"require_vwap": false` per strategy for delayed-data paper smoke tests.
- **Static calendar** in `calendar_util.py` (2025–2027). Extend yearly.
- **No event-driven bars:** polls `reqHistoricalData` each tick (rate-limited). Fine for a
  handful of names; for large universes move to `reqRealTimeBars`/`barUpdateEvent`.

## Paper-validation checklist (do BEFORE trusting it)
1. TWS paper (`DU672616`), API on, port 7497. Confirm `bootstrap` logs a real
   `NetLiquidation` and a sensible `volume_scale` (expect 1).
2. Confirm `ticker.vwap` actually populates on your data entitlement; if not, set
   `require_vwap: false` (and know the VWAP filter is then off).
3. Fire ONE name end-to-end: watch the bracket appear in TWS (entry + TP + stop), verify
   the stop is **server-side immediately** after the entry fills (no naked long).
4. Verify breakeven + trail actually move the stop in TWS (not just locally).
5. Force an EOD flatten (set `eod_flatten_time` a few minutes out) and confirm the position
   closes and the journal records the real fill.
6. Run all three together; confirm the shared caps hold (max concurrent, 2/sector,
   aggregate-risk, 3% daily-loss halt) and that two bots never both long the same symbol.
7. Only after a full clean paper session: consider a tiny live test — with LPL pre-clearance.
