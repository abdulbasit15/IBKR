# Indicator Strategies — Supertrend bot (IBKR / ib_async)

A single, fully **config-driven** indicator strategy that follows the Supertrend on the
chosen timeframe. Works on **any stock, any timeframe, any `ST(atr_period, multiplier)`**,
and any **trade direction** — set it all in `supertrend.json`. The example config is
`long_only` `ST(10,3)` on 15-minute bars.

### Direction modes (`direction`)
| Mode | Behavior |
|---|---|
| `long_only` | **Long when bullish, cash when bearish, never short.** e.g. "buy & hold SOXL, sell when the indicator turns bearish, re-buy when it turns bullish." |
| `short_only` | **Short when bearish, cash when bullish, never long.** (Requires shortable/borrowable shares + margin.) |
| `long_short` | **Always in the market** — long when bullish, **flip to short** when bearish, and back. |

In every mode the protective stop is the Supertrend line on the correct side (below price
for a long, above price for a short) and trails toward price as the trend extends; the
position is exited (or reversed, in `long_short`) on the Supertrend flip.

It reuses the conventions of the sibling `../Intraday Equity` bots (ib_async, own event
loop, rate-limited historical data, acts on the **last completed bar**, atomic
server-side stop so there's never a naked long, long-only asserts, 1%-risk sizing).

> **STATUS: paper-first, NOT live-ready.** Syntax-checked and the Supertrend math is
> verified bit-for-bit against the validated backtest engine (0 mismatches over 16,100
> SOXL 15-min bars). It has **not** been run end-to-end against a live TWS/Gateway. Do the
> paper checklist below first, and never point it at a live account without LPL
> pre-clearance.

## Files
| File | Purpose |
|---|---|
| `supertrend_bot.py` | The bot: Supertrend indicator, entry/exit, server-side trailing stop, sizing, logging |
| `supertrend.json` | Config — symbols, timeframe, ST params, mode, sizing, account/port |
| `requirements.txt` | `ib_async==2.1.0`, `tzdata` |

## How it trades (per symbol, every poll)
1. Pull `bar_size` history, compute Supertrend on the **last completed** bar (`bars[-2]`).
2. Decide the **desired side** from `direction` + the Supertrend trend (see the table
   above): LONG, SHORT, or FLAT.
3. **Flat + a side is wanted** → enter with a marketable limit (BUY for long / SELL for
   short) and a **server-side protective stop** attached at the Supertrend line (transmit
   chained, so the stop is live the instant the entry fills — no unprotected position).
   Stop is **GTC** in swing mode, **DAY** in intraday mode.
4. **Holding + signal unchanged** → trail the stop toward the Supertrend line (up for a
   long, down for a short; never the wrong way, always kept on the protective side of price).
5. **Holding + signal changed** → cancel the stop and **flatten** (market order). In
   `long_short` it immediately opens the opposite side; otherwise it goes to cash and waits.
6. At most **one entry per completed bar per symbol** (prevents same-bar re-entry churn
   after a stop-out). The server-side stop is the backstop if price gaps between polls.

## Run
```bash
# from this folder; install into a venv (pypi.org is blocked on LPL -> Aliyun mirror)
python -m pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/
# start IB Gateway / TWS (paper, API enabled, port matches supertrend.json), then:
python supertrend_bot.py                # uses supertrend.json next to the script
python supertrend_bot.py my_config.json # or pass another config
```
You can reuse the sibling project's venv: `../Intraday Equity/.venv/Scripts/python.exe`
(it already has `ib_async` 2.1.0).

## Config reference (`supertrend.json`)
| Key | Meaning |
|---|---|
| `host` / `port` / `client_id` / `account` | TWS/Gateway connection. Defaults: `127.0.0.1` / `4002` / `40` / paper `DU672616`. Use a `client_id` not used by the other bots (they use 30/31/32). |
| `market_data_type` | `1` live, `2` frozen, `3` delayed, `4` delayed-frozen. Paper `DU672616` has **no live sub → use `3`**. (Signals run off historical bars, which work on delayed.) |
| `direction` | `long_only` (default) / `short_only` / `long_short` — see the table at the top. |
| `symbols` | Any list of US equities, e.g. `["AAPL","NVDA","AMD"]`. |
| `bar_size` | Any IB bar: `"5 mins"`, `"15 mins"`, `"30 mins"`, `"1 hour"`, `"1 day"`, … |
| `supertrend.atr_period` / `.multiplier` | The ST config, e.g. `10` / `3.0` = ST(10,3). |
| `hist_duration` | History pulled per evaluation (default auto: `10 D` minute / `30 D` hour / `1 Y` day). Must comfortably exceed `atr_period`. |
| `use_rth` | `true` = regular hours bars only (recommended for intraday timeframes). |
| `intraday_mode` | `false` = **swing** (hold overnight, GTC stop, exit only on flip/stop). `true` = **intraday** (flatten all at `eod_flatten_time`, DAY stop). |
| `eod_flatten_time` | ET flatten time when `intraday_mode` is true (e.g. `"15:55"`). |
| `entry_window` | `[start, end]` ET — **new** entries only inside this window. Exits/stops always active. |
| `entry_on_flip_only` | `false` (default) = enter whenever the regime is bullish (matches the backtest `want_long` model). `true` = require a fresh bear→bull flip (avoids chasing an extended trend). |
| `poll_interval_sec` | Seconds between evaluation passes (default 30). |
| `sizing.fixed_stocks` | `>0` → buy exactly that many shares (ignores % risk). `0` → 1%-risk-at-stop sizing. |
| `sizing.risk_per_trade_pct` | Fraction of `strategy_capital` risked to the stop when `fixed_stocks=0` (`0.01` = 1%). |
| `sizing.strategy_capital` | Capital base the % risk sizes against (independent of account NetLiq). |
| `sizing.min_stop_pct` | Floor on stop distance so a too-tight Supertrend line can't blow up share count. |
| `sizing.max_position_notional` | Per-name notional cap. |
| `max_concurrent_positions` | Cap on simultaneous open names. |
| `entry_offset_pct` / `entry_timeout_sec` | Marketable-limit offset above price and how long to wait for a fill before cancelling. |

## Sizing
`fixed_stocks>0 → qty = fixed_stocks`; else `qty = floor(strategy_capital ×
risk_per_trade_pct / (entry − stop))`, with the stop floored to `min_stop_pct` and capped
by `max_position_notional`.

## Restart safety (swing)
On startup the bot calls `sync_existing()`: for every configured symbol it adopts any
pre-existing long (so it never double-buys after a restart) and re-links to a resting stop
on the book, or places a fresh protective stop at the current Supertrend line if none
exists. Because swing stops are **GTC and server-side**, open positions stay protected even
if the Python process is down.

## Paper-validation checklist (do BEFORE trusting it)
1. IB Gateway paper (`DU672616`), API on, port `4002`, `market_data_type: 3`. Confirm it
   logs `connected` and per-symbol Supertrend state without `hist error`.
2. Set `fixed_stocks: 1` and a couple of liquid symbols. Watch ONE entry fire: the BUY
   fills and a SELL stop appears **server-side immediately** in the Gateway (no naked long).
3. Confirm the stop **trails up** in the Gateway as the Supertrend line rises (not just in
   the log).
4. Force an exit: when the higher-TF Supertrend flips (or set a very short `bar_size` and
   wait), confirm it cancels the stop and the market SELL closes the position; check the
   row in `supertrend_trades.csv`.
5. For `intraday_mode: true`, set `eod_flatten_time` a few minutes out and confirm the EOD
   flatten closes everything.
6. Restart the process while a position is open and confirm `sync_existing()` adopts it
   (no duplicate buy).
7. Only after a clean paper session: consider a tiny live test — with LPL pre-clearance.

## Known limitations / next iteration
- **No holiday calendar** — only a weekend guard (the sibling `calendar_util.py` has a full
  ET holiday/half-day calendar if you want to wire it in). On a holiday IB simply returns
  no fresh bars; entries won't fire but run it on trading days.
- **Polls `reqHistoricalData` each tick** (rate-limited). Fine for a handful of names; for
  large universes move to `reqRealTimeBars` / `barUpdateEvent`.
- **Single position per symbol**, single Supertrend timeframe. No multi-timeframe
  confirmation here (the SOXL research's "triple-screen" would be a separate strategy).
- **Delayed data**: signals use completed historical bars (work on delayed). There is no
  live-quote VWAP/again gate — by design, Supertrend is the only filter.
- Entry uses a marketable limit with a short chase via `entry_offset_pct`; in fast markets
  a fill may be slightly worse than the trigger.
