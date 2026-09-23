# ZTH Trade Journal — Handoff Document

A local, private, TradeZella-style AI trading journal for **Tradovate futures**
(MNQ/NQ, MES/ES, MYM/YM, MGC/GC, MCL/CL, RTY, QM). It imports Tradovate order
exports, reconstructs round-trip trades, computes multi-timeframe technical
indicators + a confluence/entry-quality read per trade, fetches market & news
context, and produces a self-contained HTML dashboard plus (optionally) an
AI-written coaching narrative. Everything runs locally.

Use this document to continue the project in another AI tool or a fresh session.

---

## 1. Owner & intent
- Discretionary intraday futures trader; primary instruments **MNQ** (Micro
  Nasdaq) and **MGC** (Micro Gold). Style: **Break & Retest**, trades the RTH
  morning, targets **2–2.5R**, flat between trades.
- Wants: capture every trade, tag them, see per-trade technical context, get
  data-grounded feedback, and keep it all **private/local**.

## 2. Hard environment constraints (READ FIRST)
- **Work machine is locked down: PyPI is blocked (HTTP 403).** `pip install`
  fails. The tool therefore uses ONLY: `pandas` + `openpyxl` (pre-installed) +
  the Python **standard library**. Do all HTTP via `urllib`; no requests,
  yfinance, jinja2, matplotlib, anthropic, or any pip package. Charts are
  hand-rolled SVG / inlined Chart.js.
- **On a different machine PyPI may be available** — then `pip install pandas
  openpyxl` is fine. Nothing else is needed.
- **Reachable endpoints:** api.anthropic.com, query1.finance.yahoo.com,
  nfs.faireconomy.media (ForexFactory mirror), api.nasdaq.com, stooq.com.
- **Timezone:** Tradovate export times are **US Eastern (ET)**; Yahoo epochs are
  UTC. `market.et_epoch()` uses a fixed **EDT −4** offset (valid for the summer
  dates in use; revisit for winter/EST). Entry prices are matched to Yahoo 5-min
  candles using this.
- **The Excel workbook MUST be closed** when running import/tag/serve (Windows
  file lock). If open, writes raise PermissionError and the tool prints a
  "close Excel" message.

## 3. Layout
```
Trade Journal/
  ZTH Trade Tracker - AB.xlsx      <- source of truth (data + tags)
  Orders.csv / orders*.csv         <- Tradovate export you drop in (newest auto-picked)
  update.bat  tag.bat  update-no-ai.bat
  README.md   HANDOFF.md
  ZTH_Confluence.pine              <- TradingView indicator (user maintains separately)
  backups/                         <- automatic .xlsx backups before every write
  reports/TradeJournal.html        <- generated dashboard (open in any browser)
  .cache/                          <- (unused now; was for a since-removed feature)
  journal/                         <- the Python package (run: python -m journal ...)
    __main__.py     entrypoint; catches Ctrl+C -> exit code 130 (no traceback)
    cli.py          commands: import | tag | report | app | serve | all
    config.py       paths, MULTIPLIERS, YAHOO_MAP, thresholds, load_dotenv()
    excel_io.py     read/write workbook; COL map; sheet builders; backups
    tradovate_import.py  CSV normalize + FIFO round-trip reconstruction
    market.py       Yahoo daily + intraday OHLC(V); et_epoch(); caches
    news.py         ForexFactory (current wk) + Nasdaq (historical) econ events
    indicators.py   ALL technical indicators + per-trade confluence/AI-read text
    analytics.py    metrics, by_setup/instrument/hour/tag, behavior flags
    autotag.py      default setup ("Break and Retest") + mistake detection
    tags.py         7 tag categories + DEFAULT hard/other trading rules
    ai.py           Claude backends (CLI / API) + graceful no-AI fallback
    webapp.py       build_data() + build_app() -> the HTML file
    serve.py        stdlib http.server for live tag/rule editing -> Excel
    report.py       (older) standalone HTML report
    templates/app.html   the single-page dashboard (data + Chart.js inlined)
    vendor/chart.min.js  vendored Chart.js
```

## 4. Excel workbook (the data model)
Sheets the tool reads/writes:
- **Trade Tracker - Eval** — the trades. Column map (`excel_io.COL`, 1-indexed):
  1 zth, 2 date, 3 time, 4 asset, 5 direction, 6 entry, 7 exit, 8 size, 9 stop,
  10 target, 11 rr_targeted, 12 rr_realized, 13 winloss, 14 pnl, 15 pnl_pct,
  16 cum_pnl, 17 setup, 18 notes, 19 instrument_level, 20 level_screenshot,
  21 trade_screenshot, 22 mistakes, 23 rules, 24 market, 25 emotion, 26 process,
  27 learning. (Tag columns are comma-separated multi-values.)
