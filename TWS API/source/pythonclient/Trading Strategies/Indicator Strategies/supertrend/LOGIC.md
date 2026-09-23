# Supertrend v1 — Strategy Logic

How the bot turns bars into orders, decision by decision. This documents the
**shipped code** in `supertrend_bot.py`. v1's distinguishing feature vs
[v2](../supertrendv2/LOGIC.md) is **partial take-profit** (profit-scaling on trend
trades); v1 has **no** mean-reversion sub-strategy.

---

## 1. Cadence

Evaluate **once per completed bar**, heartbeat between bars.

- On each poll (`poll_interval_sec`, default 30s) it checks the connection and
  catches any server-side stop fill.
- When a **new** `bar_size` bar closes, it pulls `hist_duration` of history for
  the configured `market_hours` session and computes indicators on the **last
  completed bar** (`bars[-2]`; `bars[-1]` is still forming).
- At most **one entry per completed bar per symbol**; the server-side stop is the
  backstop between polls.

`hist_duration` is auto-derived to cover the largest indicator warmup (ATR, DEMA,
ADX), then clamped to a per-bar-size max so small-bar all-hours pulls don't time
out.

---

## 2. Indicators (from the shared `Indicators/` package)

| Indicator | Used for |
|---|---|
| **Supertrend** `ST(atr_period, multiplier)` | trend direction + the trailing stop line |
| **DEMA** (default 200) | core entry gate (`close > DEMA` long / `< DEMA` short) |
| **ADX** | optional trend-strength gate; also an input to the regime classifier |
| **Choppiness Index** | regime classifier (TREND vs CHOP) |
| **RSI** | optional momentum gate |
| **MACD** | optional momentum gate |

---

## 3. Regime classification (`current_regime`)

Each bar the tape is labelled **TREND** or **CHOP** via Choppiness + ADX with
**hysteresis** (state persisted per symbol in `self._regime`):

- Flip → **TREND** only when `CHOP < chop_trend` **AND** `ADX > adx_trend`.
- Flip → **CHOP** only when `CHOP > chop_range`.
- Otherwise **hold** the current regime. (Starts CHOP — conservative.)

Defaults: `adx_trend=25`, `chop_trend=38`, `chop_range=61`, periods 14.

---

## 4. Entry pipeline (per symbol, once per bar)

```
new bar? ── no ──▶ heartbeat only (connection + stop-fill check)
   │ yes
   ▼
inside entry_window?  ── no ──▶ manage existing position only
   │ yes
   ▼
desired side from direction + Supertrend trend  (LONG / SHORT / FLAT)
   │
   ▼
DEMA gate  (close vs DEMA)
   │ pass
   ▼
ADX gate   (if enabled: ADX ≥ threshold)
   │ pass
   ▼
regime_filter enabled?
   ├─ yes ─▶ regime gate:
   │          TREND ─▶ enter (rsi+macd only if trend_momentum)
   │          CHOP  ─▶ stand_aside (no entry)  OR  momentum (require rsi+macd)
   └─ no  ─▶ always-on rsi + macd gates (if enabled)
   │ pass
   ▼
OPEN / TOP UP to target
```

Notes:
- When `regime_filter` is **on**, it **supersedes** the always-on rsi/macd gates
  (applies momentum by regime instead). DEMA still applies independently.
- Optional `entry_on_flip_only` requires a fresh Supertrend flip to enter.
- A filter that cannot be evaluated (insufficient history) **blocks** the entry —
  the bot never trades a filter it can't compute.

v1 has **no** `mean_revert` CHOP action — that is v2 only. In CHOP, v1 either
stands aside or requires momentum.

---

## 5. Position management (`manage_symbol`)

For a held position each bar:

1. **Partial take-profit first** (if `partial_tp` enabled) — see §6.
2. **Signal unchanged** → trail the single protective stop toward the Supertrend
   line (only ever in the favourable direction).
3. **Signal flipped** → cancel the stop and flatten (market). In `long_short` it
   immediately opens the opposite side; otherwise it goes to cash.

