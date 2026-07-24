# Supertrend Bot — Session Handover

_Last updated: 2026-07-18. Covers the RSI/MACD momentum filters, the regime-adaptive gate, the
supporting backtests, and the current deployed config. Read this before changing the strategy._

## Location (moved 2026-07-18)
All supertrend source/config/scripts now live in **`Trading Strategies/Indicator Strategies/supertrend/`**
(previously sat directly in `Indicator Strategies/`). The shared `Indicators/` package is now TWO levels
up; the bot resolves it by walking up the tree, and the build script uses `--paths ..\..`. The separate
`supertrendv2/` bot and shared `README.md`/`BUILD_AND_DEPLOY.md` stayed in `Indicator Strategies/`. Old
generated `dist/`/`build_pi/` were left behind (stale) in `Indicator Strategies/`; the next `.\supertrend.ps1`
run rebuilds fresh ones inside this `supertrend/` folder.

## TL;DR — current deployed state
- **Live config** (`supertrend.json`), paper account `DU672616`, IB Gateway port 4002:
  - `DU672616_MNQ_15m` and `DU672616_MES_15m` — futures, **15-min**, `long_short`, 24H.
  - Filters: **DEMA(200) ON + regime gate ON (stand_aside)**; RSI/MACD present but **off** (regime supersedes them).
  - **partial_tp ON (50%@2R, runner trails 1R)**; `fixed_stocks: 4` (so half=2 actually trims), `max_position_notional: 500000`.
  - `hist_duration: 30 D` (warms DEMA200/ADX/Choppiness on 15m).
- **Not yet rebuilt/redeployed.** The regime logic is new *code*, so the running `dist/` exe must be
  rebuilt: `.\supertrend.ps1` then restart the exe. (Config-only changes don't need a rebuild, but the
  regime feature does.)
- Environment: Python 3.12 (`...\Python312`), `ib_async` 2.1.0, IB Gateway paper on 127.0.0.1:4002.

## What was added to the code

### 1. New indicator — Choppiness Index
`../../Indicators/trend/choppiness.py` (new). `choppiness()` pure math + `choppiness_value()` config-driven,
same pattern as the other indicators. Range 0–100; >~61 = choppy, <~38 = trending. Bundled into the exe
automatically via `collect_submodules('Indicators')`.

### 2. RSI + MACD momentum filters (`supertrend_bot.py`)
Reuse existing `../../Indicators/momentum/rsi.py` and `macd.py`. Gate entries so momentum AGREES with the
Supertrend direction; a filter that can't be evaluated blocks the entry (same convention as DEMA/ADX).
- `rsi_filter`: `{enabled, period=14, long_min=50, short_max=50}` — LONG needs RSI>long_min, SHORT needs
  RSI<short_max. Shorthand `"rsi": 50`. Method `rsi_filter_ok`.
- `macd_filter`: `{enabled, fast=12, slow=26, signal=9}` — LONG needs hist>0, SHORT needs hist<0. Method
  `macd_filter_ok`.

### 3b. Partial take-profit / scale-out (`supertrend_bot.py`)
- Config `partial_tp`: `{enabled, trail_r=1.0, tighten_after_r=2.0, tranches:[{fraction, r_multiple}]}`.
  Default ladder = `[{0.5, 2}]` (trim 50% at 2R).
- `_setup_tranches()` builds the ladder on entry (R = |entry−initial stop|; tranche qty = round(frac*Q),
  capped; remainder = runner). No-op if Q<2. `check_partial_tp()` fires reached tranches (marketable
  exit via `flatten`), logs each as a `PARTIAL_<n>R` CSV leg, resizes the protective stop to the
  reduced qty, and after a trim at ≥`tighten_after_r` switches the runner to a `trail_r`-R trailing
  stop (via `trail_mode="oneR"` handled in `_trail`). Wired into `manage_symbol`'s same-side branch
  before the trail; exits/stops/flips still apply to the remainder.
