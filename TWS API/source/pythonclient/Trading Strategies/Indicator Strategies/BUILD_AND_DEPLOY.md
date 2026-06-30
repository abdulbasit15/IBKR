# BUILD & DEPLOY — Supertrend Indicator Bot (runbook)

> Hand this file to any coding agent on the target machine and say:
> *"Follow BUILD_AND_DEPLOY.md to build and deploy this app."* It is self-contained.

## 0. What this app is
A single, **config-driven Supertrend bot** on `ib_async`. Entry point is
**`supertrend_bot.py`**; behavior is driven entirely by **`supertrend.json`**. It connects
to TWS / IB Gateway, computes the Supertrend on the configured timeframe for each symbol,
and trades the configured **direction**:
- `long_only` — long when bullish, cash when bearish, never short (e.g. buy & hold SOXL,
  sell when bearish, re-buy when bullish);
- `short_only` — short when bearish, cash when bullish, never long;
- `long_short` — always in the market, flips long/short on each Supertrend flip.

It sizes per trade (1% risk-at-stop or fixed shares), attaches a **server-side protective
stop at the Supertrend line**, trails it, exits/reverses on the flip, and writes a daily log
+ a `supertrend_trades.csv`. Defaults to a **paper** account.

## 1. Files to copy to the target machine
Copy the **entire `Indicator Strategies/` folder**, which must contain:
```
supertrend_bot.py     supertrend.json     requirements.txt
build_and_deploy.ps1  BUILD_AND_DEPLOY.md README.md
```
**Do NOT copy** (rebuild/regenerate on the target): `dist/`, `build_pi/`, `.venv/`,
`__pycache__/`, `logs/`, `supertrend_trades.csv`.

## 2. Prerequisites on the target machine
- **Python 3.12+** (`ib_async` needs 3.10+; this project standardizes on 3.12). Verify:
  `python --version`.
- **IB Gateway or TWS** installed, running, **logged into the trading account**, with the
  API enabled: *Configure → Settings → API → Settings → "Enable ActiveX and Socket Clients"*.
  Untick **Read-Only API** so the bot can place orders.
- Know the **socket port**: IB Gateway paper **4002** / live 4001 · TWS paper **7497** / live 7496.

## 3. Configure `supertrend.json` (edit before running)
| Key | Set to |
|---|---|
| `port` | Match the Gateway/TWS socket (**4002** for paper Gateway). |
| `account` | The target account (paper `DU…`, live `U…`). |
| `client_id` | A free clientId (default **40**; the Intraday Equity bots use 30/31/32, bootstrap 120 — keep this distinct). |
| `market_data_type` | **3** (delayed) for paper without a live sub — historical bars still work. **1** (live) once a market-data sub is shared to the account. |
| `direction` | `long_only` / `short_only` / `long_short`. |
| `symbols` | Any US equities, e.g. `["AAPL","NVDA","AMD"]`. |
| `bar_size` | `"5 mins"`, `"15 mins"`, `"30 mins"`, `"1 hour"`, `"1 day"`, … |
| `supertrend.atr_period` / `.multiplier` | e.g. `10` / `3.0` = ST(10,3). |
| `intraday_mode` | `false` = swing (hold overnight, GTC stop); `true` = flatten at `eod_flatten_time` (DAY stop). |
| `sizing.fixed_stocks` | `>0` = fixed shares/symbol; `0` = 1%-risk-at-stop sizing. |

See `README.md` for the full config reference.

## 4. Build + deploy with the script (recommended)
Run from inside the `Indicator Strategies/` folder on the target machine.
```powershell
.\build_and_deploy.ps1
```
This script:
- creates/uses a local `.venv` inside `Indicator Strategies/`;
- installs `requirements.txt` — **auto-handles blocked PyPI**: tries the default index
  (pypi.org) first, then automatically falls back to the **Aliyun mirror**, so the *same*
  script works on open networks and on the LPL network where pypi.org returns HTTP 403;
- builds `supertrend_bot.exe` into `dist/`;
- copies `supertrend.json` into `dist/`.

Optional overrides:
```powershell
.\build_and_deploy.ps1                                                   # auto: PyPI -> Aliyun fallback
.\build_and_deploy.ps1 -IndexUrl https://mirrors.aliyun.com/pypi/simple/ # force one specific mirror
.\build_and_deploy.ps1 -FallbackIndexUrl ''                              # disable the auto fallback
```
If PowerShell blocks the script: `powershell -ExecutionPolicy Bypass -File .\build_and_deploy.ps1`.

## 5. Run the built exe (from dist)
```powershell
cd "<...>/Indicator Strategies/dist"
.\supertrend_bot.exe                       # uses supertrend.json next to the exe
.\supertrend_bot.exe my_other_config.json  # or pass another config file
```
Bundled deps (into the exe at build time): `ib_async==2.1.0`, `tzdata` (REQUIRED on Windows
for the ET clock), `pyinstaller` (build only). The frozen exe resolves all paths from its
own location, so it writes `dist/logs/` and `dist/supertrend_trades.csv` next to itself.

