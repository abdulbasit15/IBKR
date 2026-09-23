# Local AI Trade Journal

A private, TradeZella-style trading journal that runs **entirely on your machine**.
Your Excel workbook (`ZTH Trade Tracker - AB.xlsx`) stays the source of truth; the
tool imports fills, analyzes your trades/behavior/market/news, and writes back an
HTML dashboard plus analysis sheets.

Built for futures: **MNQ, NQ, MES, ES, MYM, YM, MGC, GC, MCL, CL** (+ RTY, QM).

## What it does

1. **Auto-imports** a Tradovate order-export CSV — pairs raw fills into round-trip
   trades (with recovered TP/SL bracket prices) and appends them to your workbook
   in your existing column format. Duplicates are skipped automatically.
2. **Analyzes** performance and behavior offline: win rate, profit factor,
   expectancy, drawdown, streaks, R-multiples, and per-setup / per-instrument /
   per-hour / per-day breakdowns.
3. **Flags behavior leaks**: overtrading, revenge trades, stop overruns, winners
   cut short, inconsistent sizing, and negative-edge setups/instruments/hours.
4. **Fetches context**: daily market action per instrument (Yahoo Finance) and
   high-impact US economic events (ForexFactory calendar).
5. **Coaches** with Claude — using your existing **Claude Code login** (the
   `claude` CLI), so **no API key is required**. Produces a written review with
   an assessment, what's working, behavioral leaks, market/news notes, and your
   top 3 changes.
6. **Outputs**: a self-contained HTML dashboard (`reports/`) **and** `Analysis` +
   `AI Suggestions` sheets written back into the workbook. A timestamped backup of
   the workbook is saved to `backups/` before any write.

## Requirements

- Python 3.10+ with `pandas` and `openpyxl` (already installed).
- **No other packages needed** — everything else uses the standard library
  (this works even though PyPI is blocked on this network).
- Internet access for market/news/AI (all confirmed reachable here).
- **AI coaching uses your existing Claude Code login** via the `claude` CLI —
  **no API key needed.** (An `ANTHROPIC_API_KEY` is an optional alternative.)

## Setup

**Nothing to configure** if you're already logged into Claude Code — just run it
(see Usage). The AI backend auto-detects the `claude` CLI and uses your login.

Two AI backends are supported, chosen automatically:

1. **`claude` CLI (default, no key):** uses your Claude Code login. Make sure
   `claude` runs in your terminal (if it says "Not logged in", run `claude` and
   `/login` once). Pick the model with `JOURNAL_CLI_MODEL=sonnet` (default) or
   `=opus`.
2. **HTTP API (optional):** set `ANTHROPIC_API_KEY` in a `.env` file to use the
   Messages API instead. Force a backend with `JOURNAL_AI_BACKEND=cli|api|auto`.

See `.env.example` for all options (the `.env` file is entirely optional).

## Usage

Run from **this** folder (`Trade Journal/`):

```bash
# Import newest Tradovate CSV + full analysis + AI + dashboard + write-back:
python -m journal all --open

# Just preview what an import would add (writes nothing):
python -m journal import --dry-run

# Import a specific CSV:
python -m journal import --csv "tradovate-orders-all-....csv"

# Analyze what's already in the workbook and build the dashboard:
python -m journal report --open
```

### Useful flags

| Flag             | Effect                                                     |
| ---------------- | ---------------------------------------------------------- |
| `--open`         | Open the HTML dashboard in your browser when done          |
| `--dry-run`      | Preview an import without writing to Excel                 |
| `--no-ai`        | Skip the Claude call (no API cost)                         |
| `--no-market`    | Skip Yahoo market-context fetch                            |
| `--no-news`      | Skip the economic-calendar fetch                           |
| `--no-writeback` | Don't add analysis sheets to the workbook (dashboard only) |
| `--csv PATH`     | Use a specific Tradovate CSV                               |

## How trades are reconstructed

Tradovate exports one row per order. The importer keeps only _filled_ orders,
walks them chronologically per symbol tracking net position, and emits a
round-trip trade every time the position returns to flat. TP/SL prices are
recovered from the protective bracket orders in the trade's time window. This was
verified to reproduce your existing journal rows exactly (entry, exit, size,
stop, and target).

## Notes & limitations

- **News history**: the free ForexFactory feed only covers the _current week_, so
  trades before this week won't have calendar events (the dashboard says so).
- **Market data** uses Yahoo's continuous-future charts (`ES=F`, `NQ=F`, etc.);
  micros map to the same underlying.
- **Not investment advice.** This is a personal performance-review tool.

## Layout

```
Trade Journal/
├── journal/            # the package
├── reports/            # generated HTML dashboards
├── backups/            # automatic workbook backups
├── .env                # your API key (you create this)
└── ZTH Trade Tracker - AB.xlsx
```

