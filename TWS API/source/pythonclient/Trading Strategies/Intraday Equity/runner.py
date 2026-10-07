"""Entry point for the intraday long-only equity bots (PyInstaller one-file target).

Loads equity.json (next to sys.executable when frozen), takes ONE start-of-day equity
snapshot + detects STK volume scale on a bootstrap connection, builds the shared
PortfolioRiskManager + rate limiter + day cache + journal, then launches one thread per
active strategy (each with its own clientId and event loop).

Run:  python runner.py            (or the frozen .exe)
TWS/IB Gateway must be running on the configured port with the API enabled.
Defaults to PAPER account DU672616.
"""
from __future__ import annotations
import argparse
import asyncio
import datetime as _dt
import json
import os
import sys
import threading
import time

from ib_async import IB


def base_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


BASE = base_dir()
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import calendar_util as cal                     # noqa: E402
from market_data import RateLimiter, DailyCache, detect_volume_scale  # noqa: E402
from portfolio_risk import PortfolioRiskManager, SymbolLock  # noqa: E402
from reporting import TradeReporter  # noqa: E402
from strategies.orb_stocks_in_play import ORBStocksInPlay  # noqa: E402
from strategies.nr7_compression import NR7Compression      # noqa: E402
from strategies.pdh_breakout import PDHBreakout            # noqa: E402
from strategies.vwap_pullback import VWAPPullback          # noqa: E402
from strategies.trend_pullback import TrendPullback        # noqa: E402
from strategies.range_breakout_retest import RangeBreakoutRetest  # noqa: E402
from strategies.sr_bounce import SRBounce                  # noqa: E402

REGISTRY = {
    "orb_stocks_in_play": ORBStocksInPlay,
    "nr7_compression": NR7Compression,
    "pdh_breakout": PDHBreakout,
    "vwap_pullback": VWAPPullback,
    "trend_pullback": TrendPullback,
    "range_breakout_retest": RangeBreakoutRetest,
    "sr_bounce": SRBounce,
}

JOURNAL_HEADERS = ["Event", "Symbol", "Sector", "Strategy", "Shares", "Entry", "Stop",
                   "Target", "RiskAtStop", "Exit", "PnL", "R_Multiple", "Result"]
_journal_lock = threading.Lock()
_log_lock = threading.Lock()


def make_logger(log_path: str):
    def log(msg: str):
        line = f"[{cal.now_et().strftime('%Y-%m-%d %H:%M:%S')} ET] {msg}"
        with _log_lock:
            print(line, flush=True)
            try:
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except OSError:
                pass
    return log


def make_journal(path: str):
    def journal(strategy: str, row: dict):
        with _journal_lock:
            try:
                import openpyxl
                if os.path.exists(path):
                    wb = openpyxl.load_workbook(path)
                else:
                    wb = openpyxl.Workbook()
                    wb.remove(wb.active)
                sheet = (strategy or "trades")[:31]
                if sheet not in wb.sheetnames:
                    ws = wb.create_sheet(sheet)
                    ws.append(["Time"] + JOURNAL_HEADERS)
                else:
                    ws = wb[sheet]
                ws.append([cal.now_et().strftime("%Y-%m-%d %H:%M:%S")] +
                          [row.get(h, "") for h in JOURNAL_HEADERS])
                wb.save(path)
            except Exception as e:  # journaling must never crash trading
                print(f"[journal error] {e}", flush=True)
    return journal


