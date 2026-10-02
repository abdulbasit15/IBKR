# VWAP Pullback / Reclaim — Strategy Logic

> Source: [`strategies/vwap_pullback.py`](../strategies/vwap_pullback.py) · engine: [`equity_base.py`](../equity_base.py) · config block: `"VWAP PB - 9.45"` in [`equity.json`](../equity.json)

## Edge thesis
A **break-and-retest of session VWAP**. After a first impulse pushes price above a **rising**
session VWAP, a *controlled* pullback that re-tests the VWAP zone and holds above it on a
**higher low** often resolves into continuation. Go long when the next completed 5-min bar
**reclaims** — closing back above both VWAP and the pullback high — on volume. VWAP is the
intraday "fair value" line institutions lean on, so a held retest is a lower-risk entry than
chasing the initial breakout.

## Universe & watchlist
Same "stocks in play" screen as PDH (`build_watchlist()`): scanner seed → prior-close price
band (`min_price`/`max_price` 15–500) → dollar-ADV ≥ `min_dollar_adv` (25M) → pre-market RVOL
≥ `min_premarket_rvol` (1.5, *missing ⇒ keep*). Excludes `SPY`/`QQQ`; capped at `max_watchlist` (30).

## Entry conditions (all must hold)
Evaluated on the **last completed 5-min bar** (`bars5[-2]` = the trigger bar), only at a
new-bar-open boundary. VWAP is computed **from bars** (delayed-safe). Windows `09:45–11:30`
and `14:00–15:30` (the first ~10 min is skipped so VWAP + an impulse leg can form):

| # | Gate | Rule |
|---|------|------|
| 1 | **Trend** | session VWAP **rising** over `vwap_slope_lookback` (3) bars, and `price > VWAP` now |
| 2 | **Impulse** | an earlier bar in the last `pullback_lookback` (8) bars had `high ≥ VWAP × (1 + impulse_pct)` (0.3%) |
| 3 | **Re-test** | at least one pullback bar dipped into the VWAP zone: `low ≤ VWAP × (1 + pullback_touch_band)` (0.3%) |
| 4 | **Controlled** | pullback held above VWAP: `pullback_low ≥ VWAP × (1 − reclaim_depth_pct)` (0.2%) |
| 5 | **Higher low** | `pullback_low > impulse_bar.low` |
| 6 | **Reclaim trigger** | `bar.close > pullback_high` **and** `bar.close > VWAP` |
| 7 | **Volume** | `bar.volume ≥ vol_mult × avg(prior 6 completed bars)` (`vol_mult` 1.3) |

## Levels (entry / stop / target)
```
entry   = pullback_high + entry_offset_atr_mult × ATR(atr_period,5m)   # +0.05·ATR5
structural = pullback_low − stop_atr_mult × ATR5                        # below the higher low
stop    = min(structural, entry × (1 − min_stop_pct))                   # floored to ≥0.5%
R       = entry − stop
target  = entry + target_r_mult × R                                     # target_r_mult = 2.0 → 2R
```
Rejected if `R ≤ 0`. The stop sits below the **pullback (higher) low**, so risk is defined by
the retest structure, not an arbitrary distance.

## Position sizing & management
Same engine as the others: `fixed_stocks` (1) or 1% risk-at-stop on $100k; native
stop-market + TP bracket, OCA-grouped; breakeven at `breakeven_mult` R (1.0), trail from
`trail_start_mult` R (1.5) locking `trail_lock_mult` R (0.5); EOD flatten 15:55.

## Order execution
`entry_order_type` is currently **`MKT`**. As with the other bots, set it to `LMT` for the
bounded marketable-limit chase (`max_chase_pct` 0.5%) to cap entry slippage.

## Config keys (VWAP PB block)
| Key | Value | Meaning |
|---|---|---|
| `entry_order_type` | `MKT` | true market entry (consider `LMT`) |
| `windows` | `[["09:45","11:30"],["14:00","15:30"]]` | two windows; skip the first ~10 min |
| `vwap_slope_lookback` | `3` | bars used to confirm VWAP is rising |
| `impulse_pct` | `0.003` | how far above VWAP the impulse must reach |
| `pullback_lookback` | `8` | window to find the impulse/pullback |
| `pullback_touch_band` | `0.003` | how close to VWAP the retest must dip |
| `reclaim_depth_pct` | `0.002` | max allowed dip below VWAP during the pullback |
| `vol_mult` | `1.3` | reclaim-bar volume confirmation |
| `atr_period` | `14` | ATR for entry/stop |
| `entry_offset_atr_mult` / `stop_atr_mult` | `0.05` / `0.5` | entry buffer / stop distance |
| `target_r_mult` | `2.0` | 2R target |
| `max_chase_pct` / `entry_timeout_sec` | `0.005` / `30` | LMT chase (if enabled) |

## Known failure modes
- **Chop below/around VWAP** produces failed reclaims that tag the stop — the dominant risk,
  and the backtest was **net negative** (see performance doc).
- **Parameter sensitivity** — impulse/touch/reclaim bands are tight; small changes materially
  change the trade count.
- **Delayed data** breaks the intraday VWAP timing; run on live data.