Entry / top-up mechanics (`open_position`):
- Buy only the **shortfall** (`target − held`) with a market order **+ an attached
  server-side protective stop** at the Supertrend line (parent `transmit=False` →
  stop child `transmit=True`, so there's never an unprotected position).
- Then **cancel every existing stop and place ONE consolidated stop** for the full
  quantity — never stacked stops.

---

## 6. Partial take-profit / scale-out (`partial_tp`) — v1's feature

R = |entry − initial stop|. On entry, `_setup_tranches` builds a scale-out ladder
(default `[{fraction: 0.5, r_multiple: 2}]` = trim 50% at 2R). No-op if
`fixed_stocks < 2` (can't trim half of one contract).

- **Resting take-profit orders** (`place_take_profits`) — a real LIMIT order per
  tranche for its qty at the R target, **visible in TWS** (not a synthetic
  in-code price cross). GTC (swing) or DAY (intraday).
- **`check_take_profits`** detects a TP *order fill*, books the partial to the
  trade CSV as a `PARTIAL_<n>R` leg, shrinks the position, and — once a trim at
  `≥ tighten_after_r` fills — switches the **runner** from the Supertrend trail to
  a `trail_r`-R trailing stop (locks profit), then resizes the protective stop to
  the reduced qty.
- **`_cancel_tps`** kills the resting TP on any stop/flip/EOD exit so a half-qty
  TP can't orphan into a new position; **`_cancel_stray_tps`** + re-arm logic in
  `sync_existing` restore stop + TP after a restart/reconnect.

Backtest verdict (see [PERFORMANCE.md](PERFORMANCE.md)): 50%@2R + 1R runner beats
the plain exit in both regimes; laddering into smaller/earlier 1R trims does not
help.

---

## 7. Sizing

- **`fixed_stocks > 0`** → target total position; the bot tops up to it (buys the
  shortfall), so a restart never stacks duplicates. Authoritative over the
  notional cap (which only warns).
- **`fixed_stocks = 0`** → `qty = floor(strategy_capital × risk_per_trade_pct /
  (entry − stop))`, with the stop floored at `min_stop_pct` and capped by
  `max_position_notional`.
- Futures size by contract multiplier (MNQ $2/pt, MES $5/pt).

There is always **one** protective stop per symbol, sized to the full held qty.

---

## 8. Order mechanics & sessions

- **RTH** — market entries, native STP stop.
- **ETH / 24H** — orders flagged `outsideRth`; entries use a **marketable-limit
  chase** (walks the limit up to `max_chase_pct` over `entry_chase_levels`) since
  IBKR rejects plain market orders outside RTH. Stops: STP for futures (CME
  accepts 24h), STP-LMT for outside-RTH equities.
- **24H equities overnight** (~20:00–04:00 ET) routes to the IBKR **OVERNIGHT**
  venue (LIMIT-only, no GTC) → a **synthetic stop** (monitor price each bar, fire
  a marketable limit exit on breach). Futures never use OVERNIGHT.

---

## 9. Startup / reconnect reconciliation (`sync_existing`)

On startup and every reconnect: read a **live** position snapshot
(`reqPositions`, not the cache — which is empty right after reconnect and caused
duplicate entries), adopt any existing position per symbol (scoped to the
account), then either flatten (if the Supertrend already flipped against it) or
top up to target and consolidate all stops into one at the current Supertrend
line. Also cancels stray TP orders and re-arms.

Because swing stops are **GTC and server-side**, open positions stay protected
even while the Python process is down.

---

## 10. Connection resilience (v1's `_safe_sleep`)

v1 wraps all loop/reconnect waits in **`_safe_sleep()`**, which pumps events via
`ib.sleep()` while connected (needed to process fills/errors), else plain-sleeps,
and swallows both `Exception` **and** `asyncio.CancelledError` (a `BaseException`
that `except Exception` would miss). This is the fix for the "bot doesn't come
back after IB Gateway's daily restart" bug — the socket peer-closes, `ib.sleep()`
raises, and without this the strategy thread would die. The `run()` loop body is
also guarded so a fresh reconnect + re-sync happens on the next tick.

> This is one of the two things v2 lacks (the other being partial-TP). If porting
> features between branches, carry `_safe_sleep` into v2.