- Backtest verdict (see `backtest/mnq_mes_tranche_scaleout.txt`): 50%@2R (or 33/33@2,3) beats plain
  exit; laddering into smaller/earlier 1R trims does NOT help. Needs `fixed_stocks ≥ 2`.

### 3. Regime-adaptive gate (`supertrend_bot.py`) — the main new feature
- Config `regime_filter`: `{enabled, adx_period=14, chop_period=14, adx_trend=25, chop_trend=38,
  chop_range=61, chop_action="stand_aside"|"momentum", trend_momentum=false}`.
- `current_regime(symbol, bars)` — classifies TREND vs CHOP each bar via **Choppiness Index + ADX** with
  **hysteresis** (state persisted in `self._regime[symbol]`): flip→TREND when CHOP<chop_trend AND
  ADX>adx_trend; flip→CHOP when CHOP>chop_range; else hold.
- `regime_gate_ok(symbol, bars, side)` — TREND: allow (require RSI+MACD only if `trend_momentum`);
  CHOP: `stand_aside` (no new entries) or `momentum` (require RSI+MACD).
- **Only NEW entries are gated. Stops/trailing/flip-exits are never gated.**
- **When `regime_filter` is enabled it SUPERSEDES the always-on RSI/MACD gates** (applies momentum by
  regime instead). It does NOT override DEMA — DEMA still applies independently if enabled.
- Entry-gate order in `manage_symbol`: DEMA → ADX → (regime gate  OR  rsi+macd if regime off) → open.
- Per-bar status log now prints RSI / MACD / REGIME (e.g. `REGIME TREND (CHOP 24/ADX 41)`).

### Config files
- `supertrend.json` (deployed) — MNQ/MES switched to 15m + DEMA + regime stand_aside (see TL;DR). Header
  comments document the momentum + regime filters.
- `supertrend - futures.json` — documented `rsi_filter` / `macd_filter` / `regime_filter` templates
  (all disabled by default) globally and per-strategy.

## Key findings from backtests (reports in `backtest/`, scripts in `backtest/scripts/`)
1. **Raw Supertrend alone is marginal** — whipsaws badly in chop (win rate ~30%, PF often <1.1). Matches
   the online literature.
2. **RSI>50/<50 momentum filter helps** win rate (+6–10pts) and drawdown, esp. 30m/1h. MACD similar but
   more mixed. **DEMA/ADX trend gates mostly just DELAY entries** (redundant with Supertrend) and hurt in
   clean trends.
3. **Regime gate (stand-aside in chop) is the biggest win**: over full multi-regime continuous history it
   ~**halves max drawdown** and beats the always-on RSI+MACD config in **5/6 series**. It's *defense in
   chop, offense in trends* — it does NOT profit in chop, it avoids it.
4. **Timeframe matters**: regime gate wins big on **15m**; **ST+DEMA** is best on **30m**; raw **ST / ST+DEMA**
   best on **1h** (higher TFs already clean, so the gate over-filters). → hence live config is on 15m.
5. **DEMA on top of the regime gate is ~a wash** (slightly lower drawdown, slightly less upside). Kept ON
   per user preference for the drawdown benefit.

## CRITICAL data gotcha (see also memory `backtest-data-placeholder-bars`)
- A single **far-dated** futures contract (e.g. MNQU6) returns **zero-volume flat placeholder bars**
  (O=H=L=C) for hours it wasn't liquid — 20–32% of the 30m/1h files. They corrupt indicators and
  manufacture fake gap-trades. **Always filter `volume>0` before backtesting.** (Symptom if forgotten:
  ADX seed returns all-None → 0 trades with the ADX/regime filter; inflated P/L.)
