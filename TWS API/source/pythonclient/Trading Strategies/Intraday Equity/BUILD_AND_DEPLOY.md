# BUILD & DEPLOY — Intraday Equity Bots (Copilot runbook)

> Hand this file to GitHub Copilot (or any coding agent) on the target machine and say:
> *"Follow BUILD_AND_DEPLOY.md to build and deploy this app."* It is self-contained.
> (If you use GitHub Copilot repo custom-instructions, you may also copy this to
> `.github/copilot-instructions.md`.)

## 0. What this app is
Three long-only, intraday-only IBKR equity bots — **PDH Breakout**, **ORB Stocks-in-Play**,
**NR7 Compression** — built on `ib_async`. Entry point is **`runner.py`**; behavior is
driven entirely by **`equity.json`**. It connects to TWS / IB Gateway, sizes per strategy
(1% risk-at-stop or fixed shares), places native bracket orders, and writes per-strategy
daily logs + an accumulating Excel report. Defaults to a **paper** account.

## 1. Files to copy to the target machine
Copy the **entire `Intraday Equity/` folder**, which must contain:
```
runner.py              equity_base.py     equity_order.py     portfolio_risk.py
market_data.py         calendar_util.py   reporting.py        backtest.py
build_and_deploy.ps1   equity.json        requirements.txt   README.md
BUILD_AND_DEPLOY.md
strategies/__init__.py strategies/orb_stocks_in_play.py
strategies/nr7_compression.py            strategies/pdh_breakout.py
```
**Do NOT copy** (rebuild/regenerate on the target): `dist/`, `build_pi/`, `__pycache__/`,
`logs/`, `reports/`, `cache_*.json`, `risk_*.json`, `*_journal_*.xlsx`.

## 2. Prerequisites on the target machine
- **Python 3.12+** (required: `ib_async` needs 3.10+). Verify: `python --version`.
- **IB Gateway or TWS** installed, running, **logged into the trading account**, with the
  API enabled: *Configure → Settings → API → Settings → "Enable ActiveX and Socket Clients"*.
  Untick **Read-Only API** if the bots must place orders.
- Know the **socket port**: IB Gateway paper **4002** / live 4001 · TWS paper **7497** / live 7496.

## 3. Build + deploy with the script
Run from inside the `Intraday Equity/` folder on the target machine.
```powershell
.\build_and_deploy.ps1
```
This script:
- creates/uses a local `.venv` inside `Intraday Equity/`
- installs `requirements.txt`
- builds `intraday_equity.exe` into `dist/`
- copies `equity.json` into `dist/`

If local PyPI is blocked, install dependencies with a mirror first and then rerun the script.

## 4. Run from the built dist
```powershell
cd "<...>/Intraday Equity/dist"
.\intraday_equity.exe
```
- Deps: `ib_async==2.1.0`, `openpyxl`, `tzdata` (REQUIRED on Windows for the ET clock),
  `pyinstaller` (build only); `pandas` is listed but not used by these bots.
- **If pypi.org is blocked** (e.g. on the LPL network it returns HTTP 403), use the Aliyun
  mirror — on a normal/unrestricted machine plain pip works:
  ```bash
  python -m pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/
  ```

## 5. Configure `equity.json` (edit before running)
- `port` → match the Gateway/TWS socket (e.g. **4002** for paper Gateway).
- `default_account` / `accounts` → the target account (paper `DU…`, live `U…`).
- `active_strategies` → which of the three to run.
- Per strategy: `strategy_capital` (e.g. 100000), `risk_per_trade_pct` (0.01),
  `fixed_stocks` (0 = use 1% risk sizing; >0 = fixed shares/ticker),
  `max_concurrent_tickers` (e.g. 5), `universe_symbols`, and windows.
