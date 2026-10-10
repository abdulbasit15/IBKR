# Scalping v2 intraday bot (NQ / ES / GC full-size)

Automates the four **2:1 reward-to-risk** strategies that survived the RTH time-window study
(`scalping-v1/Windows_Report.md`). Intraday only, **RTH 09:30–16:00 ET**, 5-minute bars,
**flat by 16:00**. Paper by default.

## Files
| File | Purpose |
|---|---|
| `scalping_v2_bot.py` | The bot: IB connection, contract roll, data, signals, bracket orders, exits, logging, CSVs. |
| `scalping_v2_core.py` | Shared engine: indicators, the 4 strategies, window wrapper, simulator, live replay. Used by the bot **and** the backtest. |
| `scalping_v2.json` / `scalping_v2_live.json` | Paper / live config. Every key is documented in `configuration.html`. |
| `scalping_v2_backtest.py` (+ `scalping_v2_report.py`) | Backtests the config exactly as the bot trades it. `--html` rebuilds `backtest_results.html`. |
| `scalping_v2_parity_test.py` | Proves the live decision path equals the backtest (617/617 trades). |
| `scalping_v2_sim_test.py` | Runs the real bot code against a fake IB broker on historical bars, then compares with the backtest. |
| `scalping.ps1`, `requirements.txt` | The ONE script: builds the exe if needed and runs it supervised. Paper by default; `-Live` for live, `-Build` to rebuild, `-NoRun` to build only. |
| `scalping_v2_reports.py` | Builds `reports/eod_report_<date>.html` and `reports/performance_report.html`, using the same layout as the supertrend bot's `reports.py`. |
| Runtime outputs in `dist\` (same logic as supertrend, one strategy instance = `<account>_<symbol>_<strategy>`) | <ul><li>`logs\scalping_v2_<date>.log` (combined)</li><li>`logs\scalping_v2_<account>_<symbol>_<strategy>_<date>.log`</li><li>`scalping_v2_trades_<account>_<symbol>_<strategy>.csv` (supertrend columns `time,strategy,account,symbol,side,qty,entry,exit,stop,pnl,ret_pct,reason,hold` plus `r_mult,entry_time,trade_id,commission`; pnl in $ net of commission)</li><li>`reports\`</li><li>`scalping_v2_signals.csv`</li><li>`scalping_v2_state.json`</li></ul> |

## Strategies (config `strategies`)
| Key | Setup | Window · mode | Symbols |
|---|---|---|---|
| `ib_trend` | Initial-Balance (09:30–10:30) breakout confirmed at 11:00, daily-trend direction only. Stop at the IB midpoint. | 09:30–11:30 · hold | NQ ES GC |
| `orb2nd` | 15-min ORB that fails, then breaks the opposite side. Stop at the failed-break extreme. | 09:30–11:30 · flat at 11:30 | NQ GC |
| `h2l2_trend` | Al Brooks High-2/Low-2 pullback in trend, buy/sell-stop entry. Stop at the pullback extreme. | 09:30–11:30 · hold | NQ GC |
| `confluence_pb` | Five-factor trend confluence plus an EMA9 pullback. Stop = 1×ATR. | 13:30–16:00 · hold | NQ GC |

- **Exits:** target = 2 × risk from the actual fill. Otherwise the trade exits at the stop, or at the window end/16:00.
- **Hold vs flat:** in `hold` mode the window only limits entries and the trade can run to 16:00. In `flat` mode the trade is also closed at the window end.

## How it works
1. **Signals:** every 5 minutes (bar close + 6 s) it pulls today's RTH bars from IB and replays them through `scalping_v2_core`. That's the same code the backtest uses. If a strategy signals on the latest bar, the bot acts.
2. **Orders:** a native IB **bracket** goes in: MKT or STP entry, plus a 2R LMT target and a STP stop. Both exits are GTC, OCA'd, and attached to the entry.
3. **Target re-anchor:** once the entry fills, the target is moved to exactly 2R from the real fill price.
4. **Time exits:** at the window end (`flat` mode) or 15:59:40, it cancels that trade's exit orders and sends a MKT for **that trade's quantity only**.
5. **Recovery:** every order is tagged `orderRef=sv2|<id>|<role>`. On a restart or reconnect the bot rebuilds its trades from IB executions.

## Safety
- **Paper vs live:** `paper:true` uses port 4002, and the account must be a DU paper account. Live needs `paper:false` **and** `--i-understand-live`.
- **Dry run:** `dry_run:true` only logs; no orders are placed.
- **Full-size, so no clash with supertrend:** the bot trades NQ/ES/GC; supertrend trades MNQ/MES/MGC on the same paper account. Different contracts don't net.
- **Foreign-exposure guard:** if anything else holds a position or working orders in NQ/ES/GC on the account, the bot **blocks that symbol**.
- **YM (Dow):** in the config but disabled. All four strategies lose on the Dow in the backtest.
- **Limits:**
  - `one_position_per_symbol`
  - `max_risk_usd` per symbol
  - `max_trades_per_day`
  - `daily_loss_limit_usd` circuit breaker
- **Intraday only:** if the bot dies, the GTC stop and target stay on IB's server. At the next startup any stale trade is flattened.

## Prereqs
- **IB Gateway:** running with the API enabled. Paper uses **4002**, live uses 4001.
- **Market data:** CME + COMEX futures (you already have it; the historical bars download fine).
- **Python:** 3.12 with `ib_async` 2.1.0, `pandas`, `numpy` and `tzdata`. These are already on this machine's system Python. To build and run the exe, use `.\scalping.ps1`.

## Usage
```
python scalping_v2_bot.py --check              # validate config + engine (no network)
python scalping_v2_bot.py --status             # read-only: contracts, history, today's levels and decisions
python scalping_v2_bot.py --test-orders NQ     # paper only: far-away bracket -> verify -> cancel
python scalping_v2_bot.py                      # run (leave it running through the session)
python scalping_v2_backtest.py --html          # backtest the config, rebuild backtest_results.html
```
With the exe, everything goes through **one script**, `scalping.ps1`:
```
.\scalping.ps1                 # paper: build dist\scalping_v2_bot.exe if missing, then run supervised (auto-restart)
.\scalping.ps1 -Build          # rebuild after a code change, then run on paper
.\scalping.ps1 -Build -NoRun   # rebuild only
.\scalping.ps1 -Live           # LIVE config (asks you to type LIVE)
.\scalping.ps1 -ResetConfig    # overwrite dist\*.json with the source configs
```
- **Stopping:** close the window, or create `STOP.txt` in the folder.
- **Rebuilds keep your files:** `dist` is never wiped, so logs, CSVs, state and your edited `dist\scalping_v2.json` survive.

## Recommended rollout
1. **Read-only checks:** run `--status` on a trading day after 11:00 and compare its "trades this session" with your chart.
2. **First paper week:** run the bot every session. Check `scalping_v2_signals.csv` and the logs.
3. **Validate:** after 2–4 weeks, compare `scalping_v2_trades_*.csv` with `python scalping_v2_backtest.py` over the same dates (refresh the data CSVs first).
4. **Live:** only then run `.\scalping.ps1 -Live` (config `scalping_v2_live.json`) with 1 contract (full-size = 10× micro risk; switch the symbols to MNQ/MES/MGC for a smaller account) (`scalping_live.ps1`). Get pre-clearance on corporate accounts. Not financial advice.