## TradeZella-style Web App

`python -m journal app --open` builds a single self-contained web app
(`reports/TradeJournal.html`) — double-click to open, works offline (Chart.js
and your data are inlined; no server needed). Screens:

- **Dashboard** — Net P&L, expectancy, profit factor, win %, avg win/loss cards;
  a Zella-style radar score; cumulative + daily P&L charts; trade-time scatter;
  and a monthly P&L calendar with weekly summaries.
- **Daily Journal** — one card per day: trades, win rate, P&L, and your notes.
- **Trades** — full sortable/filterable table (by instrument, side, result,
  search) with links to your TradingView screenshots.
- **Notebook** — the Claude coaching write-up plus all your trade notes.
- **Reports** — P&L by instrument / setup / hour / day-of-week, long-vs-short,
  win-loss doughnut, and drawdown/streak stats.
- **Playbooks** — performance per setup tag.
- **Progress** — Zella score components, recovery factor, streaks, equity growth,
  and behavior flags to work on.

`python -m journal all --open` now runs import → report → app in one go.

### New: auto-tagging, calendar heatmap & trade charts

- **Setup auto-tagging** — `python -m journal tag` classifies each trade's setup
  from the 5-minute price action before entry (Breakout / Breakdown / Pullback /
  Reversal, or With-trend / Counter-trend when intraday data is thin) and writes
  the labels into the Excel **Trade Setup** column (blank cells only; backed up
  first). The web app also applies these automatically.
- **Calendar** screen — a dedicated P&L **heatmap** (cell intensity scales with
  the day's gain/loss) with month navigation and monthly totals.
- **Trade detail** — click any row in **Trades** to open a **5-minute
  candlestick chart** of that instrument around the trade, with **entry and exit
  marked** (plus stop/target price lines) and the full trade stat panel. Candle
  times are US Eastern; entry/exit are matched to the candles by time and price.

If a command can't write to the workbook, it means the file is open in Excel —
close it and re-run. The web app never needs the file closed.

### News screen (ForexFactory economic calendar)

The **News** tab shows this week's economic calendar from the free ForexFactory
feed, styled like ForexFactory itself:

- **Impact filter** — High (red 📁), Medium (orange), Low (yellow), with all/none.
- **Currency filter** — AUD/CAD/CHF/CNY/EUR/GBP/JPY/NZD/USD, defaulting to **USD**.
- Events grouped by day with time, currency, colored impact folder, forecast,
  and previous values.

**Limitation:** the free feed only covers the **current week**, so it's for
planning ahead (e.g. "Core PCE Wed 8:30 — size down / avoid"), not back-testing
past trade days. Per-day _market_ context (day direction, gap, range vs. average)
for your historical trades is still computed from Yahoo and used in the AI
coaching and setup auto-tagging.

### Historical news on the calendars

Since the free ForexFactory feed is current-week only, the **Dashboard** and
**Calendar** pages mark past trade days with major US economic events pulled from
Nasdaq's historical economic calendar and classified by name:

- **High-impact** (red dot): CPI, PCE, PPI, GDP, Payrolls, FOMC/Fed Rate, Retail
  Sales, ISM, Unemployment, Fed Chair.
- **Medium-impact** (orange dot): Jobless Claims, Fed speakers, Crude Oil
  Inventories, Housing, Consumer Sentiment, Durable Goods, ADP, etc.

Hover any calendar day to see the event times and names. The Calendar page also
lists the top events inside each cell. (The News tab still uses ForexFactory for
the upcoming week with true impact ratings.)

## Everyday workflow — adding a new Tradovate export

Whenever you export orders from Tradovate (name it anything like `Orders.csv`,
`Orders1.csv`, or the default `tradovate-orders-*.csv`), drop it in the
**Trade Journal** folder and run **one command**:

```bash
python -m journal all --open
```

This auto-detects the **newest** CSV, imports it (safely — duplicates are
skipped, so it doesn't matter if the file is a full month or just the last few
days), auto-tags setups, refreshes the analysis, and opens the dashboard.

- The CSV can overlap previous imports; only genuinely new round-trip trades are
  added. Order doesn't matter.
- To point at a specific file: `python -m journal all --csv "Orders1.csv" --open`
- To skip the AI coaching call: add `--no-ai`.
- **Close the Excel workbook first** — if it's open, the import can't write to it.

## One-click update & command reference

- **`update.bat`** — double-click it (no terminal needed). It imports the newest
  CSV in the folder, refreshes everything, and opens the dashboard. Close the
  Excel workbook first.
- **`COMMANDS.txt`** — a plain-text cheat sheet of every command and flag.
