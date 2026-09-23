# Supertrend v1 — Handover for the next AI / engineer

_Read this first. It orients you fast, then points at the details in
[README.md](README.md), [LOGIC.md](LOGIC.md), [PERFORMANCE.md](PERFORMANCE.md),
and [BUILD_AND_DEPLOY.md](BUILD_AND_DEPLOY.md). For the dated session-by-session
narrative (what changed when, and why), see the existing
[HANDOVER.md](HANDOVER.md)._

---

## 1. What this is, in three sentences

`supertrend_bot.py` is a config-driven IBKR (ib_async) Supertrend
trend-follower: enter with the Supertrend, gated by DEMA(200) + a regime filter,
with the Supertrend line as a server-side trailing stop. Its distinguishing
feature is **partial take-profit** (trim ½ at 2R with resting TP orders, then
trail the runner 1R). It is the **production line** — the branch to run live.

---

## 2. Orient yourself in 5 minutes

1. Skim the **module docstring** at the top of `supertrend_bot.py` — it's the
   canonical, maintained spec.
2. Read [LOGIC.md](LOGIC.md) §4–§6 (entry pipeline, management, partial-TP).
3. Read [PERFORMANCE.md](PERFORMANCE.md) §1 (the evolution chart) — this is why
   the current stack exists.
4. Look at `supertrend.json` (deployed) and `supertrend - live.json`.
5. For deployment mechanics read [BUILD_AND_DEPLOY.md](BUILD_AND_DEPLOY.md).

---

## 3. The v1 ↔ v2 relationship (do not lose this)

There is a sibling bot at [`../supertrendv2/`](../supertrendv2/) that shares ~95%
of this code. They diverge on **exactly one feature each**:

| Aspect | v1 (this) | v2 (`supertrendv2/`) |
|---|---|---|
| Shared core (ST, DEMA, ADX, RSI, MACD, regime, sizing, orders, reconnect) | ✅ | ✅ (same) |
| Profit scaling | **partial_tp** (trim ½@2R, runner trails 1R, resting TP orders) | ❌ absent |
| CHOP-regime extra strategy | — (stand_aside / momentum only) | **Tier-2 mean-reversion fade** |
| Gateway-restart hardening | **`_safe_sleep()`** | ❌ raw `ib.sleep()` |
| Backtest verdict | positive (partial_tp adds ~+$7.6k on 15m) | flat/slightly-negative at defaults |

They are **divergent branches**, not v1→v2 progression. v1 is production; v2 is
the mean-reversion experiment. To diff precisely:
```bash
cd "Trading Strategies/Indicator Strategies"
diff <(sed 's/[[:space:]]*$//' supertrend/supertrend_bot.py) \
     <(sed 's/[[:space:]]*$//' supertrendv2/supertrendv2_bot.py)
```

---

## 4. Key methods to know (`supertrend_bot.py`)

| Method | Role |
|---|---|
| `run()` / `manage_symbol()` | main loop; per-bar evaluation + entry pipeline |
| `current_regime()` / `regime_gate_ok()` | TREND/CHOP classification + entry gating |
| `open_position()` | entry mechanics (sizing, atomic entry+stop, chase, overnight) |
| `_setup_tranches()` | build the scale-out ladder on entry (R = |entry−stop|) |
| `place_take_profits()` / `check_take_profits()` | resting TP orders + fill detection |
| `_cancel_tps()` / `_cancel_stray_tps()` | kill/rearm TP orders on exit / reconnect |
| `reconcile_stops()` | one consolidated protective stop for the full qty |
| `sync_existing()` | startup/reconnect: adopt live position, flatten-or-topup, one stop, rearm TP |
| `_safe_sleep()` | Gateway-restart-safe wait (swallows `CancelledError`) — v1 only |
| `ensure_connected()` / `_connect_once()` | reconnect (fresh `IB()` each attempt) |

---

## 5. Deployed state (from `supertrend.json`)

Paper `DU672616`, IB Gateway port 4002:
- `DU672616_MNQ_15m` and `DU672616_MES_15m` — futures, **15-min**, `long_short`,
  24H.
- **DEMA(200) ON + regime gate ON (stand_aside)**; RSI/MACD present but off
  (regime supersedes them).