- For multi-regime history use **continuous futures** (`ContFuture`, whatToShow="TRADES", useRTH=False).
  IBKR forbids `endDateTime` on continuous futures → request ONE big duration (no end date), don't chunk.
  Downloaded data lives in the Trade root: `MNQ_cont_{15mins,30mins,1hour}.csv`, `MES_cont_*.csv`
  (15m≈1y, 30m≈2y, 1h≈3y). Single-contract sets `MNQ_*_bt.csv` / `MES_*_bt.csv` also there.

## How to re-run / extend
- Scripts persisted to `backtest/scripts/` (they were built in a session scratchpad). Run with
  `py -3.12 <script>.py`. `backtest_compare/three/two.py` import `backtest_regime.py` (same folder).
  `backtest_regime.py` holds the canonical indicators + regime classifier used by the comparisons.
- Data downloaders: `download_contfut.py` (continuous, preferred), `download_mnq.py`/`download_mes.py`
  (single-contract). Need IB Gateway running on 4002.
- Key reports: `mnq_mes_regime_gate.txt` (regime validation), `mnq_mes_st_dema_regime.txt` (3-way
  ST vs ST+DEMA vs Regime), `mnq_mes_regime_dema_vs_nodema.txt` (DEMA's value on top of regime).

## Gateway-restart reconnect fix (2026-07-21)
**Bug:** on IB Gateway's daily restart the socket peer-closed and `ib.sleep()` in the `run()` loop
raised `ConnectionError: Socket disconnect` / `asyncio.CancelledError`. It was UNCAUGHT (and
`CancelledError` is a BaseException, so `except Exception` missed it), so each strategy thread
died and never reconnected. **Fix:** added `_safe_sleep()` (pumps events via ib.sleep while
connected, else plain sleep; swallows both error types) used for all loop/reconnect waits, and
wrapped the entire `while True` body in `except (asyncio.CancelledError, Exception)` that tears
down the client and lets the next `ensure_connected()` do a fresh reconnect + re-sync. Net effect:
a Gateway restart now just logs `main loop: ... — reconnecting on next tick` and the bot resumes
(the existing reconnect loop already retries through the Gateway-down window with backoff).
Recommend enabling Gateway auto-restart/auto-relogin so it comes back on its own. NEEDS REBUILD.

## Partial-TP now uses RESTING orders (2026-07-21)
**Was:** the profit target was SYNTHETIC — `check_partial_tp` fired a marketable order when price
crossed the level, so no target order was visible in TWS; and the futures stop was a STP-LMT that
could be fragile/hidden. **Now:** on fill the bot places (1) a native **stop-MARKET (STP) for the
FULL qty** — `reconcile_stops` uses STP for futures (CME Globex accepts it 24h; STP-LMT kept only
for outside-RTH *equities*), and (2) a **resting LIMIT take-profit for HALF the qty** at the 2R
target via `place_take_profits`. `check_take_profits` detects the TP *order fill* (not a price
cross), books the partial, shrinks the position, tightens the runner to a 1R trail, and resizes
the stop to the remaining qty. `_cancel_tps` (in `close_position`) kills the resting TP on any
stop/flip/EOD exit so it can't orphan into a new position; `_cancel_stray_tps` + re-arm logic in
`sync_existing` restore the stop+TP after a restart/reconnect (full qty >= target ⇒ arm TP; a
reduced qty ⇒ treat as a runner, trail 1R, no new TP). Verified offline (fake IB): STP full-qty
stop, LIMIT half-qty target, TP-fill → qty↓ + 1R lock + stop resized. NEEDS REBUILD.

## Open items / next steps (not done)
- **Deploy**: rebuild with `.\supertrend.ps1` + restart the `dist/` exe to activate the regime code.
- **Tier-2 (not built)**: to *profit* in chop (not just sit out), add a mean-reversion sub-strategy for
  the CHOP regime (RSI/Bollinger fade). Discussed, not implemented.
- Consider per-timeframe deployment (15m→Regime, 30m→ST+DEMA) if running multiple strategies.
- All new filters ship disabled in the template config; only the two live 15m futures strategies enable
  the regime gate. Equities strategies unchanged.