## 6. Run from source (alternative — easiest to verify)
```bash
cd "<...>/Indicator Strategies"
python supertrend_bot.py
# or reuse the sibling venv that already has ib_async:
# "../Intraday Equity/.venv/Scripts/python.exe" supertrend_bot.py
```
Expected startup log (proves success):
```
connected clientId=40 account=DU672616 port=4002 mktDataType=3
direction=long_only symbols=['AAPL', 'NVDA', ...] bar=15 mins ST(10,3) mode=SWING sizing=fixed 1
```
Then per poll it evaluates each symbol; on a signal it logs `OPENED …` / `CLOSED …` /
`trail … stop`. Stop with Ctrl-C. In `intraday_mode` it auto-flattens at `eod_flatten_time`.
Outputs: `logs/supertrend_<YYYYMMDD>.log`, `supertrend_trades.csv`.

## 7. Manual one-file build (PyInstaller) — reference
`build_and_deploy.ps1` (§4) runs this for you; the raw command is here for reference/debug.
Run from inside the `Indicator Strategies/` folder:
```bash
pyinstaller --onefile --name supertrend_bot --collect-all ib_async --copy-metadata ib_async --copy-metadata aeventkit --collect-all tzdata --distpath ./dist --workpath ./build_pi --specpath ./build_pi supertrend_bot.py
```
The metadata/collect flags are mandatory: `ib_async`+`aeventkit` need their package
metadata; `tzdata` provides the ET timezone. (No `openpyxl` — this bot logs trades to CSV,
not Excel.) Output: `dist/supertrend_bot.exe` (~30 MB).

> PowerShell note: the command is given on one line on purpose (avoids continuation
> issues). To split it in PowerShell, end each line with a backtick `` ` ``.

## 8. Deploy the exe to another folder/machine
```bash
cp supertrend.json ./dist/supertrend.json   # config MUST sit next to the exe
cd ./dist
./supertrend_bot.exe                          # Windows: supertrend_bot.exe
```
To deploy elsewhere, copy **`supertrend_bot.exe` + `supertrend.json`** into any folder and run.

## 9. IBKR data entitlement
The bot's signals are computed from **`reqHistoricalData`** bars (not live ticks) and there
is **no VWAP/quote gate**, so it works on **delayed** data:
- Paper accounts have no live sub of their own → keep **`market_data_type: 3`**. Historical
  bars on delayed data are sufficient for Supertrend.
- For real-time bars, share the live account's market-data sub: Client Portal (LIVE login)
  → *Settings → Account Configuration → Paper Trading Account* → **"Share real-time market
  data with paper account" = Yes** → pick the live username → Save (**up to 24h**). Then set
  `market_data_type: 1`. Only one of {live, paper} logins active at a time when sharing.
- **Red `OFF: usfarm` / `OFF: ushmds` in the Gateway is normal** (idle codes 2107/2108) —
  the farms wake on the first request.
- `short_only` / `long_short` additionally require **shortable/borrowable shares + margin**
  on the account.

## 10. Verify the deployment
1. Gateway/TWS running, API enabled, port matches `supertrend.json`.
2. Startup log shows `connected clientId=40 …` and the `direction=… ST(…)` line.
3. `logs/supertrend_<date>.log` is created; no repeated `hist error …`.
4. On a Supertrend signal during your `entry_window`, the entry + a **server-side stop**
   appear in the Gateway immediately (no unprotected position); the stop **trails** toward
   the line; a flip cancels the stop and flattens; a row lands in `supertrend_trades.csv`.

## 11. Troubleshooting
| Symptom | Cause / fix |
|---|---|
| `CONNECT FAILED` | Wrong `port`, API not enabled, or Gateway not logged in. Match port (4002 paper Gateway). |
| `client id already in use` | Another client holds clientId 40 (or 30/31/32/120 from the other bots). Close stray processes or change `client_id`. |
| `hist error … 162 / 354 / Timeout` | No market-data entitlement / farm not up — see §9. On delayed (`market_data_type: 3`) historical bars should still return. |
| Connects but never trades | Outside `entry_window`; or the Supertrend isn't in the side your `direction` trades yet; or `bar_size` too slow to have flipped. Watch the per-symbol state in the log. |
| `No matching distribution` / pip 403 on build | pypi.org blocked. `build_and_deploy.ps1` auto-falls-back to Aliyun; for a manual install add `-i https://mirrors.aliyun.com/pypi/simple/`. |
| Frozen exe crashes on launch | Rebuild with the §7 metadata flags (esp. `--copy-metadata ib_async`, `--collect-all tzdata`). |
| `ZoneInfoNotFoundError` | `tzdata` not installed/bundled — `pip install tzdata` and rebuild with `--collect-all tzdata`. |
| `… cannot short` / order rejected (short modes) | Shares not shortable/borrowable, or account lacks margin — see §9. |
| Script won't run (`… is not digitally signed`) | `powershell -ExecutionPolicy Bypass -File .\build_and_deploy.ps1`. |

## 12. Quick checklist
- [ ] Python 3.12+ · [ ] Gateway/TWS running + API on · [ ] `supertrend.json`: port, account, client_id, direction, symbols, bar_size, ST params
- [ ] Build + deploy: `.\build_and_deploy.ps1` (§4) → `supertrend_bot.exe` + `supertrend.json` in `dist/`
- [ ] Run: `dist\supertrend_bot.exe` (§5) — or `python supertrend_bot.py` from source (§6)
- [ ] `market_data_type` correct for the account (§9); short modes need borrowable shares
