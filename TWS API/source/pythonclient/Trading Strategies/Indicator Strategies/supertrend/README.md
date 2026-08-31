# Indicator Strategies — Supertrend bot (IBKR / ib_async)

A fully **config-driven** Supertrend trend-follower. Works on **any symbol, any timeframe,
any `ST(atr_period, multiplier)`**, any **trade direction**, and now runs **multiple
accounts / strategies concurrently** — all defined in `supertrend.json`. The protective
stop is the Supertrend line itself (server-side, trailed as the trend extends); the DEMA
filter is the core entry gate.

### Direction modes (`direction`)
| Mode | Behavior |
|---|---|
| `long_only` | **Long when bullish, cash when bearish, never short.** e.g. "buy & hold SOXL, sell when the indicator turns bearish, re-buy when it turns bullish." |
| `short_only` | **Short when bearish, cash when bullish, never long.** (Requires shortable/borrowable shares + margin.) |
| `long_short` | **Always in the market** — long when bullish, **flip to short** when bearish, and back. |

In every mode the protective stop is the Supertrend line on the correct side (below price
for a long, above for a short) and trails toward price as the trend extends; the position
is exited (or reversed, in `long_short`) on the Supertrend flip.

> **STATUS: paper-first.** The Supertrend math is verified bit-for-bit against the backtest
> engine, and connection resilience + the multi-account order logic have been exercised live
> on the paper account (`DU672616`). **Never point it at a live account without LPL
> pre-clearance.** Live accounts also require the login/gateway to actually manage those
> accounts (see *Accounts*).

## Files
| File | Purpose |
|---|---|
| `supertrend_bot.py` | The bot: Supertrend + DEMA, entry/top-up, server-side trailing stop, sizing, reconnect/watchdog, logging |
| `supertrend.json` | Config — connection, accounts, and one or more per-account strategies |
| `supertrend.ps1` | Build script (venv + PyInstaller one-file exe) |
| `requirements.txt` | `ib_async==2.1.0`, `tzdata`, `pyinstaller` |

---

## Multi-account / multi-strategy (`strategies[]`)
Put a `strategies` array in the config to run **one bot thread per entry, concurrently**,
each with its own account, symbols, timeframe, ST params, market hours, and sizing. Common
top-level keys (host/port, direction, intraday_mode, entry_window, poll, …) are inherited by
each strategy and can be overridden per strategy.

```json
"client_id_base": 40,
"accounts": ["U20181485", "U21953487", "DU672616"],
"default_account": "DU672616",
"strategies": [
  { "name": "acctA_5m", "account": "U20181485", "symbols": ["SOXL"],
    "bar_size": "5 mins",  "market_hours": "RTH",
    "supertrend": {"atr_period": 10, "multiplier": 3}, "dema_filter": {"enabled": true, "period": 200},
    "hist_duration": "10 D",
    "sizing": {"fixed_stocks": 1940, "min_stop_pct": 0.005, "max_position_notional": 100000} }
]
```

- **Client IDs**: each strategy gets a unique API client id (`client_id_base + index`, or a
  per-strategy `client_id` override) so the concurrent connections don't collide.
- **Account scoping**: each thread scopes positions/orders to its own `account`, so two
  strategies trading the same symbol on different accounts don't interfere.
- **Per-strategy trade log**: each writes `supertrend_trades_<name>.csv` (never a shared
  file) with `strategy` + `account` columns.
- If there's **no** `strategies` array, the bot runs a single strategy from the top-level
  keys (backward compatible).

### Accounts
IBKR serves **one login per gateway**. That login manages a fixed set of accounts
(`ib.managedAccounts()`). If a strategy's configured `account` **isn't** managed by the
connected login and the login manages exactly **one** account, the bot adopts that one (with
a log line) — this is what lets you paper-test a live-account config against the paper
gateway (`DU672616`). To trade several live accounts at once, the login must be an **FA /
advisor master** that holds them as sub-accounts. **Paper (`DU…`) and live (`U…`) accounts
cannot be served by the same gateway/port.**

---

## Market hours (`market_hours`) — RTH / ETH / 24H
Controls both which bars the **Supertrend/DEMA are computed on** and whether orders/stops
may act outside regular hours.

| Mode | Data pulled | Bars used for ST/DEMA | Orders / stops |
|---|---|---|---|
| `RTH` | `useRTH=True` | regular **09:30–16:00** ET | regular hours only |
| `ETH` | `useRTH=False` | extended **04:00–20:00** ET | flagged `outsideRth` |
| `24H` | `useRTH=False` | **all** hours (incl. overnight) | flagged `outsideRth` |

- ETH/24H set `outsideRth=True` on entry, stop, top-up and flatten orders so the protective
  **stop can trigger outside RTH** (critical for holding overnight).
- ⚠️ IBKR generally **rejects market orders outside RTH** (extended hours usually require
  limit orders). Entries here are market orders; stops are fine. If ETH/24H entries don't
  fill outside RTH, that's the reason.