- **Multipliers** — $/point per contract (mirrors `config.MULTIPLIERS`).
- **Tag Options** — user-owned vocab per category; tool only creates if missing.
- **Trading Rules** — Type (Hard/Other) + Rule; shown on the Rules tab.
- **Analysis**, **AI Suggestions** — regenerated (metrics + Claude coaching).
- **Economic News** — high-impact "red-folder" events (regenerated).
- **Indicators** — one row per trade with its full indicator snapshot at entry.

## 5. How to run
From the **Trade Journal/** folder (not its parent):
- `update.bat`  — import newest CSV -> tag -> report -> build+open dashboard.
- `tag.bat`     — import -> tag -> launch live tag-editing server (port 8899+).
- `update-no-ai.bat` — same as update.bat but forces AI off (fast mode).
- CLI directly: `python -m journal <import|tag|report|app|serve|all> [--open]
  [--no-ai] [--no-market] [--no-news] [--dry-run] [--csv PATH]`.
- **Ctrl+C** cleanly stops any bat (Python exits 130; bats guard with
  `if errorlevel 130 goto :aborted`, so Y or N at Windows' prompt both exit).

## 6. AI backend (Claude) — OPTIONAL
Only ONE feature calls Claude: the Notebook's **"AI Analysis & Coaching"**
narrative. Everything else (indicators, the per-trade "AI read", confluence,
backtests, dashboard) is **deterministic local Python — no Claude**.

`ai.py` picks a backend via `JOURNAL_AI_BACKEND` (default "auto"):
1. **CLI** (`claude -p --model sonnet ...`) using a Claude Code login — needs a
   Claude **Pro/Max** plan (free claude.ai tier generally can't run headless).
2. **API** — set `ANTHROPIC_API_KEY` (put it in a local `.env`; `config.load_dotenv()`
   loads it). Pay-per-use.
3. **none** — `ai.available()` is False -> the tool prints a one-line skip and
   builds everything except the coaching paragraph.

The bats do a **non-blocking** login check (no `claude auth login` prompt) and
run either way. So the tool works on any machine; on a free-plan machine it just
skips the coaching narrative.

## 7. Trade import & reconstruction (important nuances)
- `tradovate_import.normalize()` handles two CSV shapes: `Orders.csv`
  (columns B/S, Contract/Product, Fill Time, ...) and `tradovate-orders-*.csv`
  (Symbol, Side, Update Time, ...). `_latest_csv()` auto-picks the newest.
- `build_trades()` = FIFO **net-position** reconstruction per instrument root,
  sorted by fill time; recovers stop/target from the bracket orders.
- **Stale-carry guard (`_GAP_RESET_SEC = 4h`):** if a position stays open across
  a >=4h gap between fills (e.g. an unclosed overnight leftover before the RTH
  session), it is dropped so the next session reconstructs from flat. Without
  this, a carried position mislabels the next session's trades. **If import ever
  "misses" trades, first trace the running net position per instrument (buys vs
  sells) looking for imbalance/carryover before suspecting the parser.**
- Dedup key = date/time/asset/direction/entry. NOTE: if a bad reconstruction
  ever writes wrong rows, fixing the code won't delete the already-written wrong
  rows — they must be removed manually (or by a targeted delete; back up first).

## 8. Indicators & the per-trade "AI read" (indicators.py)
Computed at each trade's entry from Yahoo OHLC(V), all pure pandas:
- **Multi-timeframe (1H / 15m / 5m):** EMA-trend (close vs EMA50 & EMA21 vs
  EMA50), Supertrend(10,3), Wilder RSI(14), ADX(14), ATR(14).
- **5m detail:** EMA 9/21 cross (+ bars since cross), MACD(12/26/9) line/signal/
  histogram/momentum/cross-freshness.
- **Session (RTH-anchored from 09:30 ET):** VWAP (+distance+side), VPOC
  (price of the highest-volume 5m bar this session — simplified), RVOL (entry
  bar vs same-time-of-day median), **estimated** cumulative delta (close-location
  x volume PROXY — NOT real order-flow; always labelled "est.").
- **Fibonacci** of the last 5m impulse leg (+ 38/50/61.8/78.6 levels, retrace %,
  golden-zone flag).
- **Key levels** (`_key_levels`): prior-day H/L, overnight H/L, opening-range
  H/L (09:30–10:00), round numbers (`_ROUND_STEP`); "at level" if within ~0.5 ATR.
- **Candlestick trigger** + **trigger-bar volume** (`_entry_bar_signals`).

`analysis()` returns **categorized sections** (list of `{cat, items}`) rendered
in the popup; the categories are:
- **Confluence — N/3** (direction): **1H trend**, **5m EMA 9/21**, **VWAP side**.
  (1H/15m/5m Supertrend and 5m MACD were REMOVED from the count as redundant/
  no-edge — they still display for info elsewhere, just don't vote.)
- **Entry quality — N/3**: key level, candlestick, trigger-bar volume.
- **Pullback & Fibonacci**: pullback grade (trend+zone+trigger, 0–3) + fib.
- **🎯 The right play** (verdict): Take / Reverse / Avoid[/Avoid-chop], weighing
  all 6 confluences + pullback, gated by ADX>=20; plus likely-outcome (from the
  trader's own history) and the actual result.
`performance()` buckets win-rate/P&L by every indicator state (feeds Reports +
Claude). The rendering lives in `templates/app.html` `indHtml()`/`indAiHtml()`.

## 9. Findings from the trader's own data (as of ~79-trade sample, Aug 2026)
Directional/quality edges that separate winners from losers:
- **With the 1H trend:** +$3,334 (59%) vs against/unclear −$1,524 (47%).
- **ADX >= 25 (strong trend):** +$1,960; **ADX < 20 (chop):** −$1,540 *despite
  62% win rate* (chop wins often but loses money — the classic leak).
- **Pullback grade Good/A+ (>=2/3):** +$4,669 (69%) vs Weak/None −$2,860 (47%).
- **At a key level:** +$3,974 vs not −$2,164. **Candle-with-trade:** +$1,137 vs
  against −$639. **High trigger-bar volume:** +$2,465 vs weak −$655.
- **EMA 9/21 cross is a better ENTRY TRIGGER than MACD** for MNQ/MGC (beat MACD
  in all 8 backtest configs; ATR-based R outperformed fixed-tick R).
- Supertrend alignment adds **no** edge (aligned −$228 vs not +$2,038) — the old
  "1H/15m/5m ST must align" rule was removed accordingly.
- Behavior leaks: **overtrading** (9–12 trade days) and **oversizing/revenge**
  on evening MGC; the afternoon (12–3pm) and parts of the evening are net-negative.

**3 suggested hard rules** derived from this: (1) only trade **ADX>=20**;
(2) only **with the 1H trend**; (3) only **"Good"+ pullback entries**.

## 10. Known gotchas / caveats
- **Est. delta is a proxy**, not tick order-flow (Yahoo has no bid/ask). Labelled
  as such everywhere. Real delta would need a tick+quote feed (e.g. Tradovate
  market data) — not implemented (a Tradovate API integration was prototyped then
  removed; user has no API entitlement).
- **VPOC/RVOL are approximations** (bar-level), not a full volume profile.
- **Round-number "at level"** is the loosest level type (dominates the hits);
  PDH/PDL/ONH/ONL/OR are tracked distinctly if you want to weight structure over
  round numbers.
- **EDT −4 offset is hard-coded** — fine for summer data; will be off by 1h in
  EST (winter). Revisit `market.ET_OFFSET_HOURS` if analyzing winter trades.
- Yahoo 5m history is ~60 days max; longer backtests need another source.

## 11. TradingView companion
`ZTH_Confluence.pine` (Pine v6, run on a 5-min chart) mirrors the journal's
indicators + confluence + Buy/Sell/Hold. **The user maintains this themselves —
do not edit unless asked.** Pine gotchas learned: no `+=` operator (use `:=`);
`shorttitle` <= 10 chars; keep multi-timeframe EMAs inside `request.security`
tuples (avoid short-circuit `ta.*` warnings); avoid maps/for-loops if a simpler
form works.

## 12. Open items / possible next steps (none in progress)
- Optionally rename `update-no-ai.bat` -> `update-fast.bat` (clarity), or delete.
- Regenerate the written Notebook coaching so it reflects the current
  3-confluence + entry-quality model (older coaching predates it).
- Optionally add a rule-break auto-flag (tag trades that violated ADX/1H-trend/
  pullback rules) to track adherence over time.
- Optionally weight structural levels above round numbers in the level check.

## 13. Quick start for a new machine
1. Copy the whole `Trade Journal/` folder (incl. the .xlsx).
2. `pip install pandas openpyxl` (if PyPI is available there).
3. Drop your latest Tradovate `Orders.csv` in the folder.
4. Close the workbook in Excel.
5. Run `update.bat` (AI auto-included if a Claude backend exists, else skipped),
   or `python -m journal all --open`.
6. The dashboard opens from `reports/TradeJournal.html` (works offline, any browser).
