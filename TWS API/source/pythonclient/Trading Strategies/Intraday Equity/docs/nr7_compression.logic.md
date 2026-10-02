# NR7 Compression Breakout — Strategy Logic

> Source: [`strategies/nr7_compression.py`](../strategies/nr7_compression.py) · engine: [`equity_base.py`](../equity_base.py) · config block: `"NR7 - 9.35"` in [`equity.json`](../equity.json)

## Edge thesis
**Volatility compression precedes expansion.** When yesterday's daily range is the narrowest of the last 7 sessions (an "NR7") *and* the name is a liquid, above-trend mover (ADR% > 5, close > 20-day SMA), a break of the opening range the next morning can release a directional move. Combines a **multi-day daily-bar filter** (the compression setup) with an **intraday ORB trigger**.

## Universe & watchlist (multi-day, daily bars)
The scanner is **off** for NR7 — no `scanCode` can express a multi-day compression pattern, so it screens the fixed `universe_symbols` (liquid ETFs/large-caps) each morning in `build_watchlist()`:

1. **Price band** — most-recent completed close within `price_min`/`price_max` (15–150).
2. **NR7** — `(ref.high − ref.low)` is the **minimum** range of the last `nr7_lookback` (7) sessions.
3. **ADR%** — average daily range over `adr_lookback` (20) ≥ `adr_min_pct` (5.0).
4. **Trend** — `ref.close > SMA(sma_period=20)`.
5. **Liquidity** — 20-day average share volume ≥ `adv_min_shares` (1,000,000).

Survivors are persisted to the day cache as the NR7 watchlist.

## Opening range
Same 09:30–09:35 5-min OR bar as ORB (`ORB_high`, `ORB_low`, `height`), accepted only when `orb_height_min_pct ≤ height/high ≤ orb_height_max_pct` (0.3%–5%).

## Entry conditions (all must hold)
On the **last completed 5-min bar** (`bars5[-2]`), at a new-bar-open boundary:

| # | Gate | Rule |
|---|------|------|
| 1 | Trade window | ET now inside `09:35–11:00` |
| 2 | Breakout | `bar.close > ORB_high` (5-min close) |
| 3 | RVOL | intraday RVOL ≥ `rvol_min` (1.5); missing history + `require_rvol:true` ⇒ skip |
| 4 | VWAP | session VWAP from bars; `price > VWAP` |

## Levels (entry / stop / target) — ATR + VWAP hybrid
```
entry     = ORB_high + entry_offset_atr_mult × ATR(atr_period,5m)   # +0.05·ATR5
stop_atr  = ORB_low − stop_atr_mult × ATR5                          # 0.5·ATR5 below OR-low
stop_vwap = VWAP × (1 − vwap_stop_buffer_pct)                       # just under VWAP (0.1%)
structural= max(stop_atr, stop_vwap)                                # higher = tighter/more conservative
stop      = min(structural, entry × (1 − min_stop_pct))             # floored to ≥0.5%
target    = entry + target_r_mult × (entry − stop)                  # 2.2R
```
Using the **more conservative** of the ATR-based and VWAP-based stops keeps the risk tight; flooring to `min_stop_pct` keeps the printed R:R honest. Rejected if `R ≤ 0` or R:R `< min_rr` (1.5).

## Position sizing & management
Identical engine to the others: `fixed_stocks` (1) or 1% risk-at-stop on $100k; native stop-market + TP bracket; breakeven at 1.0R; trail from 1.5R locking 0.5R; EOD flatten 15:55.

## Order execution
`entry_order_type` is currently **`MKT`**. Set to `LMT` for the bounded marketable-limit chase (rest at `entry`, step to `entry × (1 + max_chase_pct)`), same as PDH now uses.

## Config keys (NR7 block)
| Key | Value | Meaning |
|---|---|---|
| `entry_order_type` | `MKT` | true market entry (consider `LMT`) |
| `windows` | `[["09:35","11:00"]]` | single morning window |
| `price_min` / `price_max` | `15` / `150` | price band |
| `nr7_lookback` | `7` | NR7 compression window |
| `adr_min_pct` | `5.0` | minimum average daily range % |
| `sma_period` | `20` | trend filter |
| `adv_min_shares` | `1,000,000` | liquidity floor |
| `atr_period` | `14` | ATR for entry/stop |
| `entry_offset_atr_mult` | `0.05` | entry buffer above OR-high |
| `stop_atr_mult` | `0.5` | ATR component of the stop |
| `vwap_stop_buffer_pct` | `0.001` | VWAP component of the stop |
| `target_r_mult` | `2.2` | target multiple of R |
| `rvol_min` | `1.5` | intraday RVOL gate |

## Known failure modes
- **Very low trade count.** The stacked daily filters (NR7 ∧ ADR>5 ∧ close>SMA20 ∧ liquidity) rarely all fire on a small fixed universe, so signals are scarce — the backtest produced only a handful of trades, far too few to claim an edge (see performance doc). Broaden `universe_symbols` (or enable a `MOST_ACTIVE_USD` scanner seed) to get a testable sample.
- **Compression can resolve *down*** — this is long-only, so downside breaks are simply missed, and an upside break that fails tags the stop.
- **Delayed data** breaks intraday timing; run live.