- **partial_tp ON** (50%@2R, runner trails 1R); `fixed_stocks: 4` (half = 2 so it
  actually trims); `hist_duration: 30 D`.
- Deploy on **15m** — every backtest series says 30m is the weak timeframe.

Any *code* change (not config-only) needs a rebuild: `.\supertrend.ps1` →
`dist/supertrend_bot.exe`, then restart the exe.

---

## 6. Gotchas & footguns (learned the hard way)

- **Placeholder bars.** A single far-dated futures contract returns zero-volume
  flat bars (O=H=L=C) for illiquid hours — 20–32% of the 30m/1h single-contract
  files. They corrupt indicators and manufacture fake gap-trades. **Always filter
  `volume>0` before backtesting**, and prefer continuous futures
  (`MNQ_cont_*.csv`) for multi-regime history. Symptom if forgotten: ADX seed
  all-None → 0 trades with the ADX/regime filter, and inflated P/L.
- **Partial-TP needs `fixed_stocks ≥ 2`.** Half of one contract is 0 → no-op.
- **TP orphans.** A resting half-qty TP that survives a full stop/flip can reopen
  a position — `_cancel_tps` (on every exit) and `_cancel_stray_tps` (on
  reconnect) exist to prevent this; keep them wired if you refactor exits.
- **Regime gate supersedes RSI/MACD** when enabled (it does not override DEMA).
  Don't expect the always-on momentum gates to fire while the regime filter is on.
- **Filters block when they can't compute.** Too little history → the entry is
  refused (by design). Widen `hist_duration` if you see "insufficient bars".
- **Paper vs live gateways don't mix.** One login per gateway; paper (`DU…`) and
  live (`U…`) can't share a port. If the configured account isn't managed by the
  login and exactly one is, the bot adopts it (logged). Multiple live accounts at
  once require an FA/advisor master login.
- **Market entries outside RTH** may not fill (IBKR usually wants limit orders in
  extended hours); the chase is marketable-limit for this reason. Stops are
  unaffected.

---

## 7. If you're asked to… (playbook)

- **"Improve exits/profit-taking"** → the tranche work is done; `backtest_partial.py`
  / `backtest_tranche.py` already showed 50%@2R + 1R runner is the edge and finer
  ladders don't help. Re-run those before changing `partial_tp` defaults.
- **"Add mean-reversion in chop"** → that's v2 (`../supertrendv2/`). Don't rebuild
  it here; port from v2 if you want both features in one bot (and note v2's fade
  underperforms at its defaults — see `../supertrendv2/PERFORMANCE.md`).
- **"Deploy / rebuild"** → [BUILD_AND_DEPLOY.md](BUILD_AND_DEPLOY.md);
  `.\supertrend.ps1` (PyInstaller one-file, `--collect-submodules Indicators`,
  `--paths ..\..`). Config-only changes don't need a rebuild.
- **"Backtest a change"** → scripts in `../../Historical Data/Futures/scripts/`,
  `py -3.12 <script>.py`; `backtest_regime.py` holds the canonical indicators +
  classifier the comparisons import; data in `../../Historical Data/data/`;
  results in `../../Historical Data/Futures/results/`.
- **"Validate before live"** → follow the paper checklist in
  [README.md](README.md) ("Paper-validation checklist").

---

## 8. Environment

- Python 3.12 (`...\Python312`), `ib_async==2.1.0`, `tzdata`. PyPI blocked on LPL
  → Aliyun mirror (`-i https://mirrors.aliyun.com/pypi/simple/`). Can reuse
  `../Intraday Equity/.venv`.
- IB Gateway/TWS, API enabled. Paper `DU672616` on `127.0.0.1:4002`
  (`4001` = live). `market_data_type`: `1` live, `3` delayed (paper has no live
  sub → use `3`).
- Shared `Indicators/` at `Trading Strategies/Indicators`, resolved by walking up
  the tree; bundled into the exe when frozen.

---

## 9. Guardrails

- **Paper-first, always.** Never point at a live account without **LPL
  pre-clearance**. Short modes need borrowable/shortable shares + margin.
- Backtest numbers are **in-sample, frictionless** — directional guidance, not a
  live-P/L forecast.
- Keep the invariant: **never an unprotected position, never stacked stops** — one
  consolidated server-side stop per symbol at all times.
