# Qullamaggie LONG-only IBKR bot

Automates the **long** side of Qullamaggie's breakout method. **No shorts.**
Risk **1%** per ticker, **max 10** positions. Paper + dry-run by default.

## Files
- `qm_bot.py` — the bot (entry scan + position management + scheduler)
- `qm_bot.json` — config (edit this)
- `universe.py` — full US stock universe (Nasdaq/NYSE/AMEX, cached)
- `qm_screener.py` — standalone watchlist scanner
- `qm_long_backtest.py` — long-only backtest (shared fetch/indicator code)
- `qm_bot_state.json` — live position state (auto-created)
- `logs/` — run logs (auto-created): a combined `qm_bot_<date>.log` plus one log per setup
  `qm_<setup>_<date>.log` (`breakout`/`parabolic_long`/`ep`)
- `qm_trades_<setup>.csv` — **per-setup** trade logs in the root (e.g. `qm_trades_breakout.csv`),
  appended as each leg closes (partial/BE/trail/stop), in the Backtest Journal format
  (`symbol,strat,entry_id,...,R_result,pnl`; legs share `entry_id`) so
  `python -m journal backtest` ingests the bot's live trades.

## Long setups traded (config `setups`)
- **breakout** — stock up big over ~3 months, coiled into a tight base near the
  highs, not yet broken out → BUY-STOP at the base high, stop at the base low.
- **parabolic_long** — a former parabolic that ran up then **crashed ~50%+ in a
  few days**, now basing near the low → BUY-STOP at the recent swing high (first
  range-break up), stop at the crash low. Rare by design (his premise is a stock
  down 50–60% in days). Tuned via the `pl_*` config keys.

- **ep** — Episodic Pivot: confirms an earnings catalyst (Nasdaq calendar) + a ≥10% opening
  gap in a not-already-extended name → BUY-STOP at the opening-range high (5-min intraday),
  stop at the opening-range low. Runs at the open (`ep_entry_time`), its own schedule slot.

All three are LONG. The parabolic **short** is not implemented.

## What it does
1. **Entry (once/day, ~09:40 ET):** scans the universe for the enabled `setups`.
   For the top candidates (until 10 slots are full) it places a **BUY-STOP at the
   trigger** with a protective **SELL-STOP below** (native IB bracket — a filled
   position is never unprotected).
2. **Manage (once/day, ~15:50 ET):**
   - After `partial_days` (5) held: **sell half** at market, move stop to **break-even**.
   - **Trail** the remainder on the `trail_sma` (20-day): exit on the first daily
     **close below** it.
3. Sizing: `shares = floor(capital * 1% / (trigger - stop))`, capped so no name
   exceeds `max_position_pct` (30%) of capital.

## Safety
- `paper: true` → paper gateway (port 4002). LIVE needs `paper: false` **and** the
  CLI flag `--i-understand-live`.
- `dry_run: true` → logs orders, places nothing. Set `false` to arm.
- Long-only is structural; every sell is clamped to the held quantity.
- On startup it **reconciles** with real IB positions (no double-entry / no orphans).

## Prereqs
- IB Gateway (or TWS) running, API enabled, on the configured port.
  Paper Gateway = **4002**, Live Gateway = 4001 (TWS: 7497 paper / 7496 live).
- `ib_async` (already installed, 2.1.0).

## Usage
```
python qm_bot.py --check            # validate config + imports (no network)
python qm_bot.py --scan-only        # print today's setups (no IB needed)
python qm_bot.py --once             # connect, run one entry+manage cycle
python qm_bot.py                    # scheduled loop (leave running)
```

## Recommended rollout
1. `--scan-only` for a few days — sanity-check the setups it picks.
2. Paper + `dry_run: true` `--once` — confirm sizing/slots/logs.
3. Paper + `dry_run: false` — let it actually trade paper for **weeks**.
4. Only then consider live, with pre-clearance. Not financial advice.

## Key knobs (qm_bot.json)
`risk_per_trade_pct` (0.01), `max_positions` (10), `max_position_pct` (0.30),
`min_move_pct` (30), `cons_days` (10), `max_base_range_pct` (20), `near_high_pct`
(15), `min_adr_pct` (3), `partial_days` (5), `trail_sma` (20), `min_cap_m` /
`max_cap_m` (universe size), `entry_time` / `manage_time` (ET schedule).
