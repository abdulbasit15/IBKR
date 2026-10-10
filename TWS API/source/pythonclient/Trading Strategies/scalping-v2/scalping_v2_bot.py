"""
Scalping v2 intraday bot for IBKR (ib_async) — MNQ / MES / MGC, RTH only (09:30-16:00 ET), 5-minute bars.

Trades the four 2:1 reward-to-risk strategies from the research study (see backtest_results.html):
  ib_trend       IB (09:30-10:30) breakout confirmed at 11:00, daily-trend direction, stop IB mid   [MNQ MES MGC]
  h2l2_trend     Al Brooks High-2/Low-2 pullback with trend, stop-entry, 09:30-11:30 entries        [MNQ MGC]
  orb2nd         15-min ORB second (opposite) break, 09:30-11:30, flat by 11:30                     [MNQ MGC]
  confluence_pb  5-factor trend confluence + EMA9 pullback, 13:30-16:00 entries                     [MNQ MGC]
Every trade: structural stop + target = 2R from the actual fill, otherwise flat at its window end / 16:00.

HOW SIGNALS ARE MADE (backtest parity):
  On every 5-minute bar close (+bar_delay_sec) the bot pulls today's RTH bars from IB and REPLAYS them through
  the very same engine the backtest uses (scalping_v2_core.live_decision). If the replay says "signal at the last
  completed bar" the bot acts at the next bar open — exactly what the backtest assumed. scalping_v2_parity_test.py
  proves bar-by-bar live replay == backtest trades over the full history.

ORDERS: native IB bracket — parent (MKT, or STP for h2l2 stop-entries) + take-profit LMT + stop-loss STP
  (children GTC, OCA). On the entry fill the take-profit is re-anchored to exactly 2R from the real fill.
  Window/session exits: cancel the children, then a MKT for exactly THIS trade's quantity.
  Every order carries orderRef "sv2|<trade-id>|<role>"; trade state is rebuilt from IB executions with that
  tag, so restarts/reconnects never lose track. The bot NEVER closes positions it did not open.

=================================  SAFETY  =================================
 * paper=true -> paper gateway (4002). LIVE requires paper=false AND --i-understand-live.
 * dry_run=true -> logs the orders it WOULD place, places nothing.
 * Foreign-exposure guard: if another bot/user holds a position or working orders in a contract this bot
   trades (e.g. supertrend_bot on MNQ/MES/MGC on the same account), that symbol is BLOCKED for new entries
   (positions net per account; two bots on one contract corrupt each other's accounting).
 * daily_loss_limit_usd circuit breaker, max_trades_per_day, per-symbol max_risk_usd, one position/symbol.
 * Intraday only: everything is flat by 16:00; GTC protective children keep a position protected if the
   bot dies; a stale trade found at the next startup is flattened (flatten_stale_trades).
 * PAPER-FIRST. On a corporate/LPL account get pre-clearance before live. Not financial advice.
===========================================================================

  python scalping_v2_bot.py --check                 # validate config + imports + engine self-test (no network)
  python scalping_v2_bot.py --status                # connect READ-ONLY: contracts, history, today's levels + decisions
  python scalping_v2_bot.py --test-orders MNQ       # PAPER ONLY: place a far-away bracket, verify, cancel it
  python scalping_v2_bot.py --once                  # one decision pass at the latest bar (orders only if armed)
  python scalping_v2_bot.py                         # scheduled loop (leave running)
  python scalping_v2_bot.py --config scalping_v2_live.json --i-understand-live
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
if _MODULE_DIR not in sys.path:
    sys.path.insert(0, _MODULE_DIR)
_APP_DIR = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else _MODULE_DIR

import pandas as pd                     # noqa: E402
import scalping_v2_core as C                    # noqa: E402
import scalping_v2_reports  # noqa: E402,F401  (bundled into the exe; used by write_reports)

ET = ZoneInfo("America/New_York")
STATE_FILE = os.path.join(_APP_DIR, "scalping_v2_state.json")
LOG_DIR = os.path.join(_APP_DIR, "logs")
DEFAULT_CONFIG = os.path.join(_APP_DIR, "scalping_v2.json")
REF = "sv2"
# Trade CSV = the supertrend bot's columns (time = exit time ET, pnl in $ net of commission) + extras at the end.
# One file per strategy instance: scalping_v2_trades_<account>_<symbol>_<strategy>.csv (like supertrend_trades_<name>.csv).
TRADE_COLS = ["time", "strategy", "account", "symbol", "side", "qty", "entry", "exit", "stop", "pnl", "ret_pct",
              "reason", "hold", "r_mult", "entry_time", "trade_id", "commission"]
SIGNAL_COLS = ["time_et", "symbol", "strategy", "bar_et", "dir", "kind", "entry_ref", "stop", "target_est",
               "risk_pts", "risk_usd", "qty", "action", "detail"]


# ─────────────────────────────── utils ───────────────────────────────
def now_et() -> datetime:
    return datetime.now(ET)


def _log_path(tag=None):
    stamp = now_et().strftime("%Y%m%d")
    return os.path.join(LOG_DIR, f"scalping_v2_{tag}_{stamp}.log" if tag else f"scalping_v2_{stamp}.log")


def log(msg: str, tag: str = None):
    """Print + append to the combined logs/scalping_v2_<date>.log and, when tagged with a strategy-instance name,
    to logs/scalping_v2_<account>_<symbol>_<strategy>_<date>.log (one log per instance per day, like supertrend)."""
    line = f"[{now_et():%Y-%m-%d %H:%M:%S ET}] {msg}".replace("—", "-")
    try:
        print(line, flush=True)
    except UnicodeEncodeError:
        print(line.encode("ascii", "replace").decode("ascii"), flush=True)
    os.makedirs(LOG_DIR, exist_ok=True)
    for path in [_log_path()] + ([_log_path(tag)] if tag else []):
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass


def load_config(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def round_tick(x: float, tick: float) -> float:
    return round(round(x / tick) * tick, 10)


def _append_csv(path, cols, row):
    new = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        if new:
            w.writeheader()
        w.writerow({c: row.get(c, "") for c in cols})


def mins(s: str) -> int:
    return C.hhmm_to_min(s)


def liquid_end_today(liquid_hours: str, tz_id: str, today, default_end: int):
    """Today's RTH (liquid-hours) end in ET minutes from IB contractDetails.liquidHours, e.g.
    '20261127:0830-20261127:1200;...' (exchange tz). Returns None when today is CLOSED (holiday),
    min(default_end, segment end) on early-close days, default_end if unparsable."""
    try:
        tz = ZoneInfo({"US/Central": "America/Chicago", "US/Eastern": "America/New_York"}.get(tz_id, tz_id))
        open_et = datetime(today.year, today.month, today.day, 9, 30, tzinfo=ET)
        saw_today = False
        for seg in str(liquid_hours).split(";"):
            if seg.startswith(f"{today:%Y%m%d}:CLOSED"):
                return None
            if "-" not in seg:
                continue
            a, b = seg.split("-")
            sa = datetime.strptime(a, "%Y%m%d:%H%M").replace(tzinfo=tz).astimezone(ET)
            sb = datetime.strptime(b, "%Y%m%d:%H%M").replace(tzinfo=tz).astimezone(ET)
            if sa.date() == today or sb.date() == today:
                saw_today = True
            if sa <= open_et + timedelta(minutes=30) and sb > open_et:
                return min(default_end, sb.hour * 60 + sb.minute) if sb.date() == today else default_end
        return default_end if not saw_today else default_end
    except Exception:
        return default_end


# ─────────────────────────────── bot ───────────────────────────────
class ScalpingV2Bot:
    def __init__(self, cfg: dict, allow_live: bool):
        self.cfg = cfg
        self.paper = bool(cfg.get("paper", True))
        self.dry = bool(cfg.get("dry_run", True))
        if not self.paper and not allow_live:
            raise SystemExit("REFUSING: config paper=false but --i-understand-live not passed.")
        self.ib = None
        self.c = {}                    # sym -> {"cont","fut","tick","pv"}
        self.hist = {}                 # sym -> raw history DataFrame (date, ohlcv) — past sessions
        self.today_df = {}             # sym -> prepared bars+indicators of TODAY (complete bars only)
        self.day = None                # trading date initialised for
        self.blocked = {}              # sym -> reason (foreign exposure / data problems)
        self.sess_end = {}             # sym -> today's RTH end (ET minutes; early-close aware)
        self.strats = {}               # name -> (Windowed strategy, params, cfg)
        for name, sc in cfg["strategies"].items():
            if sc.get("enabled", True):
                st, p = C.build_strategy(name, sc)
                self.strats[name] = (st, p, sc)
        self.priority = [s for s in cfg.get("strategy_priority", list(self.strats)) if s in self.strats]
        self.state = self._load_state()
        self._conn_ok = True
        self._exec_seen = set(self.state.get("exec_ids", []))
        self.trades_csv_base = os.path.join(_APP_DIR, cfg.get("trade_log_csv", "scalping_v2_trades.csv"))
        self.signals_csv = os.path.join(_APP_DIR, "scalping_v2_signals.csv")
        self._breaker_logged = False

    # ---- state ----
    def _load_state(self):
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE, encoding="utf-8") as f:
                    return json.load(f)
            except (OSError, json.JSONDecodeError):
                pass
        return {"date": None, "trades": {}, "seen_signals": [], "exec_ids": [], "day_pnl": 0.0, "day_trades": 0}

    def save_state(self):
        self.state["exec_ids"] = sorted(self._exec_seen)[-2000:]
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.state, f, indent=2, default=str)
        os.replace(tmp, STATE_FILE)

    def active_trades(self, sym=None):
        return {k: t for k, t in self.state["trades"].items()
                if t["status"] in ("pending", "open") and (sym is None or t["sym"] == sym)}

    # ---- connection (same resilient pattern as the QM / supertrend bots) ----
    _BENIGN = {2104, 2106, 2107, 2108, 2119, 2158, 2100, 2150, 2174}

    def _wire(self):
        for hook, fn in (("errorEvent", self._on_error), ("disconnectedEvent", self._on_disc),
                         ("execDetailsEvent", self._on_exec), ("commissionReportEvent", self._on_comm),
                         ("orderStatusEvent", self._on_status)):
            try:
                getattr(self.ib, hook).__iadd__(fn)
            except Exception:
                pass
        self._status_seen = {}

    def _on_error(self, *a):
        reqId, code, msg = (a + (None, None, ""))[:3]
        if code == 1100:
            self._conn_ok = False
            log("IB 1100: connectivity LOST")
        elif code in (1101, 1102):
            self._conn_ok = True
            log(f"IB {code}: connectivity RESTORED")
        elif code in self._BENIGN:
            return
        else:
            log(f"IB msg code={code} req={reqId}: {msg}")

    def _on_disc(self):
        log("API socket disconnected — reconnecting on next tick")

    def _on_status(self, trade):
        try:
            oid, st = trade.order.orderId, trade.orderStatus.status
            if self._status_seen.get(oid) == st:
                return
            self._status_seen[oid] = st
            ref = str(getattr(trade.order, "orderRef", ""))
            if ref.startswith(REF) and st in ("Cancelled", "ApiCancelled", "Inactive"):
                log(f"ORDER {st}: {ref} {trade.order.action} {trade.order.orderType} id={oid}",
                    tag=self._strat_of_ref(ref))
        except Exception as e:
            log(f"status-log error: {e}")

    def _connect_once(self):
        from ib_async import IB
        try:
            if self.ib is not None and self.ib.isConnected():
                self.ib.disconnect()
        except Exception:
            pass
        self.ib = IB()
        self._wire()
        self.ib.connect(self.cfg["host"], int(self.cfg["port"]), clientId=int(self.cfg["client_id"]),
                        account=self.cfg.get("account", "") or "", timeout=20)
        mgd = list(self.ib.managedAccounts() or [])
        acct = self.cfg.get("account", "") or ""
        if mgd and acct not in mgd:
            if len(mgd) == 1:
                self.cfg["account"] = mgd[0]
            else:
                raise SystemExit(f"config account '{acct}' not in managed accounts {mgd}; set 'account'.")
        if self.paper and not str(self.cfg["account"]).startswith("D"):
            raise SystemExit(f"paper=true but account {self.cfg['account']} does not look like a paper (DU…) account.")
        self.ib.reqPositions()
        self._conn_ok = True

    def connect(self):
        import asyncio
        try:
            asyncio.set_event_loop(asyncio.new_event_loop())
        except Exception:
            pass
        log(f"connecting {self.cfg['host']}:{self.cfg['port']} clientId={self.cfg['client_id']} "
            f"[{'PAPER' if self.paper else 'LIVE'}] {'DRY-RUN' if self.dry else 'ARMED'}")
        self._connect_once()
        self.ib.sleep(1.0)
        log(f"connected account={self.cfg['account']}")

    def ensure_connected(self):
        if self.ib and self.ib.isConnected():
            if not self._conn_ok:
                log("IB 1100 — socket alive, waiting for restore...")
                while self.ib.isConnected() and not self._conn_ok:
                    self._sleep(2)
            return
        attempt = 0
        while True:
            attempt += 1
            try:
                self._connect_once()
                log(f"reconnected (attempt {attempt}) — re-syncing executions/orders")
                self.sync_from_ib()
                return
            except SystemExit:
                raise
            except Exception as e:
                wait = 5 if attempt <= 3 else int(self.cfg.get("reconnect_backoff_sec", 60))
                log(f"reconnect attempt {attempt} failed: {e}; retry in {wait}s")
                self._sleep(wait)

    def _sleep(self, secs):
        import asyncio
        try:
            if self.ib is not None and self.ib.isConnected():
                self.ib.sleep(secs)
            else:
                time.sleep(secs)
        except (asyncio.CancelledError, Exception):
            time.sleep(secs)

    def disconnect(self):
        try:
            if self.ib and self.ib.isConnected():
                self.ib.disconnect()
        except Exception:
            pass

    # ---- contracts & data ----
    def resolve_contracts(self):
        from ib_async import ContFuture, Future
        for sym, sc in self.cfg["symbols"].items():
            if not sc.get("enabled", True):
                continue
            cf = ContFuture(sym, sc.get("exchange", C.SPECS[sym]["exchange"]), currency="USD")
            q = self.ib.qualifyContracts(cf)
            if not q:
                self.blocked[sym] = "contract not found"
                log(f"{sym}: ContFuture did not qualify — symbol BLOCKED")
                continue
            fut = Future(conId=cf.conId, exchange=cf.exchange)
            self.ib.qualifyContracts(fut)
            tick, pv = C.SPECS[sym]["tick"], C.SPECS[sym]["pv"]
            s_end = mins(self.cfg.get("session_end", "16:00"))
            end_today = s_end
            try:
                det = self.ib.reqContractDetails(fut)
                if det:
                    tick = float(det[0].minTick) or tick
                    hours = det[0].liquidHours if self._use_rth(sym) else det[0].tradingHours
                    end_today = liquid_end_today(hours, det[0].timeZoneId, now_et().date(), s_end)
                pv = float(fut.multiplier or pv)
            except Exception:
                pass
            self.c[sym] = {"cont": cf, "fut": fut, "tick": tick, "pv": pv}
            if end_today is None:
                self.blocked[sym] = "market closed today (holiday)"
                log(f"{sym}: exchange CLOSED today (liquidHours) - no trading")
            else:
                self.sess_end[sym] = end_today
                if end_today < s_end:
                    log(f"{sym}: EARLY CLOSE today - RTH ends {end_today // 60:02d}:{end_today % 60:02d} ET; "
                        f"all {sym} trades flatten before then")
            log(f"{sym}: trading {fut.localSymbol} (conId {fut.conId}, expiry {fut.lastTradeDateOrContractMonth}) "
                f"tick={tick} multiplier={pv}")

    def _use_rth(self, sym) -> bool:
        """CL/MCL: IB's RTH is the 09:00-14:30 pit, so they use full-session bars (trimmed to 09:30-16:00 ET)."""
        return bool(self.cfg["symbols"].get(sym, {}).get("use_rth", C.SPECS.get(sym, {}).get("use_rth", True)))

    def _bars(self, contract, duration: str, use_rth: bool = True):
        bars = self.ib.reqHistoricalData(contract, "", duration, "5 mins", "TRADES", use_rth, 2, timeout=120) or []
        return pd.DataFrame([{"date": b.date, "open": b.open, "high": b.high, "low": b.low,
                              "close": b.close, "volume": b.volume} for b in bars])

    def load_history(self, sym):
        df = self._bars(self.c[sym]["cont"], f"{int(self.cfg.get('history_days', 120))} D", self._use_rth(sym))
        if df.empty:
            raise RuntimeError("no history returned")
        df["date"] = pd.to_datetime(df["date"], utc=True)
        today = now_et().date()
        self.hist[sym] = df[df.date.dt.tz_convert(ET).dt.date < today].reset_index(drop=True)
        prep = C.prepare_bars(self.hist[sym])
        log(f"{sym}: history {prep.day.nunique()} sessions {prep.day.min()} .. {prep.day.max()} ({len(prep)} bars)")

    def refresh_today(self, sym, expect_last_tm=None, retries=3):
        """Fetch today's bars, keep only COMPLETE ones, recompute indicators over history+today."""
        today = now_et().date()
        for attempt in range(retries):
            df = self._bars(self.c[sym]["cont"], "1 D", self._use_rth(sym))
            if not df.empty:
                df["date"] = pd.to_datetime(df["date"], utc=True)
                cutoff = pd.Timestamp(now_et()).tz_convert("UTC") - pd.Timedelta(minutes=5)
                df = df[(df.date.dt.tz_convert(ET).dt.date == today) & (df.date <= cutoff)]
            full = pd.concat([self.hist[sym], df], ignore_index=True)
            prep = C.prepare_bars(full, live_day=today)
            ind = C.add_indicators(prep, self.c[sym]["tick"])
            td = ind[ind.day == today].reset_index(drop=True)
            last = int(td.tm.iloc[-1]) if len(td) else None
            if expect_last_tm is None or last == expect_last_tm:
                self.today_df[sym] = td
                return td
            self._sleep(3)
        log(f"{sym}: latest bar {last} != expected {expect_last_tm} after {retries} tries — skipping this bar")
        self.today_df[sym] = td
        return None

    # ---- foreign-exposure guard ----
    def check_foreign(self):
        """Block symbols where someone else (another bot / manual) holds a position or works orders."""
        try:
            self.ib.reqAllOpenOrders()
        except Exception:
            pass
        ours = {}
        for t in self.active_trades().values():
            if t["status"] == "open":
                ours[t["sym"]] = ours.get(t["sym"], 0) + t["dir"] * t["filled"] - t["dir"] * t.get("exited", 0)
        for sym, cc in self.c.items():
            pos = sum(int(p.position) for p in self.ib.positions()
                      if p.contract.conId == cc["fut"].conId and p.account == self.cfg["account"])
            foreign_orders = [t for t in self.ib.openTrades()
                              if t.contract.conId == cc["fut"].conId
                              and not str(t.order.orderRef or "").startswith(REF)
                              and t.orderStatus.status in ("PreSubmitted", "Submitted")]
            reason = ""
            if pos != ours.get(sym, 0):
                reason = f"account position {pos:+d} != this bot's {ours.get(sym, 0):+d}"
            elif foreign_orders:
                reason = f"{len(foreign_orders)} working order(s) from another client"
            was_foreign = str(self.blocked.get(sym, "")).startswith("foreign:")
            if reason and not self.cfg.get("allow_shared_symbols", False):
                if self.blocked.get(sym) != "foreign: " + reason:
                    log(f"{sym}: FOREIGN EXPOSURE — {reason}. New entries BLOCKED for {sym} "
                        f"(another bot e.g. supertrend trading it on this account?). Set allow_shared_symbols "
                        f"to override (not recommended).")
                self.blocked[sym] = "foreign: " + reason
            elif was_foreign and not reason:
                log(f"{sym}: foreign exposure cleared — unblocked")
                self.blocked.pop(sym, None)

    # ---- executions → trade state (idempotent; also used after restarts) ----
    @staticmethod
    def _parse_ref(ref: str):
        parts = str(ref or "").split("|")
        return (parts[1], parts[2]) if len(parts) == 3 and parts[0] == REF else (None, None)

    def _sname(self, sym, strategy):
        """Strategy-instance name '<account>_<symbol>_<strategy>' (supertrend style: DU672616_MNQ_5m)."""
        raw = f"{self.cfg.get('account') or 'acct'}_{sym}_{strategy}"
        return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in raw)

    def _strat_of_ref(self, ref):
        tid, _ = self._parse_ref(ref)
        t = self.state["trades"].get(tid) if tid else None
        return self._sname(t["sym"], t["strategy"]) if t else None

    def _apply_fill(self, ex):
        if ex.execId in self._exec_seen:
            return
        tid, role = self._parse_ref(getattr(ex, "orderRef", ""))
        if not tid or tid not in self.state["trades"]:
            return
        self._exec_seen.add(ex.execId)
        t = self.state["trades"][tid]
        qty, px = float(ex.shares), float(ex.price)
        ts = ex.time.astimezone(ET).strftime("%Y-%m-%d %H:%M:%S") if hasattr(ex.time, "astimezone") else str(ex.time)
        if role == "entry":
            tot = t["filled"] + qty
            t["entry_fill"] = (t.get("entry_fill") or 0) * t["filled"] / tot + px * qty / tot if t["filled"] else px
            t["filled"] = tot
            t["entry_time"] = t.get("entry_time") or ts
            t["status"] = "open"
            log(f"ENTRY FILLED {tid}: {'BUY' if t['dir'] == 1 else 'SELL'} {int(qty)} @ {px} (avg {t['entry_fill']:.4f})",
                tag=self._sname(t["sym"], t["strategy"]))
            if t["filled"] >= t["qty"]:
                self._reanchor_target(t)
        else:
            tot = t.get("exited", 0) + qty
            t["exit_fill"] = (t.get("exit_fill") or 0) * t.get("exited", 0) / tot + px * qty / tot if t.get("exited") else px
            t["exited"] = tot
            t["exit_time"] = ts
            t["exit_reason"] = t.get("exit_reason") or {"tp": "target", "sl": "stop"}.get(role, role)
            log(f"EXIT FILLED {tid} [{role}]: {int(qty)} @ {px}", tag=self._sname(t["sym"], t["strategy"]))
            if t["filled"] and t["exited"] >= t["filled"]:
                self._close_trade(t)
        self.save_state()

    def _on_exec(self, trade, fill):
        try:
            self._apply_fill(fill.execution)
        except Exception as e:
            log(f"exec handler error: {e}")

    def _on_comm(self, trade, fill, report):
        try:
            tid, _ = self._parse_ref(getattr(fill.execution, "orderRef", ""))
            if tid in self.state["trades"] and report.commission and report.commission < 1e6:
                t = self.state["trades"][tid]
                t["comm"] = round(t.get("comm", 0.0) + float(report.commission), 2)
                self.save_state()
        except Exception:
            pass

    def sync_from_ib(self):
        """Rebuild fills for our trades from today's executions (orderRef-tagged) after start/reconnect."""
        try:
            for f in self.ib.reqExecutions():
                self._apply_fill(f.execution)
        except Exception as e:
            log(f"sync executions error: {e}")
        # a pending entry whose parent order no longer works and never filled -> cancelled/expired
        try:
            self.ib.reqAllOpenOrders()
            working = {str(t.order.orderRef) for t in self.ib.openTrades()
                       if t.orderStatus.status in ("PreSubmitted", "Submitted", "PendingSubmit", "ApiPending")}
        except Exception:
            working = None
        if working is not None:
            for tid, t in list(self.active_trades().items()):
                if t["status"] == "pending" and f"{REF}|{tid}|entry" not in working and not self.dry:
                    t["status"] = "cancelled"
                    log(f"{tid}: entry order no longer working and unfilled -> cancelled", tag=self._sname(t["sym"], t["strategy"]))
        self.save_state()

    # ---- trade lifecycle ----
    def _close_trade(self, t):
        if t["status"] == "closed":
            return
        t["status"] = "closed"
        pv = self.c.get(t["sym"], {}).get("pv", C.SPECS[t["sym"]]["pv"])
        comm = t.get("comm")
        if comm is None:
            comm = 2 * float(self.cfg.get("commission_per_side", {}).get(t["sym"], 0.62)) * t["filled"]
        pts = (t["exit_fill"] - t["entry_fill"]) * t["dir"]
        pnl = pts * pv * t["filled"] - comm
        risk_pts = abs(t["entry_fill"] - t["stop"])
        t["pnl"] = round(pnl, 2)
        self.state["day_pnl"] = round(self.state.get("day_pnl", 0.0) + pnl, 2)
        name = self._sname(t["sym"], t["strategy"])
        hold = ""
        try:
            hold = str(datetime.fromisoformat(t["exit_time"]) - datetime.fromisoformat(t["entry_time"])).split(".")[0]
        except Exception:
            pass
        ret = ((t["exit_fill"] / t["entry_fill"] - 1) * 100 * t["dir"]) if t["entry_fill"] else 0.0
        row = {"time": t.get("exit_time", ""), "strategy": name, "account": self.cfg.get("account", ""),
               "symbol": t["sym"], "side": "LONG" if t["dir"] == 1 else "SHORT", "qty": int(t["filled"]),
               "entry": round(t["entry_fill"], 4), "exit": round(t["exit_fill"], 4), "stop": round(t["stop"], 4),
               "pnl": round(pnl, 2), "ret_pct": round(ret, 3), "reason": str(t.get("exit_reason", "")).upper(),
               "hold": hold, "r_mult": round(pts / risk_pts, 2) if risk_pts else "",
               "entry_time": t.get("entry_time", ""), "trade_id": t["id"], "commission": round(comm, 2)}
        base, ext = os.path.splitext(self.trades_csv_base)
        try:
            _append_csv(f"{base}_{name}{ext or '.csv'}", TRADE_COLS, row)
        except OSError as e:
            log(f"trade csv write failed: {e}")
        log(f"CLOSED {row['side']} {t['sym']} {t['strategy']} {row['reason']} entry {row['entry']} exit {row['exit']} "
            f"qty {row['qty']} pnl ${pnl:,.2f} ({row['r_mult']}R, {ret:+.2f}%) hold {hold}  (day ${self.state['day_pnl']:,.2f})",
            tag=name)
        self._cancel_children(t)       # belt & braces: OCA should already have done it

    def _contract_for(self, t):
        """The contract a trade was opened in (matters across a roll: the front month may have changed)."""
        cc = self.c.get(t["sym"])
        if cc and cc["fut"].conId == t.get("conId"):
            return cc["fut"]
        from ib_async import Future
        f = Future(conId=t["conId"])
        self.ib.qualifyContracts(f)
        return f

    def _orders_for(self, tid, roles=("entry", "tp", "sl", "close")):
        out = {}
        for tr in self.ib.openTrades():
            r_tid, role = self._parse_ref(tr.order.orderRef)
            if r_tid == tid and role in roles:
                out[role] = tr
        return out

    def _cancel_children(self, t):
        if self.dry:
            return
        for role, tr in self._orders_for(t["id"], ("tp", "sl")).items():
            try:
                self.ib.cancelOrder(tr.order)
            except Exception:
                pass

    def _reanchor_target(self, t):
        """Move the take-profit to exactly 2R from the ACTUAL fill (the backtest measures R from the fill)."""
        if self.dry:
            return
        tick = self.c[t["sym"]]["tick"]
        e = t["entry_fill"]
        risk = (e - t["stop"]) * t["dir"]
        if risk <= 0:
            log(f"{t['id']}: filled through the stop (fill {e}, stop {t['stop']}) — stop child will exit", tag=self._sname(t["sym"], t["strategy"]))
            return
        new_tgt = round_tick(e + t["dir"] * C.R_MULT * risk, tick)
        tp = self._orders_for(t["id"], ("tp",)).get("tp")
        if tp and abs(tp.order.lmtPrice - new_tgt) >= tick / 2:
            tp.order.lmtPrice = new_tgt
            self.ib.placeOrder(self._contract_for(t), tp.order)
            log(f"{t['id']}: target re-anchored to 2R from fill -> {new_tgt}", tag=self._sname(t["sym"], t["strategy"]))
        t["target"] = new_tgt

    def place_trade(self, sym, name, sig, bar_tm, ref_close):
        """Validate + size + place the bracket for a live signal."""
        from ib_async import MarketOrder, StopOrder, LimitOrder
        cc, sc = self.c[sym], self.cfg["symbols"][sym]
        tick, pv = cc["tick"], cc["pv"]
        d = int(sig["dir"])
        kind = "stp" if sig.get("entry") is not None else "mkt"
        e_ref = round_tick(sig["entry"], tick) if kind == "stp" else ref_close
        stop = round_tick(sig["stop"], tick)
        risk_pts = (e_ref - stop) * d
        tgt = round_tick(e_ref + d * C.R_MULT * risk_pts, tick)
        sz = self.cfg.get("sizing", {})
        if sz.get("mode") == "risk":
            qty = min(int(sz.get("risk_usd", 200) // max(risk_pts * pv, 1e-9)), int(sz.get("max_contracts", 1)))
        else:
            qty = int(sc.get("contracts", 1))
        tid = f"{sym}-{name}-{now_et():%Y%m%d}-{bar_tm // 60:02d}{bar_tm % 60:02d}"
        row = {"time_et": f"{now_et():%Y-%m-%d %H:%M:%S}", "symbol": sym, "strategy": name,
               "bar_et": f"{bar_tm // 60:02d}:{bar_tm % 60:02d}", "dir": "LONG" if d == 1 else "SHORT", "kind": kind,
               "entry_ref": e_ref, "stop": stop, "target_est": tgt, "risk_pts": round(risk_pts, 4),
               "risk_usd": round(risk_pts * pv * max(qty, 1), 2), "qty": qty}

        def skip(why):
            row.update(action="SKIP", detail=why)
            _append_csv(self.signals_csv, SIGNAL_COLS, row)
            log(f"SIGNAL {tid} {row['dir']} skipped: {why}", tag=self._sname(sym, name))

        if tid in self.state["seen_signals"]:
            return
        self.state["seen_signals"].append(tid)
        if sym in self.blocked:
            return skip(f"symbol blocked ({self.blocked[sym]})")
        if self.cfg.get("one_position_per_symbol", True) and self.active_trades(sym):
            return skip("symbol busy (another strategy in position)")
        if self.state.get("day_trades", 0) >= int(self.cfg.get("max_trades_per_day", 999)):
            return skip("max_trades_per_day reached")
        if self.breaker_tripped():
            return skip("daily loss circuit breaker")
        if risk_pts < 4 * tick:
            return skip(f"risk {risk_pts} < 4 ticks")
        if qty < 1:
            return skip("size < 1 contract")
        if risk_pts * pv * qty > float(sc.get("max_risk_usd", 1e9)):
            return skip(f"risk ${risk_pts * pv * qty:,.0f} > max_risk_usd {sc.get('max_risk_usd')}")
        exit_at = self._exit_at(name, sym)
        msg = (f"{row['dir']} {qty} {cc['fut'].localSymbol} {kind.upper()}{'@' + str(e_ref) if kind == 'stp' else ''} "
               f"stop {stop} target~{tgt} risk {risk_pts:.2f}pt ${risk_pts * pv * qty:,.0f} exit_by {exit_at:%H:%M:%S}")
        if self.dry:
            row.update(action="DRY", detail=msg)
            _append_csv(self.signals_csv, SIGNAL_COLS, row)
            log(f"[DRY] SIGNAL {tid}: {msg}", tag=self._sname(sym, name))
            self.save_state()
            return
        act, opp = ("BUY", "SELL") if d == 1 else ("SELL", "BUY")
        parent = MarketOrder(act, qty) if kind == "mkt" else StopOrder(act, qty, e_ref)
        parent.tif = self.cfg.get("entry_tif", "DAY")
        tp = LimitOrder(opp, qty, tgt)
        sl = StopOrder(opp, qty, stop)
        oca = f"{REF}-{tid}"
        for o, role in ((parent, "entry"), (tp, "tp"), (sl, "sl")):
            o.orderId = self.ib.client.getReqId()
            o.orderRef = f"{REF}|{tid}|{role}"
            o.account = self.cfg["account"]
            o.transmit = False
        tp.parentId = sl.parentId = parent.orderId
        tp.tif = sl.tif = "GTC"
        tp.ocaGroup = sl.ocaGroup = oca
        tp.ocaType = sl.ocaType = 1
        sl.transmit = True
        self.state["trades"][tid] = {
            "id": tid, "sym": sym, "strategy": name, "dir": d, "qty": qty, "kind": kind, "entry_ref": e_ref,
            "stop": stop, "target": tgt, "status": "pending", "filled": 0, "exited": 0, "placed": f"{now_et():%H:%M:%S}",
            "expire_at": (self._bar_end(bar_tm, int(sig.get("expire", 1))).isoformat() if kind == "stp" else None),
            "exit_at": exit_at.isoformat(), "conId": cc["fut"].conId, "bar_tm": bar_tm}
        self.state["day_trades"] = self.state.get("day_trades", 0) + 1
        self.save_state()
        for o in (parent, tp, sl):
            self.ib.placeOrder(cc["fut"], o)
        self.ib.sleep(0.5)
        row.update(action="PLACED", detail=f"orders {parent.orderId}/{tp.orderId}/{sl.orderId}")
        _append_csv(self.signals_csv, SIGNAL_COLS, row)
        log(f"ARMED {tid}: {msg}  [orders {parent.orderId}/{tp.orderId}/{sl.orderId}]", tag=self._sname(sym, name))

    def _bar_end(self, bar_tm, expire_bars):
        """End of the `expire_bars`-th bar after the signal bar (signal bar starts at bar_tm)."""
        d = now_et().date()
        start = datetime(d.year, d.month, d.day, bar_tm // 60, bar_tm % 60, tzinfo=ET)
        return start + timedelta(minutes=5 * (1 + expire_bars))

    def _exit_at(self, name, sym):
        sc = self.strats[name][2]
        s_end = self.sess_end.get(sym, mins(self.cfg.get("session_end", "16:00")))
        end = mins(sc.get("window", ["09:30", "16:00"])[1]) if sc.get("mode") == "flat" else s_end
        end = min(end, s_end)
        d = now_et().date()
        return datetime(d.year, d.month, d.day, end // 60, end % 60, tzinfo=ET) - timedelta(
            seconds=int(self.cfg.get("flatten_lead_sec", 20)))

    def flatten(self, t, reason):
        """Exit THIS trade only: cancel its children, re-check fills, then MKT for its remaining quantity."""
        from ib_async import MarketOrder
        if self.dry:
            return
        self._cancel_children(t)
        self.ib.sleep(1.0)
        self.sync_from_ib()
        if t["status"] != "open":
            return
        left = int(t["filled"] - t.get("exited", 0))
        if left <= 0:
            return
        if self._orders_for(t["id"], ("close",)):
            return                                       # a close order is already working
        o = MarketOrder("SELL" if t["dir"] == 1 else "BUY", left)
        o.orderRef = f"{REF}|{t['id']}|{reason}"
        o.account = self.cfg["account"]
        o.tif = "DAY"
        t["exit_reason"] = reason
        self.ib.placeOrder(self._contract_for(t), o)
        self.save_state()
        log(f"FLATTEN {t['id']} [{reason}]: {o.action} {left} at market", tag=self._sname(t["sym"], t["strategy"]))

    def cancel_entry(self, t, why):
        if self.dry:
            return
        tr = self._orders_for(t["id"], ("entry",)).get("entry")
        if tr:
            self.ib.cancelOrder(tr.order)                 # children are cancelled with the parent
            self.ib.sleep(0.5)
        self.sync_from_ib()
        if t["status"] == "pending":
            t["status"] = "cancelled"
            log(f"{t['id']}: unfilled entry cancelled ({why})", tag=self._sname(t["sym"], t["strategy"]))
        elif t["status"] == "open" and t["filled"] < t["qty"]:
            self._resize_children(t)
        self.save_state()

    def _resize_children(self, t):
        """Partially-filled entry was cancelled: shrink the protective children to the filled quantity."""
        for role, tr in self._orders_for(t["id"], ("tp", "sl")).items():
            tr.order.totalQuantity = int(t["filled"])
            self.ib.placeOrder(self._contract_for(t), tr.order)
        log(f"{t['id']}: partial entry fill {t['filled']}/{t['qty']} — children resized", tag=self._sname(t["sym"], t["strategy"]))

    def manage_timers(self):
        n = now_et()
        for tid, t in list(self.active_trades().items()):
            if t["status"] == "pending":
                if t.get("expire_at") and n >= datetime.fromisoformat(t["expire_at"]):
                    self.cancel_entry(t, "stop-entry expired")
                elif n >= datetime.fromisoformat(t["exit_at"]):
                    self.cancel_entry(t, "window closed")
            elif t["status"] == "open" and n >= datetime.fromisoformat(t["exit_at"]):
                if not t.get("flatten_sent"):
                    t["flatten_sent"] = True
                    sc = self.strats.get(t["strategy"], (None, None, {}))[2]
                    self.flatten(t, "window" if sc.get("mode") == "flat" else "eod")

    # ---- risk ----
    def breaker_tripped(self):
        lim = float(self.cfg.get("daily_loss_limit_usd", 0) or 0)
        if not lim:
            return False
        unreal = 0.0
        for t in self.active_trades().values():
            if t["status"] == "open" and t["sym"] in self.today_df and len(self.today_df[t["sym"]]):
                last = float(self.today_df[t["sym"]].close.iloc[-1])
                unreal += (last - t["entry_fill"]) * t["dir"] * self.c[t["sym"]]["pv"] * (t["filled"] - t.get("exited", 0))
        hit = self.state.get("day_pnl", 0.0) + unreal <= -lim
        if hit and not self._breaker_logged:
            log(f"CIRCUIT BREAKER: day P&L ${self.state.get('day_pnl', 0) + unreal:,.0f} <= -${lim:,.0f} — no new entries today")
            self._breaker_logged = True
        return hit

    # ---- daily init / decisions ----
    def day_init(self):
        today = now_et().date()
        if self.state.get("date") != str(today):
            stale = {k: t for k, t in self.active_trades().items()}
            if stale:
                log(f"found {len(stale)} non-closed trade(s) from {self.state.get('date')} — handling as stale")
            self.state.update(date=str(today), seen_signals=[], day_pnl=0.0, day_trades=0)
            self.state["trades"] = {k: t for k, t in self.state["trades"].items() if t["status"] in ("pending", "open")}
            self._breaker_logged = False
            self.save_state()
        self.blocked, self.sess_end = {}, {}
        self.resolve_contracts()
        for sym in list(self.c):
            if sym in self.blocked:
                continue
            try:
                self.load_history(sym)
            except Exception as e:
                self.blocked[sym] = f"history failed: {e}"
                log(f"{sym}: history load failed ({e}) — BLOCKED")
        self.sync_from_ib()
        # stale trades from a previous session (bot died before 16:00): flatten them
        for tid, t in list(self.active_trades().items()):
            if not tid.split("-")[-2] == f"{today:%Y%m%d}":
                if t["status"] == "pending":
                    self.cancel_entry(t, "stale (previous session)")
                elif self.cfg.get("flatten_stale_trades", True):
                    log(f"{tid}: STALE open trade from a previous session — flattening", tag=self._sname(t["sym"], t["strategy"]))
                    self.flatten(t, "stale")
        self.check_foreign()
        self.day = today
        log(f"day initialised {today}: symbols {list(self.c)} blocked={self.blocked or 'none'} "
            f"strategies={self.priority}")

    def evaluate(self, boundary_tm):
        """Called right after the bar that ENDS at boundary_tm (minutes) closes."""
        expect = boundary_tm - 5
        self.check_foreign()
        for sym in list(self.c):
            if sym in self.blocked and not self.blocked[sym].startswith("foreign:"):
                continue
            if boundary_tm > self.sess_end.get(sym, 960):
                continue
            td = self.refresh_today(sym, expect_last_tm=expect)
            if td is None or td.empty:
                continue
            for name in self.priority:
                st, p, sc = self.strats[name]
                if sym not in sc.get("symbols", []):
                    continue
                dec = C.live_decision(td, st, p, self.c[sym]["tick"])
                if "signal" in dec:
                    self.place_trade(sym, name, dec["signal"], dec["bar_tm"], dec["ref"])
                elif dec.get("error"):
                    log(f"{sym} {name}: {dec['error']}", tag=self._sname(sym, name))

    def write_reports(self, day=None):
        """EOD + performance HTML reports (supertrend layout) into <app dir>/reports/."""
        try:
            import scalping_v2_reports as RP
            e, p, rows = RP.build(_APP_DIR, float(self.cfg.get("account_size_usd", 150000)), day or now_et().date())
            log(f"REPORTS written: {e} | {p} ({len(rows)} closed trades to date)")
        except Exception as ex:
            log(f"report generation failed: {ex}")

    def log_status(self):
        act = self.active_trades()
        parts = [f"{t['id']}:{t['status']}{'' if t['status'] == 'pending' else ' @' + str(round(t.get('entry_fill') or 0, 2))}"
                 for t in act.values()]
        log(f"STATUS day_pnl=${self.state.get('day_pnl', 0):,.2f} trades_today={self.state.get('day_trades', 0)} "
            f"active={parts or 'none'} blocked={self.blocked or 'none'}")

    def run_loop(self):
        s_start, s_end = mins(self.cfg.get("session_start", "09:30")), mins(self.cfg.get("session_end", "16:00"))
        delay = int(self.cfg.get("bar_delay_sec", 6))
        status_every = max(60, int(self.cfg.get("status_every_min", 30)) * 60)
        last_status, done_boundary, reports_done = 0.0, None, None
        log(f"loop started: session {self.cfg.get('session_start')}–{self.cfg.get('session_end')} ET, "
            f"strategies {self.priority}")
        import asyncio
        while True:
            try:
                self.ensure_connected()
                n = now_et()
                weekday = n.weekday() < 5
                m = n.hour * 60 + n.minute
                if weekday and m >= s_start - 30 and self.day != n.date():
                    self.day_init()
                if weekday and self.day == n.date():
                    self.manage_timers()
                    boundary = (m // 5) * 5
                    if (s_start + 5 <= boundary <= s_end and boundary != done_boundary
                            and n.second >= delay and m - boundary < 5):
                        done_boundary = boundary
                        self.evaluate(boundary)
                    for t in list(self.active_trades().values()):     # safety sweep after each symbol's close
                        if m < self.sess_end.get(t["sym"], s_end) + 2:
                            continue
                        if t["status"] == "pending":
                            self.cancel_entry(t, "session over")
                        elif not t.get("flatten_sent"):
                            t["flatten_sent"] = True
                            self.flatten(t, "eod")
                # end-of-day reports once per trading day, after every symbol's session end
                if (weekday and self.day == n.date() and reports_done != n.date()
                        and m >= max(self.sess_end.values() or [s_end]) + 5 and not self.active_trades()):
                    self.write_reports()
                    reports_done = n.date()
                if time.time() - last_status >= status_every:
                    self.log_status()
                    last_status = time.time()
                self._sleep(float(self.cfg.get("poll_seconds", 2)))
            except KeyboardInterrupt:
                raise
            except SystemExit:
                raise
            except (asyncio.CancelledError, Exception) as e:
                log(f"loop: {type(e).__name__}: {e} — tearing down client, reconnecting next tick")
                try:
                    self.ib.disconnect()
                except Exception:
                    pass
                self._sleep(3)

    # ---- one-off commands ----
    def cmd_status(self):
        """READ-ONLY: contracts, history, today's/most recent session levels and each strategy's decision."""
        self.resolve_contracts()
        for sym in self.c:
            self.load_history(sym)
        self.check_foreign()
        today = now_et().date()
        for sym in self.c:
            td = self.refresh_today(sym)
            label = "today"
            if td is None or td.empty:                        # market closed today -> show the last session
                prep = C.add_indicators(C.prepare_bars(self.hist[sym]), self.c[sym]["tick"])
                last_day = prep.day.max()
                td = prep[prep.day == last_day].reset_index(drop=True)
                label = f"last session {last_day}"
            D = C.Day(td)
            ib_hi = D.high[D.tm < 630].max() if (D.tm < 630).any() else float("nan")
            ib_lo = D.low[D.tm < 630].min() if (D.tm < 630).any() else float("nan")
            print(f"\n=== {sym} ({self.c[sym]['fut'].localSymbol}) {label}: {D.n} bars, last {D.tm[-1] // 60:02d}:{D.tm[-1] % 60:02d} "
                  f"close {D.close[-1]}")
            print(f"  daily trend(e20) {D.tr20[0]:+.0f}  prior close {D.pdc[0]}  14d avg range {D.datr[0]:.2f}  "
                  f"IB {ib_lo}-{ib_hi}  VWAP {D.vwap[-1]:.2f}  ATR5m {D.atr[-1]:.2f}  blocked: {self.blocked.get(sym, 'no')}")
            for name in self.priority:
                st, p, sc = self.strats[name]
                if sym not in sc.get("symbols", []):
                    continue
                trades = C._run_day(D, st, dict(p), self.c[sym]["tick"], self.c[sym]["tick"])
                dec = C.live_decision(td, st, p, self.c[sym]["tick"])
                tx = "; ".join(f"{'L' if t['dir'] == 1 else 'S'} {t['et'] // 60:02d}:{t['et'] % 60:02d} "
                               f"{t['entry']:.2f}->{t['exit']:.2f} {t['why']}" for t in trades) or "none"
                print(f"  {name:14s} window {sc['window']} {sc['mode']:4s} | trades this session: {tx} | "
                      f"live edge: {list(dec.keys()) or 'nothing'}")
        fut_pos = ", ".join(f"{p.contract.localSymbol} {int(p.position):+d}"
                            for p in self.ib.positions() if p.contract.secType == "FUT") or "none"
        print(f"\nlocal state: {len(self.active_trades())} active bot trade(s); futures positions on account "
              f"{self.cfg['account']}: {fut_pos}")


    def cmd_test_orders(self, sym):
        """PAPER ONLY: place a non-marketable bracket far from the market, confirm IB accepts it, cancel it."""
        from ib_async import StopOrder, LimitOrder
        if not self.paper or not str(self.cfg["account"]).startswith("D"):
            raise SystemExit("--test-orders is only allowed on a paper (DU…) account")
        self.resolve_contracts()
        cc = self.c[sym]
        df = self._bars(cc["cont"], "2 D")
        last = float(df.close.iloc[-1])
        tick = cc["tick"]
        trig = round_tick(last * 1.05, tick)              # BUY STOP 5% above the market: cannot fill now
        stop = round_tick(last * 1.03, tick)
        tgt = round_tick(trig + 2 * (trig - stop), tick)
        tid = f"{sym}-TEST-{now_et():%Y%m%d-%H%M%S}"
        parent, tp, sl = StopOrder("BUY", 1, trig), LimitOrder("SELL", 1, tgt), StopOrder("SELL", 1, stop)
        for o, role in ((parent, "entry"), (tp, "tp"), (sl, "sl")):
            o.orderId = self.ib.client.getReqId()
            o.orderRef = f"{REF}|{tid}|{role}"
            o.account = self.cfg["account"]
            o.transmit = False
        parent.tif = "DAY"
        tp.parentId = sl.parentId = parent.orderId
        tp.tif = sl.tif = "GTC"
        tp.ocaGroup = sl.ocaGroup = f"{REF}-{tid}"
        tp.ocaType = sl.ocaType = 1
        sl.transmit = True
        print(f"TEST {cc['fut'].localSymbol}: last {last}  BUY STOP {trig} / TP {tgt} / SL {stop} (1 lot, far from market)")
        trs = [self.ib.placeOrder(cc["fut"], o) for o in (parent, tp, sl)]
        self.ib.sleep(4)
        for tr in trs:
            print(f"  {tr.order.orderRef:40s} {tr.order.orderType:4s} {tr.order.action} status={tr.orderStatus.status} "
                  f"log={[e.message for e in tr.log if e.message][-1:] }")
        self.ib.cancelOrder(parent)
        self.ib.sleep(4)
        for tr in trs:
            print(f"  after cancel: {tr.order.orderRef:40s} status={tr.orderStatus.status}")
        ok = all(tr.orderStatus.status in ("Cancelled", "ApiCancelled") for tr in trs)
        print("ORDER PLUMBING " + ("OK — bracket accepted and cancelled" if ok else "CHECK the statuses above"))


# ─────────────────────────────── entry point ───────────────────────────────
def cmd_check(cfg):
    req = ["paper", "port", "client_id", "symbols", "strategies"]
    miss = [k for k in req if k not in cfg]
    print("config keys OK" if not miss else f"MISSING config keys: {miss}")
    print(f"paper={cfg['paper']} dry_run={cfg.get('dry_run')} port={cfg['port']} client_id={cfg['client_id']} "
          f"account={cfg.get('account') or '(auto)'}")
    for sym, sc in cfg["symbols"].items():
        print(f"  symbol {sym}: enabled={sc.get('enabled', True)} contracts={sc.get('contracts', 1)} "
              f"max_risk_usd={sc.get('max_risk_usd')}")
    for name, sc in cfg["strategies"].items():
        if name not in C.STRATEGY_CLASSES:
            print(f"  UNKNOWN strategy '{name}' (known: {list(C.STRATEGY_CLASSES)})")
            continue
        C.build_strategy(name, sc)
        print(f"  strategy {name:14s} enabled={sc.get('enabled', True)} symbols={sc.get('symbols')} "
              f"window={sc.get('window')} mode={sc.get('mode')} params={sc.get('params')}")
    try:
        import ib_async
        print(f"ib_async import OK ({ib_async.__version__})")
    except Exception as e:
        print(f"ib_async import FAILED: {e}")
    # engine self-test on a synthetic day (no network): must produce a deterministic decision without error
    import numpy as np
    rng = np.random.default_rng(1)
    days = pd.bdate_range("2026-01-05", periods=30)
    rows = []
    px = 20000.0
    for d in days:
        for k in range(78):
            o = px
            px = px + rng.normal(0, 8)
            rows.append({"date": pd.Timestamp(d.date()).tz_localize(ET) + pd.Timedelta(minutes=570 + 5 * k),
                         "open": o, "high": max(o, px) + 3, "low": min(o, px) - 3, "close": px, "volume": 1000})
    df = C.add_indicators(C.prepare_bars(pd.DataFrame(rows)), 0.25)
    td = df[df.day == df.day.max()].reset_index(drop=True)
    for name, sc in cfg["strategies"].items():
        st, p = C.build_strategy(name, sc)
        C.live_decision(td, st, p, 0.25)
    print("engine self-test OK (scalping_v2_core replay ran on synthetic bars)")
    print("check complete (no network / no IB connection performed).")


def main():
    ap = argparse.ArgumentParser(description="Scalping v2 intraday IBKR bot")
    ap.add_argument("--config", default=DEFAULT_CONFIG)
    ap.add_argument("--check", action="store_true", help="validate config + imports + engine (no network)")
    ap.add_argument("--status", action="store_true", help="connect READ-ONLY and print levels/decisions")
    ap.add_argument("--test-orders", metavar="SYM", help="PAPER ONLY: place + cancel a far-away bracket")
    ap.add_argument("--once", action="store_true", help="one decision pass at the latest completed bar")
    ap.add_argument("--reports", action="store_true", help="(re)build reports/eod_report_<date>.html + performance_report.html")
    ap.add_argument("--date", default="", help="report date YYYY-MM-DD for --reports (default today)")
    ap.add_argument("--i-understand-live", action="store_true", help="required for a LIVE account")
    a = ap.parse_args()
    cfg = load_config(a.config)
    global STATE_FILE, LOG_DIR
    if cfg.get("state_file"):
        STATE_FILE = os.path.join(_APP_DIR, cfg["state_file"])
    if cfg.get("log_dir"):
        LOG_DIR = os.path.join(_APP_DIR, cfg["log_dir"])
    if a.check:
        return cmd_check(cfg)
    if a.reports:                                         # offline: no IB connection needed
        import scalping_v2_reports as RP
        day = datetime.strptime(a.date, "%Y-%m-%d").date() if a.date else now_et().date()
        e, p, rows = RP.build(_APP_DIR, float(cfg.get("account_size_usd", 150000)), day)
        print(f"EOD report : {e}\nPerformance: {p}\n{len(rows)} closed trades found in {_APP_DIR}")
        return
    bot = ScalpingV2Bot(cfg, allow_live=a.i_understand_live)
    try:
        bot.connect()
        if a.status:
            bot.cmd_status()
        elif a.test_orders:
            bot.cmd_test_orders(a.test_orders.upper())
        elif a.once:
            bot.day_init()
            n = now_et()
            bot.evaluate((n.hour * 60 + n.minute) // 5 * 5)
            bot.log_status()
        else:
            bot.run_loop()
    except KeyboardInterrupt:
        log("interrupted — shutting down (resting brackets stay on the server)")
    finally:
        bot.disconnect()


if __name__ == "__main__":
    main()