def bootstrap(cfg, log, attempts=6):
    """Main-thread bootstrap connection: NetLiquidation snapshot + volume-scale detect.

    Retries the connect fast-then-backoff (a FRESH IB() per attempt) so a Gateway that is a few
    seconds from ready — or a briefly-in-use clientId — doesn't force a full session restart. If
    it still can't connect after `attempts`, returns equity 0 and the daemon backs off and retries
    the whole session, so it keeps trying and ultimately connects once the Gateway is up."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    account = cfg.get("default_account", "")
    steady = int(cfg.get("reconnect_backoff_sec", 60))
    equity, scale = 0.0, 1
    for attempt in range(1, attempts + 1):
        ib = IB()
        try:
            ib.connect(cfg.get("host", "127.0.0.1"), int(cfg.get("port", 7497)),
                       clientId=int(cfg.get("client_id_base", 30)) + 90, account=account)
            try:
                ib.reqMarketDataType(int(cfg.get("market_data_type", 1)))
            except Exception:
                pass
            for v in ib.accountValues(account):
                if v.tag == "NetLiquidation" and (not v.currency or v.currency == "USD"):
                    equity = float(v.value)
                    break
            scale = detect_volume_scale(ib)
            log(f"bootstrap: NetLiquidation={equity} volume_scale={scale}")
            return equity, scale
        except Exception as e:
            wait = 5 if attempt <= 3 else steady   # quick retries first, then ~every minute
            log(f"bootstrap attempt {attempt}/{attempts} failed ({e}); "
                f"retrying in {wait}s (is IB Gateway up and logged in on the configured port?)")
            time.sleep(wait)
        finally:
            try:
                ib.disconnect()
            except Exception:
                pass
    log("bootstrap: could not connect after retries; will retry the whole session shortly.")
    return equity, scale


def _interruptible_sleep(total: float) -> None:
    """Sleep in short chunks so Ctrl+C stays responsive during long dormant waits."""
    end = time.time() + total
    while True:
        remaining = end - time.time()
        if remaining <= 0:
            return
        time.sleep(min(2.0, remaining))


def earliest_window_start(cfg: dict, active: list[str]) -> str:
    """Earliest trade-window start ('HH:MM') across all active strategies (back-compat with
    the single trade_start_time/entry_start keys). Defaults to 09:35."""
    starts = []
    for name in active:
        b = cfg.get("strategies", {}).get(name, {})
        wins = b.get("windows")
        if wins:
            for w in wins:
                try:
                    starts.append(str(w[0]))
                except (IndexError, TypeError):
                    pass
        else:
            starts.append(str(b.get("trade_start_time", b.get("entry_start", "09:35"))))
    return min(starts) if starts else "09:35"


def wait_for_session(cfg: dict, active: list[str], eod: str, dlog, lead_min: int,
                     poll_sec: int) -> None:
    """Block (DORMANT, no broker connection) until it is a trading day and we are inside the
    'pre-open lead -> EOD flatten' span, then return so the caller can launch the bots. Stays
    idle across weekends/holidays, before the pre-open lead, and after the day's EOD flatten.
    Logs on every state change and a heartbeat roughly every 30 minutes so it's visibly alive."""
    start_hhmm = earliest_window_start(cfg, active)
    last_state = None
    while True:
        now = cal.now_et()
        if not cal.is_trading_day(now):
            state, why = "holiday", "not a trading day (weekend/holiday)"
        else:
            flat = cal.effective_flatten_time(eod, now)
            begin = cal.at_et(start_hhmm, now) - _dt.timedelta(minutes=lead_min)
            if now >= flat:
                state, why = "post_eod", "trading day, session finished for today"
            elif now < begin:
                state, why = "pre_open", (f"trading day, before pre-open lead "
                                          f"({start_hhmm} minus {lead_min}m)")
            else:
                if last_state is not None:
                    dlog(f"waking up — entering the session for {now:%Y-%m-%d}")
                return
        if state != last_state or now.minute % 30 == 0:
            dlog(f"dormant — {why}; idling with no connection. now={now:%Y-%m-%d %H:%M ET}")
            last_state = state
        _interruptible_sleep(poll_sec)


