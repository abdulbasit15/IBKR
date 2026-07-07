# SESSION HANDOFF — Intraday Equity Bots (IBKR / ib_async)

Continuity doc for the next session. Project lives at:
`IBKR/TWS API/source/pythonclient/Trading Strategies/Intraday Equity/`

## 1. What this is
Three **long-only, intraday-only** IBKR equity bots on **ib_async 2.1.0** (API 10.45.1),
config-driven by `equity.json`, defaulting to **paper account DU672616**, **IB Gateway port 4002**.
Entry point: `runner.py` (one thread per strategy, own clientId 30/31/32; bootstrap clientId 120).

## 2. Strategies (3) + shared engine
- **ORB Stocks-in-Play** (`strategies/orb_stocks_in_play.py`) — 09:30–09:35 opening range; long on 1-min close above OR-high; stop OR-low (or mid on narrow range); target +2× range.
- **NR7 Compression** (`strategies/nr7_compression.py`) — prior day = narrowest range of 7 + ADR%>5 + close>20-SMA; long on 5-min close above OR-high; stop max(OR_low−0.5·ATR5, VWAP−buf); target +2.2R.
- **PDH Breakout** (`strategies/pdh_breakout.py`) — long on 5-min close above prior-day high; stop-limit child; target +2R.
- **`equity_base.py`** `EquityStrategyBase`: per-thread event loop, ET-aware windows, 1%-risk-at-stop sizing w/ min-stop floor (or `fixed_stocks`), RVOL, VWAP (tick 233), ATR/ADR, regime gate, native bracket placement, breakeven+trail, EOD flatten (every tick), reconnect handling, **scanner**, journaling.
- Support files: `equity_order.py` (bracket/limit-only entry/flatten), `portfolio_risk.py` (per-strategy risk book + SymbolLock), `market_data.py` (rate limiter, day cache, vol-scale), `calendar_util.py` (ET + holidays/half-days), `reporting.py` (Excel report), `runner.py`.

## 3. Scanner (IBKR native) — WORKING
- `scan()` + `scanner_universe()` in `equity_base.py`; each `build_watchlist()` seeds from `scanner_universe()` then applies the strategy's own gap/RVOL/ADV/NR7/PDH filters.
- **CRITICAL LESSON:** use the **built-in** `ScannerSubscription` fields (`abovePrice`/`belowPrice`/`aboveVolume`) — they work **without** market-data entitlement. **TagValue generic filters** (`changePercAbove`, `avgVolumeAbove`, …) **require entitlement → error 162**. So `tag_filters` is left `{}`.
- Per strategy: ORB = `TOP_PERC_GAIN ∩ HOT_BY_VOLUME` (intersect); PDH = `TOP_PERC_GAIN`; NR7 = scanner **off** (NR7 is multi-day, no scanCode can express it → keeps computed fixed `universe_symbols`).
- `fallback_to_universe: true` → if a scan errors/empties, uses `universe_symbols`.
- **Benign noise:** `Error 162 ... scanner subscription cancelled` appears even on SUCCESS (one-shot snapshot teardown). Success signal = log line `scanner universe (N): [...]` populated. Failure = `scanner returned nothing -> using universe_symbols`.

## 4. DATA ENTITLEMENT — the key operational fact
Paper account DU672616 has **no live market-data subscription**.
- `market_data_type: 3` (**delayed**) → historical bars + quotes + VWAP all **WORK** (proven). **Current setting.**
- `market_data_type: 1` (live) → ticker fields are **NaN** → `require_vwap:true` silently blocks **every** entry. (This caused an earlier "scanned but never traded" run.)
- **To use real-time (type 1):** share the live account's market-data subscription to the paper account — IBKR Client Portal (LIVE login) → Settings → Account Configuration → Paper Trading Account → "Share real-time market data" = Yes → pick live username → Save (≤24h). Only one of {live, paper} logged in at a time.

## 5. Current equity.json (production, as of session end)
- `market_data_type: 3` (delayed — keep for paper; set 1 once live sub is shared)
- Windows: ORB & NR7 `09:35–11:00`; PDH `09:35–11:30` + `14:00–15:30` (windows are configurable per strategy via the `windows` array)
- `require_vwap: true` (all); `vol_mult: 1.5` (ORB/PDH)
- `fixed_stocks: 1` → **every trade is 1 share**; set to **0** for real 1%-of-`strategy_capital` risk sizing
- `strategy_capital: 100000`, max 5 tickers, 2/sector, 3% daily-loss, EOD flatten 15:55