- `require_vwap` → `true` for live/real-time data; set **`false`** only for a delayed-data
  paper smoke test (VWAP tick 233 doesn't populate on delayed feeds — see §8).

## 5. Run from source (recommended FIRST — easiest to verify)
```bash
cd "<...>/Intraday Equity"
python runner.py
```
Expected startup log (proves success):
```
bootstrap: NetLiquidation=<number> volume_scale=1
launched 'ORB SIP - 9.35' (...) clientId=30 ... ✓ connected <account>
launched 'NR7 - 9.35' ...                       ✓ connected <account>
launched 'PDH - 9.35' ...                       ✓ connected <account>
```
It runs until **15:55 ET** auto-flatten (earlier on half-days); stop early with Ctrl-C.
Outputs: `logs/<Strategy>_<YYYYMMDD>.log`, `reports/report_<Strategy>.xlsx`.

## 6. Build the one-file EXE (PyInstaller)
Run from inside the `Intraday Equity/` folder. **This exact command was verified working:**
```bash
pyinstaller --onefile --name intraday_equity --collect-all ib_async --copy-metadata ib_async --copy-metadata aeventkit --collect-all tzdata --collect-all openpyxl --distpath ./dist --workpath ./build_pi --specpath ./build_pi runner.py
```
The metadata/collect flags are mandatory: `ib_async`+`aeventkit` need their package
metadata, `tzdata` provides the ET timezone, `openpyxl` writes logs/reports. Output:
`dist/intraday_equity.exe` (~30 MB).

The build includes the local helper files under `Intraday Equity/`, including:
`market_data.py`, `calendar_util.py`, `portfolio_risk.py`, `reporting.py`, and the
`strategies/` package.

> PowerShell note: the command is given on one line on purpose (avoids continuation
> issues). To split it in PowerShell, end each line with a backtick `` ` ``.

## 7. Deploy & run the EXE
```bash
cp equity.json ./dist/equity.json     # config MUST sit next to the exe
cd ./dist
./intraday_equity.exe                  # Windows: intraday_equity.exe
```
The frozen exe resolves all paths from its own location, so it writes
`dist/logs/`, `dist/reports/`, `dist/cache_*.json`, `dist/risk_*.json` next to itself.
To deploy elsewhere, copy **`intraday_equity.exe` + `equity.json`** into any folder and run.

## 8. IBKR data entitlement (critical — or the bots get no data)
`reqHistoricalData` and VWAP need a **Level-1 US-stock market-data subscription**.
- A **paper account has none of its own** — share the live account's: Client Portal (LIVE
  login) → *Settings → Account Configuration → Paper Trading Account* → **"Share real-time
  market data with paper account" = Yes** → pick the live username → Save (**takes up to 24h**).
- Only ONE of {live, paper} logins can be active at a time when sharing.
- **Red `OFF: usfarm` / `OFF: ushmds` in the Gateway is normal** (idle codes 2107/2108) —
  the farms wake on the first request. It is NOT the problem; missing entitlement is.
- **Free delayed fallback** (plumbing test only, not edge): set `require_vwap: false` AND
  request delayed data (add `self.ib.reqMarketDataType(3)` after connect in
  `equity_base.py`). Delayed `reqHistoricalData` is not guaranteed and may still fail.

## 9. Verify the deployment
1. Gateway/TWS running, API enabled, port matches `equity.json`.
2. Startup log shows `bootstrap: NetLiquidation=<n>` and all active strategies `connected`.
3. `logs/` and `reports/` get created; `report_<Strategy>.xlsx` has Trades/Daily/ByTicker/Summary sheets.
4. (During market hours, with data entitlement) bracket orders appear in the Gateway.

## 10. Troubleshooting
| Symptom | Cause / fix |
|---|---|
| `CONNECT FAILED` / no NetLiquidation | Wrong `port`, API not enabled, or Gateway not logged in. Match port (4002 paper Gateway). |
| `client id already in use` | A prior run still holds clientId 30/31/32/120. Close stray `intraday_equity.exe`/python, or change `client_id_base`. |
| `reqHistoricalData: Timeout` / 162 / 354 | No market-data entitlement on the account — see §8. |
| Scanning but **zero trades** | `require_vwap: true` on delayed/no data → VWAP gate blocks. Get the subscription, or set `require_vwap: false` for a smoke test. |
| Frozen exe crashes on launch | Rebuild with the §6 metadata flags (esp. `--copy-metadata ib_async`, `--collect-all tzdata`). |
| `ZoneInfoNotFoundError` | `tzdata` not installed/bundled — `pip install tzdata` and rebuild with `--collect-all tzdata`. |

## 11. Quick checklist
- [ ] Python 3.12+ · [ ] `pip install -r requirements.txt` · [ ] Gateway/TWS running + API on
- [ ] `equity.json`: port, account, active_strategies, require_vwap set
- [ ] `python runner.py` connects + launches all strategies
- [ ] (optional) build exe (§6) → copy exe + equity.json → run (§7)
- [ ] market-data entitlement shared to paper (§8) for real data