- Legacy `use_rth: true/false` is still honored if `market_hours` is absent (`true`→RTH,
  `false`→ETH).

---

## How it trades (per symbol)
1. **Once per bar** (aligned to the bar close — e.g. every 5 min on 5-min bars), pull
   `bar_size` history for the chosen `market_hours` session and compute the Supertrend +
   DEMA on the **last completed** bar (`bars[-2]`). Between bars the loop only heartbeats
   (connection check + catch a server-side stop fill) — no extra history pulls.
2. Decide the **desired side** from `direction` + Supertrend trend: LONG, SHORT, or FLAT.
3. **Entry gate**: enter only when in the `entry_window`, on a genuinely new bar, and the
   **DEMA filter** passes (long only if `close > DEMA`, short only if `close < DEMA`).
   Optionally require a fresh flip (`entry_on_flip_only`).
4. **Enter / top up to target** (see *Sizing*): buy only the **shortfall** = `target − held`
   with a **market order + attached server-side stop** at the Supertrend line, then
   **cancel every existing stop and place ONE consolidated stop for the full position**.
5. **Holding + signal unchanged** → trail the single stop toward the Supertrend line (never
   the wrong way).
6. **Holding + signal changed** → cancel the stop and **flatten** (market). In `long_short`
   it immediately opens the opposite side; otherwise it goes to cash.
7. At most **one entry per completed bar per symbol**. The server-side stop is the backstop
   between polls.

---

## Sizing (`sizing`) — `fixed_stocks` is a *target*
- `fixed_stocks > 0` → **target total position = that many shares**. The bot tops up to the
  target (`buys target − currently-held`) rather than buying a fresh block each time, so a
  restart/reconnect never stacks duplicate positions. `fixed_stocks` is **authoritative**:
  `max_position_notional` does **not** shrink it (it only logs a warning if the target
  exceeds the notional cap).
- `fixed_stocks = 0` → **1%-risk-at-stop sizing**:
  `qty = floor(strategy_capital × risk_per_trade_pct / (entry − stop))`, with the stop
  floored to `min_stop_pct` and capped by `max_position_notional`.

There is always **one** protective stop per symbol, sized to the **full** held quantity
(all prior/stacked stops are cancelled on every entry/top-up/adoption).

---

## Connection resilience
Designed to survive gateway hiccups and "logged in from my phone" interruptions:

- **Socket drop** → reconnects on a **fresh `IB()`** (avoids stale-client failures), then
  re-adopts positions/stops. Retries fast at first, then every `reconnect_backoff_sec`
  (default 60s); in swing mode it retries indefinitely, in intraday mode until EOD.
- **Connectivity lost (IB error 1100)** → the socket stays up, so it **waits in place** for
  restore (1102) rather than tearing down a healthy socket, then re-wakes the data farm.
- **Data-line contention** (a competing login steals market data → Error 162 timeouts
  *without* dropping the socket) → after `data_fail_reconnect_cycles` bar-evaluations with
  no data, it **forces a full session reset** (disconnect → reconnect) to recover.
- **`hist_timeout_sec`** bounds each history request so a stall fails fast instead of
  blocking ~60s.

---

## Run
```bash
# from this folder; install into a venv (pypi.org is blocked on LPL -> Aliyun mirror)
python -m pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/
# start IB Gateway / TWS (API enabled, port matches supertrend.json), then:
python supertrend_bot.py                # uses supertrend.json next to the script
python supertrend_bot.py my_config.json # or pass another config
```
Or build the one-file exe: `./supertrend.ps1` → `dist/supertrend_bot.exe` (config + logs
resolve next to the exe). You can reuse the sibling `../Intraday Equity/.venv`.

---

## Config reference (`supertrend.json`)
### Connection / top level
| Key | Meaning |
|---|---|
| `host` / `port` | TWS/Gateway. Defaults `127.0.0.1` / `4002` (paper gateway; `4001` = live). |
| `client_id` / `client_id_base` | Base API client id (default `40`). Each strategy gets `base + index` (or its own `client_id`). Keep clear of the equity bots (30/31/32). |
| `accounts` / `default_account` | The accounts the config intends to trade; effective account is resolved against the login's managed accounts at connect. |
| `market_data_type` | `1` live · `2` frozen · `3` delayed · `4` delayed-frozen. Paper `DU672616` has no live sub → use `3` (signals run off historical bars, fine on delayed). |
| `direction` | `long_only` (default) / `short_only` / `long_short`. |
| `intraday_mode` | `false` = **swing** (hold overnight, GTC stop). `true` = **intraday** (flatten at `eod_flatten_time`, DAY stop). |
| `eod_flatten_time` | ET flatten time when `intraday_mode` is true (e.g. `"15:55"`). |
| `entry_window` | `[start, end]` ET — new entries only inside this window (exits/stops always active). For ETH/24H, widen this to the session you want to trade. |
| `entry_on_flip_only` | `false` = enter whenever the regime matches. `true` = require a fresh flip. |
| `poll_interval_sec` | **Heartbeat** seconds (default 30) for connection/stop checks between bars. Price/signal is still evaluated **once per bar**. |
| `reconnect_backoff_sec` | Steady reconnect retry interval (default 60). |
| `hist_timeout_sec` | Per historical-request timeout (default 20). |
| `data_fail_reconnect_cycles` | Consecutive no-data bar-evals before forcing a session reset (default 4). |
| `bar_ready_buffer_sec` | Seconds after a bar close before evaluating, so data is ready (default 5). |
| `max_concurrent_positions` | Cap on simultaneous open names (per strategy). |
| `log_dir` / `trade_log_csv` | Log folder and CSV base name (per-strategy `_<name>` suffix is added). |

