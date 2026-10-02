# PDH Breakout — Strategy Logic

> Source: [`strategies/pdh_breakout.py`](../strategies/pdh_breakout.py) · engine: [`equity_base.py`](../equity_base.py) · orders: [`equity_order.py`](../equity_order.py) · config block: `"PDH - 9.35"` in [`equity.json`](../equity.json)

## Edge thesis
The prior session's high (PDH) is a widely-watched level. A clean intraday break of it, **on volume and above session VWAP**, tends to attract continuation buying. This is the simplest and most mechanical of the three bots — one level, one direction (long), one confirmation stack.

## Universe & watchlist
Built once, right after the first window opens, in `build_watchlist()`:

1. **Scanner seed** — `TOP_PERC_GAIN` (IBKR `ScannerSubscription`, `STK.US.MAJOR`, `CORP`, price 20–200). Falls back to `universe_symbols` on empty/error.
2. **Price band** — prior-session close within `min_price`/`max_price` (20–200).
3. **Liquidity** — 30-day dollar-ADV ≥ `min_dollar_adv` (25,000,000).
4. **Pre-market RVOL** — ≥ `min_premarket_rvol` (1.5). *Missing history ⇒ keep* (distinct from a genuine 0).
5. Excludes the mega-caps in `exclude_symbols` (AAPL, MSFT, NVDA, AMZN, GOOGL, META).

For each survivor the prior-session **high** is cached as that symbol's PDH.

## Entry conditions (all must hold)
Evaluated per symbol each poll, only at a **new-bar-open boundary** (`is_new_bar`), acting on the **last completed 5-min bar** (`bars5[-2]` — never the forming bar):

| # | Gate | Rule |
|---|------|------|
| 1 | Trade window | ET now inside `09:35–11:30` **or** `14:00–15:30` |
| 2 | Breakout | `bar.close > PDH × (1 + breakout_buffer_pct)`  (buffer 0.1%) |
| 3 | Volume | `bar.volume ≥ vol_mult × avg(volume of prior 6 completed bars)` (`vol_mult` 1.5) |
| 4 | VWAP | session VWAP computed **from bars** (delayed-safe); `price > VWAP` (skip if `require_vwap:false`) |

## Levels (entry / stop / target)
```
trigger = PDH × (1 + breakout_buffer_pct)          # 0.1% above PDH
entry   = trigger + entry_offset_pct × PDH          # +0.05%
raw_stop= PDH × (1 − stop_pct)                      # 0.05% below PDH (structural)
stop    = min(raw_stop, entry × (1 − min_stop_pct)) # floored to ≥0.5% so sizing stays sane
R       = entry − stop
target  = entry + target1_R × R                     # target1_R = 2.0  → 2R
```
The tight structural stop (0.05% below PDH) is deliberately **floored to `min_stop_pct` (0.5%)** so a razor-thin stop can't explode share count; the target is measured off the *floored* stop so the printed R:R is honest. A signal is rejected if `R ≤ 0` or if realized R:R `< min_rr` (1.5).

## Position sizing
`fixed_stocks > 0` ⇒ exactly that many shares (currently **1**). Otherwise `qty = floor(strategy_capital × risk_per_trade_pct / (entry − stop))` = 1% of $100k risked at the stop, capped by `max_position_notional`.

## Trade management (`manage_open`)
- **Protective bracket** — TP (`LMT SELL`) + stop-**limit** child, attached to the parent and OCA-grouped, so protection is server-side the instant the entry fills (no naked long). PDH uses a **stop-limit** (`use_stop_limit=True`, band derived from `stop_limit_pct`) to cap slippage on the exit.
- **Breakeven** — at `breakeven_mult × R` (1.0R) the stop moves to entry.
- **Trailing** — from `trail_start_mult × R` (1.5R) the stop trails `high_water − trail_lock_mult × R` (0.5R).
- **EOD flatten** — checked every tick; hard flat at `eod_flatten_time` (15:55, pulled earlier on half-days).

## Order execution (entry) — the important part
`entry_order_type` in the config selects how the parent BUY is sent (see [`equity_order.py`](../equity_order.py) `place_protected_entry`):

- **`"LMT"` (current setting)** — a marketable-limit **chase walk**: rest a `BUY LIMIT` at `entry` and step it up over `entry_timeout_sec` toward `entry × (1 + max_chase_pct)`, never above that cap. Fills near the level; **no-fills (skips) if price has already run away.**
- **`"MKT"`** — a true market order: immediate fill, no price ceiling. On a stale/gapped signal it can fill far past the level.

> **Why this matters:** on the 2026-07-16 live run PDH used `MKT` on **delayed** data. An IR signal computed at ~79.58 filled a market order @ **84.64** — 6% past the level, above its own target. Switching PDH to `LMT` (+ live data) makes the entry bounded: it fills at the level or not at all. See [`pdh_breakout.performance.md`](pdh_breakout.performance.md) for the execution-gap discussion.

## Config keys (PDH block)
| Key | Value | Meaning |
|---|---|---|
| `entry_order_type` | `LMT` | bounded marketable-limit chase (was `MKT`) |
| `windows` | `[["09:35","11:30"],["14:00","15:30"]]` | two trade windows |
| `breakout_buffer_pct` | `0.001` | breakout trigger above PDH |
| `vol_mult` | `1.5` | breakout-bar volume confirmation |
| `entry_offset_pct` | `0.0005` | entry above trigger |
| `stop_pct` | `0.0005` | raw structural stop below PDH (then floored) |
| `stop_limit_pct` | `0.0025` | stop-limit band |
| `target1_R` | `2.0` | 2R target |
| `breakeven_mult` / `trail_start_mult` / `trail_lock_mult` | `1.0` / `1.5` / `0.5` | management |
| `max_chase_pct` | `0.005` | LMT chase ceiling (0.5%) |
| `entry_timeout_sec` | `30` | chase window |
| `min_stop_pct` (shared) | `0.005` | stop floor |
| `min_rr` (shared) | `1.5` | reject thin R:R |

## Known failure modes
- **Delayed data** (`market_data_type: 3`) makes every signal ~15 min stale — with `LMT` you mostly no-fill; with `MKT` you chase. Run on **live data** (`market_data_type: 1`).
- **Whippy/rangebound days** produce false breakouts that tag the floored stop.
- **Selection/regime dependence** — the backtested edge leans on high-beta momentum names in a trending window (see performance doc caveats).
