# ORB "Stocks in Play" — Strategy Logic

> Source: [`strategies/orb_stocks_in_play.py`](../strategies/orb_stocks_in_play.py) · engine: [`equity_base.py`](../equity_base.py) · config block: `"ORB SIP - 9.35"` in [`equity.json`](../equity.json)

## Edge thesis
An **Opening Range Breakout** filtered to *stocks in play* — names with a meaningful opening **gap** and elevated **relative volume**. The premise: when a genuinely-in-play stock clears its 09:30–09:35 opening-range high on volume and holds above VWAP, the day's directional move often extends. The edge is mostly in the **pre-market universe selection**, which IBKR has no native scan field for.

## Universe & watchlist
Built at the open in `build_watchlist()`:

1. **Scanner seed** — `TOP_PERC_GAIN ∩ HOT_BY_VOLUME` (intersect), `STK.US.MAJOR`, `CORP`, price 15–500.
2. **Price** — prior-session close ≥ `min_price` (15).
3. **Liquidity** — share-ADV ≥ `min_adv` (1,000,000), derived from dollar-ADV ÷ prior close.
4. **Gap** — `(today_open − prior_close) / prior_close ≥ min_gap_pct` (2%).
5. **Pre-market RVOL** — ≥ `min_premarket_rvol` (1.5); *missing history ⇒ keep*.
6. Always excludes `SPY`, `QQQ`; capped at `max_watchlist` (30).

## Opening range
The `09:30–09:35` 5-min bar defines `ORB_high`, `ORB_low`, `ORB_mid`, `height`. The range is only accepted when its height is a sane fraction of price: `orb_height_min_pct ≤ height/high ≤ orb_height_max_pct` (0.3%–5%). Degenerate/halted-open bars are rejected.

## Entry conditions (all must hold)
Evaluated on the **last completed 1-min bar** (`bars1[-2]`), only at a new-bar-open boundary, and only after `09:36` (one bar past the OR close):

| # | Gate | Rule |
|---|------|------|
| 1 | Trade window | ET now inside `09:35–11:00` |
| 2 | Breakout | `bar.close > ORB_high` (1-min close) |
| 3 | Volume | `bar.volume ≥ vol_mult × avg(prior 20 completed 1-min volumes)` (1.5) |
| 4 | VWAP | session VWAP from bars; `price > VWAP` (skip if `require_vwap:false`) |

## Levels (entry / stop / target) — range-based
```
entry  = ORB_high + atr_entry_buffer_mult × ATR(14,1d)     # small ATR buffer above the high
stop   = ORB_mid   if (height/high < min_or_height_pct)     # tiny range → mid
         else ORB_low                                       # normal → range low, NOT widened
target = entry + target.mult × ORB_height                   # entry + 2 × range height
```
This is the research "Stocks in Play" construction: the stop is the **structural range low** (or mid on a narrow range), never widened by the strategy, and the target is a **multiple of the opening-range height** (not a multiple of R). The base engine still applies a `min_stop_pct` safety floor for a degenerate tiny range so sizing can't blow up; with `orb_height_min_pct ≥ 0.8%` in the backtest the floor effectively never binds.

## Position sizing
Same engine as PDH: `fixed_stocks` (currently 1), else 1% risk-at-stop on `strategy_capital` ($100k), capped by `max_position_notional`.

## Trade management
Native **stop-market** child (not stop-limit) + TP, OCA-grouped and attached to the parent. Breakeven at `breakeven_mult` R (1.0), trail from `trail_start_mult` R (1.5) locking `trail_lock_mult` R (0.5). EOD flatten 15:55, checked every tick.

## Order execution
`entry_order_type` is currently **`MKT`** (true market order). To bound entry slippage the same way PDH now does, set it to `LMT` — the chase walk rests a `BUY LIMIT` at `entry` and steps up to `entry × (1 + max_chase_pct)` (0.5%), no-filling if price has already left the level.

## Config keys (ORB block)
| Key | Value | Meaning |
|---|---|---|
| `entry_order_type` | `MKT` | true market entry (consider `LMT`) |
| `windows` | `[["09:35","11:00"]]` | single morning window |
| `orb_height_min_pct` / `orb_height_max_pct` | `0.008` (research) / `0.05` | accepted OR height band |
| `atr_entry_buffer_mult` | `0.05` | ATR buffer above OR-high |
| `signal.vol_mult` | `1.5` | breakout-bar volume confirmation |
| `stop.min_or_height_pct` | `0.01` | below this, stop = ORB_mid |
| `target.mult` | `2.0` | target = entry + 2 × ORB height |
| `universe.min_gap_pct` | `0.02` | opening-gap gate |
| `universe.min_premarket_rvol` | `1.5` | pre-market RVOL gate |
| `max_chase_pct` / `entry_timeout_sec` | `0.005` / `30` | LMT chase (if enabled) |

## Known failure modes
- **Whipsaw** — the dominant risk. In the backtest, stops dwarfed targets (109 stops for −$93k vs 18 targets for +$34k); a wide, non-widened range low on a choppy morning gets tagged repeatedly. This strategy was **net negative** in the sample (see performance doc).
- **Scanner selection bias** — the backtest replays *today's* movers historically; live behaviour depends on the day's actual gappers.
- **Delayed data** breaks the 1-min breakout timing entirely; run live.