def run_one_session(cfg: dict, active: list[str], base_id: int, overrides: tuple,
                    log_dir: str, dlog) -> str:
    """Bootstrap equity + volume scale, launch one thread per active strategy, and block until
    they all finish (each strategy self-flattens at EOD and exits). Returns a status string:
    'ok' on a completed session, 'no_equity' if the bootstrap snapshot failed (caller should
    back off and retry)."""
    stamp = cal.now_et().strftime("%Y%m%d")
    log = make_logger(os.path.join(log_dir, f"equity_{stamp}.log"))
    journal = make_journal(os.path.join(BASE, f"equity_journal_{stamp}.xlsx"))

    equity, vol_scale = bootstrap(cfg, log)
    if equity <= 0:
        log("No equity snapshot (check TWS connection / account); will retry shortly.")
        return "no_equity"

    shared_risk = cfg.get("shared_risk", {})
    reports_dir = os.path.join(BASE, "reports")
    os.makedirs(reports_dir, exist_ok=True)
    shared = {
        "host": cfg.get("host", "127.0.0.1"),
        "port": int(cfg.get("port", 7497)),
        "default_account": cfg.get("default_account"),
        "market_data_type": int(cfg.get("market_data_type", 1)),  # 1=live 2=frozen 3=delayed 4=delayed-frozen
        "reconnect_backoff_sec": int(cfg.get("reconnect_backoff_sec", 60)),  # steady reconnect interval
        "shared_risk": shared_risk,
        "sector_map": cfg.get("sector_map", {}),
        "rate_limiter": RateLimiter(min_interval=float(cfg.get("hist_min_interval_sec", 2.0))),
        "cache": DailyCache(os.path.join(BASE, f"cache_{stamp}.json"), stamp),
        "vol_scale": vol_scale,
        "start_equity": equity,
        "journal": journal,
        "dry_run": bool(cfg.get("dry_run", False)),       # log orders, transmit nothing
        "capital_scale": float(cfg.get("capital_scale", 1.0)) or 1.0,  # global sizing multiplier
    }
    symbol_lock = SymbolLock()   # cross-strategy: never two strategies long the same symbol

    threads, managers = [], {}
    for i, name in enumerate(active):
        block = cfg.get("strategies", {}).get(name)
        if not block:
            log(f"active strategy '{name}' has no config block; skipping")
            continue
        cls = REGISTRY.get(block.get("strategy_type"))
        if not cls:
            log(f"unknown strategy_type for '{name}'; skipping")
            continue
        block.setdefault("client_id", base_id + i)
        safe = "".join(ch if ch.isalnum() else "_" for ch in name)
        # per-strategy daily log + persistent analytics report + own risk book
        slog = make_logger(os.path.join(log_dir, f"{safe}_{stamp}.log"))
        reporter = TradeReporter(os.path.join(reports_dir, f"report_{safe}.xlsx"), name)
        # per-strategy trades CSV in the app root (created on first close, appended thereafter)
        trade_csv = os.path.join(BASE, f"intraday_trades_{safe}.csv")
        capital = float(block.get("strategy_capital", equity))
        risk_cfg = dict(shared_risk)
        risk_cfg.update({k: block[k] for k in overrides if k in block})
        rm = PortfolioRiskManager(capital, risk_cfg, symbol_lock=symbol_lock,
                                  state_path=os.path.join(BASE, f"risk_{safe}_{stamp}.json"))
        managers[name] = rm
        inst = cls(name, block, shared, rm, slog, reporter=reporter, trade_csv=trade_csv)
        t = threading.Thread(target=inst.run, name=name, daemon=False)
        threads.append(t)
        t.start()
        mt = risk_cfg.get("max_concurrent_tickers", risk_cfg.get("max_concurrent_positions", 5))
        log(f"launched '{name}' ({block['strategy_type']}) clientId={block['client_id']} "
            f"capital={capital:,.0f} fixed_stocks={block.get('fixed_stocks', 0)} max_tickers={mt}")
        time.sleep(1.0)  # stagger connections

    for t in threads:
        t.join()
    for name, rm in managers.items():
        log(f"[{name}] final risk snapshot: {rm.snapshot()}")
    return "ok"


def resolve_config_and_mode():
    """Parse CLI and pick the config file + resolve the paper/live safety state.
      (no args)            -> equity.json           (PAPER, default)
      --live               -> equity.live.json      (live account/port; still DRY unless armed)
      --config PATH        -> explicit file         (overrides --live)
      --i-understand-live  -> ARM real-money order transmission (only matters when config live=true)
    Returns (cfg, cfg_path, live_mode, armed, dry_run, forced_dry).
    A live config that is NOT armed is forced to dry_run so it can never transmit by accident."""
    ap = argparse.ArgumentParser(description="Intraday Equity bots (PAPER by default).")
    ap.add_argument("--live", action="store_true",
                    help="load equity.live.json; still requires --i-understand-live to transmit.")
    ap.add_argument("--i-understand-live", dest="arm_live", action="store_true",
                    help="ARM real-money order transmission when the config is live.")
    ap.add_argument("--config", default=None, help="explicit config path (overrides --live).")
    a = ap.parse_args()
    if a.config:
        cfg_path = a.config if os.path.isabs(a.config) else os.path.join(BASE, a.config)
    elif a.live:
        cfg_path = os.path.join(BASE, "equity.live.json")
    else:
        cfg_path = os.path.join(BASE, "equity.json")
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    live_mode = bool(cfg.get("live", False))
    armed = bool(a.arm_live)
    forced_dry = live_mode and not armed          # live but not armed -> cannot transmit
    dry_run = bool(cfg.get("dry_run", False)) or forced_dry
    cfg["dry_run"] = dry_run                        # run_one_session reads this into `shared`
    return cfg, cfg_path, live_mode, armed, dry_run, forced_dry