### Per-strategy (inside `strategies[]`, or top level for single-strategy mode)
| Key | Meaning |
|---|---|
| `name` | Label for logs / CSV / client-id display. |
| `account` | Account to trade (resolved to the managed account — see *Accounts*). |
| `symbols` | US equities, e.g. `["SOXL"]` or `["GOOG","AMZN"]`. |
| `bar_size` | Any IB bar: `"1 min"`, `"5 mins"`, `"15 mins"`, `"1 hour"`, `"1 day"`, … Controls both the signal timeframe and the per-bar evaluation cadence. |
| `market_hours` | `RTH` / `ETH` / `24H` — see the table above. |
| `supertrend.atr_period` / `.multiplier` | ST config, e.g. `10` / `3.0`. |
| `dema_filter.enabled` / `.period` | Trend-filter entry gate (default on, period 200): long only if `close > DEMA`, short only if `close < DEMA`. |
| `hist_duration` | History per evaluation. **Auto-clamped** to a safe max for the bar size (≤1 min→10 D, ≤5 min→40 D, <1 h→90 D, hours→1 Y, daily→~10 Y) so small-bar all-hours pulls don't time out. Only needs to exceed the DEMA/ATR warmup (a few hundred bars). |
| `sizing.fixed_stocks` | Target total shares (tops up; authoritative over the notional cap). `0` → % risk. |
| `sizing.risk_per_trade_pct` / `.strategy_capital` | % risk sizing when `fixed_stocks=0`. |
| `sizing.min_stop_pct` | Floor on stop distance so a too-tight Supertrend line can't blow up share count. |
| `sizing.max_position_notional` | Notional cap (applies to % risk; only warns for `fixed_stocks`). |

---

## Restart / reconnect safety
On startup and on every reconnect the bot runs `sync_existing()`:
- reads a **live** position snapshot (`reqPositions`, not the cache — which is empty right
  after a reconnect and previously caused duplicate entries),
- adopts any existing position for each configured symbol (scoped to the account),
- if the Supertrend has already flipped against it → cancels all stops and flattens,
- otherwise **tops up to the target** if under-sized and **consolidates all stops into one**
  at the current Supertrend line.

Because swing stops are **GTC and server-side**, open positions stay protected even while the
Python process is down.

---

## Paper-validation checklist (do BEFORE trusting it)
1. IB Gateway paper (`DU672616`), API on, port `4002`, `market_data_type: 3`. Confirm it
   logs `connected`, resolves the account, and shows Supertrend state without `hist error`.
2. `fixed_stocks: 1`, a couple of liquid symbols. Watch ONE entry: the BUY fills and a SELL
   stop appears **server-side immediately** (no naked long).
3. Confirm the stop **trails** in the Gateway as the Supertrend line moves.
4. Force a flip/stop exit; confirm the stop is cancelled, the market exit fills, and a row
   lands in `supertrend_trades_<name>.csv`.
5. **Top-up test**: hold N < `fixed_stocks`, restart; confirm it buys only the shortfall and
   ends with a **single** stop for the full quantity.
6. **Reconnect test**: log in from the mobile app to interrupt, then log out; confirm the bot
   detects the outage and resumes (watchdog forces a reset within `data_fail_reconnect_cycles`
   bars if needed).
7. For `intraday_mode: true`, set `eod_flatten_time` a few minutes out and confirm EOD flatten.
8. Only after a clean paper session: a tiny live test — with LPL pre-clearance.

---

## Known limitations / next iteration
- **No holiday calendar** — only a weekend guard. On a holiday IB returns no fresh bars, so
  entries won't fire; run it on trading days.
- **Market entries outside RTH** — IBKR usually requires limit orders in extended hours;
  ETH/24H entries may not fill outside RTH (stops are unaffected). Switch ETH/24H entries to
  marketable-limit if you need reliable extended-hours fills.
- **Over-target positions aren't trimmed** — the bot only tops *up* to `fixed_stocks`; it
  won't sell down if you're already above target (e.g. left over from a prior config).
- **Polls `reqHistoricalData` once per bar** (rate-limited). Fine for a handful of names; for
  large universes move to `reqRealTimeBars` / `barUpdateEvent`.
- **Single position per symbol**, single Supertrend timeframe (no multi-timeframe screen).