## 6. Build / run / deploy
- **Run from source (preferred):** `python runner.py` from the folder (picks up config + all fixes).
- **Build exe:** `.\build_and_deploy.ps1` → `.venv` + PyInstaller one-file → `dist/intraday_equity.exe` (+ staged `equity.json`). Auto-falls-back PyPI → **Aliyun mirror** (pypi.org is 403-blocked on the LPL network). Flags: `-IndexUrl`, `-FallbackIndexUrl`.
- ⚠️ The exe currently in `dist/` is **STALE** (built before the scanner/window/reconnect fixes). **Rebuild before deploying.** `BUILD_AND_DEPLOY.md` is the full runbook.

## 7. Verified this session
- Scanner returns market-wide movers; watchlists build (e.g. ORB→`TECH`, PDH→`TECH,KYMR`).
- **Order/bracket path CONFIRMED:** `test_order.py AAPL` filled 1 share @ 276.50 with TP 282 + stop 273.71 live (server-side OCA).
- Why no midday auto-entry: these are **breakout** systems — entries fire on a break of the morning OR-high/PDH, mostly near the open (09:35–10:00). Run at the open for genuine signals.

## 8. OPEN ITEMS / TODO
1. **Flatten the leftover 1-share AAPL paper test position** (TP 282/stop 273.71) — still open in the Gateway, not bot-managed. (`test_order.py` placed it.)
2. Decide **`fixed_stocks` 1 → 0** (real % risk sizing) when ready.
3. **Share live market-data sub** → then `market_data_type: 1` for real-time VWAP/signals.
4. **Run at the open (~9:35 ET)** to see real strategy entries.
5. Code review **tranche-2/3 NOT yet done** (deferred, non-blocking): efficiency — `rvol()` cache-bypass (re-pulls 25d 5-min every check), shared `RateLimiter` serializes all 3 threads, `regime_ok()` refetches SPY/VIX every tick, NR7 double-pull of 5-min bars; design — ORB volume baseline reaches into opening bars, ORB target not floored for honest R:R. (Top-3 + confirmed bugs #1,2,3,4,5,6,15,17 WERE fixed this session.)
6. Diagnostic helpers in folder: `scanner_test.py` (scanner+data check), `test_order.py` (1-share bracket test), `backtest.py` (simple historical replay).

## 9. Environment constraints (LPL)
- **pypi.org blocked (403)** → install via Aliyun mirror `https://mirrors.aliyun.com/pypi/simple/`.
- Python 3.12 at `C:\Users\abdbasit\AppData\Local\Programs\Python\Python312`.
- Do not consider SOXL for this work (explicitly excluded by user).

## 10. Indicator library accuracy review (Trading Strategies/Indicators/)
Separate pure-Python indicator library (~30 indicators; each has math fns + a config-driven
`xxx_value(ib=..., symbol=..., bar_size=...)`; bundles for PyInstaller). Reviewed for
**mathematical accuracy vs standard/TradingView** across two sessions (direct + a workflow
with adversarial verify).
- **VERIFIED CORRECT (~27):** moving_average (sma/ema/wma/rma=Wilder/hma/stdev=population),
  dema, rsi, atr, adx (ADX seeded at 2*period-1), macd, stochastic (+StochRSI), bollinger,
  OBV, CMF, MFI, VWAP, Donchian, Williams Vix Fix, Parabolic SAR, Ichimoku, HalfTrend,
  Awesome Oscillator, CCI, WaveTrend, **Squeeze Momentum** (independently re-verified incl.
  linreg/LSMA momentum + the LazyBear multKC-for-BB quirk), FVG, Pivots, Support/Resistance,
  Order Blocks, Market Structure (BOS/CHoCH), ATR Trailing Stop (UT Bot), Chandelier Exit,
  ICT Killzones.
- **3 FINDINGS — fixes NOT yet applied:**
  1. **SMC confluence filter — `structure/smc.py` (~lines 334-335) — real bug, MED.**
     Operator-precedence error: `min(closes[i], opens[i] - lows[i])`. Fix: `body_top=max(c,o);
     body_bottom=min(c,o); upper_wick=high-body_top; lower_wick=body_bottom-low`. ⚠️ confirm the
     bullish/bearish inequality DIRECTION against LuxAlgo source (reviewers disagreed).
  2. **Keltner Channels — `volatility/keltner_channels.py` (lines 27,57) — MED.**
     Default `atr_length=10` should be **20** (TV ta.kc uses one length=20 for basis+range).
     Fix: `atr_length=20`. (Aside: TV smooths range with EMA not Wilder ATR — variant accepted.)
  3. **Supertrend — `trend/supertrend.py` (local `_rma`) — LOW, intentional.**
     Seeds ATR at TR[0] vs SMA-of-first-period; only first ~atr_period bars differ, converges.
     Matches the validated backtest engine — leave unless exact Pine parity needed.
- **Open:** apply fix #1 (SMC wick precedence) and #2 (Keltner default); #3 optional.