def main():
    log_dir = os.path.join(BASE, "logs")
    os.makedirs(log_dir, exist_ok=True)
    # A single, non-date-stamped daemon log for the dormant/wake lifecycle (per-session
    # trading logs are still date-stamped inside run_one_session).
    dlog = make_logger(os.path.join(log_dir, "equity_daemon.log"))

    try:
        cfg, cfg_path, live_mode, armed, dry_run, forced_dry = resolve_config_and_mode()
    except FileNotFoundError as e:
        dlog(f"config file not found: {e}. Exiting."); return

    active = cfg.get("active_strategies", [])
    if not active:
        dlog("no active_strategies configured; nothing to run. Exiting.")
        return

    # ------------------------------------------------ live safety guards (fail fast)
    acct = str(cfg.get("default_account", "") or "")
    strat = cfg.get("strategies", {})
    cap_scale = float(cfg.get("capital_scale", 1.0)) or 1.0
    if live_mode:
        zero_cap = [n for n in active if float(strat.get(n, {}).get("strategy_capital", 0) or 0) <= 0]
        if zero_cap:
            dlog(f"LIVE refuses to start: strategy_capital is 0/unset for {zero_cap} — set an "
                 f"explicit capital so sizing never uses full account equity. Exiting."); return
        if not acct:
            dlog("LIVE refuses to start: no default_account set. Exiting."); return
        if acct.startswith("DU"):
            dlog(f"LIVE refuses to start: account '{acct}' looks like a PAPER account (DU...). "
                 f"Set default_account/accounts to the live U-account. Exiting."); return
    elif acct.startswith("U") and not acct.startswith("DU"):
        dlog(f"WARNING: PAPER mode but default_account '{acct}' looks like a LIVE account. "
             f"Proceeding as paper on port {cfg.get('port')} — verify this is intended.")

    base_id = int(cfg.get("client_id_base", 30))
    overrides = ("max_concurrent_tickers", "max_positions_per_sector", "daily_loss_limit_pct",
                 "aggregate_open_risk_pct", "risk_per_trade_pct")
    eod = cfg.get("shared_risk", {}).get("eod_flatten_time", cfg.get("eod_flatten_time", "15:55"))
    lead_min = int(cfg.get("preopen_lead_min", 10))    # wake this many minutes before window 1
    poll_sec = int(cfg.get("dormant_poll_sec", 60))    # how often to re-check while dormant

    # ------------------------------------------------ startup banner
    sr_rpt = cfg.get("shared_risk", {}).get("risk_per_trade_pct", 0.01)
    budget = sum(float(strat.get(n, {}).get("strategy_capital", 0) or 0) * cap_scale
                 * float(strat.get(n, {}).get("risk_per_trade_pct", sr_rpt)) for n in active)
    dlog("=" * 72)
    dlog(f"MODE={'LIVE' if live_mode else 'PAPER'}  DRY_RUN={dry_run}"
         f"{'  (forced: live not armed)' if forced_dry else ''}  config={os.path.basename(cfg_path)}")
    dlog(f"account={acct or '(default)'}  host={cfg.get('host')}  port={cfg.get('port')}  "
         f"mktDataType={cfg.get('market_data_type')}  capital_scale={cap_scale}")
    dlog(f"active={active}  risk budget/trade (1R sum) ~= ${budget:,.0f}")
    if live_mode and not dry_run:
        dlog("*** LIVE ORDER TRANSMISSION ARMED — REAL MONEY WILL BE AT RISK ***")
    elif live_mode and dry_run:
        dlog("LIVE config in DRY-RUN — connects to the live account but transmits NOTHING "
             "(pass --i-understand-live and set dry_run:false to go live for real).")
    dlog("=" * 72)

    dlog(f"daemon start — will run on trading days and stay dormant otherwise "
         f"(wake {lead_min}m before the first window, EOD {eod}). Ctrl+C to stop.")
    try:
        while True:
            # DORMANT until it's a trading day and inside the pre-open->EOD span
            wait_for_session(cfg, active, eod, dlog, lead_min, poll_sec)
            status = run_one_session(cfg, active, base_id, overrides, log_dir, dlog)
            if status == "no_equity":
                # TWS/Gateway not ready on a trading day -> back off, then wait_for_session
                # will immediately return (still in session) and we retry the bootstrap.
                _interruptible_sleep(max(60, poll_sec * 5))
            else:
                dlog("session complete; returning to dormant wait for the next trading day.")
    except KeyboardInterrupt:
        dlog("interrupted (Ctrl+C); shutting down daemon.")


if __name__ == "__main__":
    main()
