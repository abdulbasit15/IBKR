"""Supertrend trading bot — IBKR / ib_async, config-driven, any stock / timeframe / config.

Go with the Supertrend on the chosen timeframe. The `direction` config decides which sides
are traded:

  * "long_only"  — long when Supertrend is bullish, CASH when bearish. Never shorts.
                   (e.g. "buy & hold SOXL, sell when bearish, re-buy when bullish".)
  * "short_only" — short when Supertrend is bearish, CASH when bullish. Never goes long.
  * "long_short" — always in the market: long when bullish, FLIP to short when bearish.

The protective stop is the Supertrend line itself (server-side; trails toward price as the
trend extends). A position is exited / reversed on the Supertrend flip. ST(period, mult)
e.g. ST(10,3) on 15-min bars — mirrors the long/cash model validated in the SOXL research.

Reuses the conventions of the sibling `Intraday Equity` bots: ib_async, own event loop,
config-driven (supertrend.json), rate-limited reqHistoricalData, acts on the LAST COMPLETED
bar (bars[-2]), atomic MARKET entry + server-side protective stop (parent transmit False ->
stop child True, so there is never an unprotected position), side-correct order asserts,
1%-risk-at-stop sizing with a min-stop floor (or fixed shares).

Indicators live in the shared `Indicators/` package one level up, at
`Trading Strategies/Indicators` (so EVERY strategy family can reuse them). They are
config-driven: this bot asks for a value by passing a symbol + timeframe + params, e.g.
`supertrend_value(symbol="SOXL", bar_size="15 mins", atr_period=10, multiplier=3.0, ...)`
and `dema_value(symbol=..., bar_size=..., period=200, ...)`. Here we pass the already-fetched
`bars=` so the Supertrend and DEMA indicators share a single IBKR historical pull per symbol.

Core entry gate (config `dema_filter`, enabled by default): BUY only when the Supertrend is
bullish AND price is above the DEMA (default 200) — longs only when close > DEMA, shorts only
when close < DEMA. The protective stop loss is the Supertrend line itself for that stock and
timeframe (the live 'sell' level), trailed as the Supertrend advances.

On startup the bot reconciles existing state: it checks current positions + open orders, and
for each held symbol recomputes the Supertrend and updates the resting stop to the current
Supertrend value (or flattens immediately if the Supertrend has already flipped against it).

Two holding modes (config `intraday_mode`):
  * false (default) = SWING: hold across days, stop is GTC, exit/reverse only on flip/stop.
  * true            = INTRADAY: flatten every position at `eod_flatten_time`, stop is DAY.

> PAPER-FIRST. Validate on paper before anything live; never point at a live account
> without LPL pre-clearance. Short modes also require shortable/borrowable shares + margin.

Run:  python supertrend_bot.py [supertrend.json]
"""
from __future__ import annotations

import asyncio
import csv
import json
import math
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from ib_async import IB, Stock, MarketOrder, StopOrder

# Shared indicator library at <Trading Strategies>/Indicators (one level ABOVE this bot's
# folder), so every strategy family reuses the same indicators. Adding that parent dir to
# sys.path keeps `from Indicators...` working from source; when frozen the package is bundled
# into the exe (the build passes --paths .. / --collect-submodules Indicators).
_BOT_DIR = os.path.dirname(os.path.abspath(__file__))
_SHARED_ROOT = os.path.dirname(_BOT_DIR)          # ...\Trading Strategies
for _p in (_SHARED_ROOT, _BOT_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from Indicators.trend.supertrend import supertrend_value  # noqa: E402
from Indicators.dema import dema_value                     # noqa: E402

ET = ZoneInfo("America/New_York")
LONG, SHORT, FLAT = "LONG", "SHORT", "FLAT"


# ───────────────────────── time helpers (ET) ─────────────────────────
def now_et() -> datetime:
    return datetime.now(ET)


def at_et(hhmm: str) -> datetime:
    h, m = (int(x) for x in hhmm.split(":"))
    return now_et().replace(hour=h, minute=m, second=0, microsecond=0)


def is_weekday() -> bool:
    return now_et().weekday() < 5


def round_to_tick(price: float, tick: float = 0.01) -> float:
    if not tick or tick <= 0:
        tick = 0.01
    return round(round(price / tick) * tick, 6)


# ───────────────────────── rate limiter ─────────────────────────
class RateLimiter:
    def __init__(self, min_interval=2.0):
        self.min_interval = float(min_interval)
        self._last = 0.0

    def acquire(self, ib: IB):
        import time as _t
        wait = self.min_interval - (_t.monotonic() - self._last)
        if wait > 0:
            try:
                ib.sleep(wait)
            except Exception:
                _t.sleep(wait)
        self._last = _t.monotonic()


# ───────────────────────── the bot ─────────────────────────
class SupertrendBot:
    def __init__(self, cfg: dict, base_dir: str):
        self.cfg = cfg
        self.base = base_dir
        self.host = cfg.get("host", "127.0.0.1")
        self.port = int(cfg.get("port", 4002))
        self.client_id = int(cfg.get("client_id", 40))
        self.account = cfg.get("account", "")
        self.market_data_type = int(cfg.get("market_data_type", 3))

        # direction: long_only (default) | short_only | long_short
        d = str(cfg.get("direction", "long_only")).lower().strip()
        self.direction = d if d in ("long_only", "short_only", "long_short") else "long_only"
        self.allow_long = self.direction in ("long_only", "long_short")
        self.allow_short = self.direction in ("short_only", "long_short")

        self.symbols = [s.upper() for s in cfg.get("symbols", [])]
        self.bar_size = cfg.get("bar_size", "15 mins")
        st = cfg.get("supertrend", {})
        self.atr_period = int(st.get("atr_period", 10))
        self.mult = float(st.get("multiplier", 3.0))
        self.hist_duration = cfg.get("hist_duration", self._default_duration(self.bar_size))
        self.use_rth = bool(cfg.get("use_rth", True))

        # Optional DEMA trend filter (Indicators/dema.py). When enabled, longs are only
        # taken when close > DEMA and shorts only when close < DEMA; otherwise the entry is
        # skipped. Computed on the same completed bar used for the Supertrend signal.
        dema_cfg = cfg.get("dema_filter", {})
        self.dema_enabled = bool(dema_cfg.get("enabled", False))
        self.dema_period = int(dema_cfg.get("period", 200))

        self.intraday_mode = bool(cfg.get("intraday_mode", False))
        self.eod_flatten_time = cfg.get("eod_flatten_time", "15:55")
        self.entry_window = cfg.get("entry_window", ["09:35", "15:45"])
        self.entry_on_flip_only = bool(cfg.get("entry_on_flip_only", False))
        self.poll = int(cfg.get("poll_interval_sec", 30))

        s = cfg.get("sizing", {})
        self.strategy_capital = float(s.get("strategy_capital", 100000))
        self.fixed_stocks = int(s.get("fixed_stocks", 0))
        self.risk_pct = float(s.get("risk_per_trade_pct", 0.01))
        self.min_stop_pct = float(s.get("min_stop_pct", 0.005))
        self.max_notional = float(s.get("max_position_notional", 0) or 0)
        self.max_positions = int(cfg.get("max_concurrent_positions", len(self.symbols) or 1))
        self.entry_offset_pct = float(cfg.get("entry_offset_pct", 0.0005))
        self.entry_timeout_sec = int(cfg.get("entry_timeout_sec", 60))

        self.rate = RateLimiter(float(cfg.get("hist_min_interval_sec", 2.0)))
        self.ib: IB | None = None
        self.contracts: dict[str, object] = {}
        self.positions: dict[str, dict] = {}     # symbol -> live position state
        self._ticks: dict[str, float] = {}
        self._entry_bar: dict[str, object] = {}   # one entry per completed bar per symbol
        self._seen_bar: dict[str, object] = {}    # last completed bar time observed per symbol

        stamp = now_et().strftime("%Y%m%d")
        log_dir = os.path.join(self.base, cfg.get("log_dir", "logs"))
        os.makedirs(log_dir, exist_ok=True)
        self._log_path = os.path.join(log_dir, f"supertrend_{stamp}.log")
        self._csv_path = os.path.join(self.base, cfg.get("trade_log_csv", "supertrend_trades.csv"))

    @staticmethod
    def _default_duration(bar_size: str) -> str:
        b = bar_size.lower()
        if "day" in b:
            return "1 Y"
        if "hour" in b:
            return "30 D"
        return "10 D"   # minute bars

    # ----------------------------------------------------------------- logging
    def log(self, msg: str):
        line = f"[{now_et().strftime('%Y-%m-%d %H:%M:%S')} ET] {msg}"
        print(line, flush=True)
        try:
            with open(self._log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass

    def record_trade(self, row: dict):
        header = ["time", "symbol", "side", "qty", "entry", "exit", "stop",
                  "pnl", "ret_pct", "reason", "hold"]
        new = not os.path.exists(self._csv_path)
        try:
            with open(self._csv_path, "a", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                if new:
                    w.writerow(header)
                w.writerow([row.get(h, "") for h in header])
        except OSError as e:
            self.log(f"trade-log write error: {e}")

    # ----------------------------------------------------------------- connect
    def connect(self) -> bool:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self.ib = IB()
        try:
            self.ib.connect(self.host, self.port, clientId=self.client_id, account=self.account or "")
            try:
                self.ib.reqMarketDataType(self.market_data_type)
            except Exception as e:
                self.log(f"reqMarketDataType failed (continuing): {e}")
            self.log(f"connected clientId={self.client_id} account={self.account} "
                     f"port={self.port} mktDataType={self.market_data_type}")
            return True
        except Exception as e:
            self.log(f"CONNECT FAILED: {e}")
            return False

    def ensure_connected(self) -> bool:
        """True if connected. If the socket dropped -- e.g. you logged into TWS or the IBKR
        app with the SAME account, which bumps the bot's API client -- keep retrying until
        reconnected: fast at first (the clientId usually frees within a few seconds of an
        app-bump), then settling to roughly every `reconnect_backoff_sec` (default 60s).
        In intraday mode it stops trying once past the EOD flatten time (nothing left to do
        today); in swing mode it retries indefinitely, since that loop has no daily exit. On
        a successful reconnect it re-runs sync_existing() to re-adopt the live server
        position + protective stop, so the stale in-memory Trade objects are refreshed."""
        if self.ib and self.ib.isConnected():
            return True
        steady = int(self.cfg.get("reconnect_backoff_sec", 60))
        flat_dt = at_et(self.eod_flatten_time)
        self.log(f"connection lost (TWS/IBKR app may have bumped the API client); retrying "
                 f"until reconnected{' or EOD' if self.intraday_mode else ''} -- fast, "
                 f"then every {steady}s...")
        attempt = 0
        while True:
            # intraday: give up once past EOD flatten (positions rest on server-side stops)
            if self.intraday_mode and now_et() >= flat_dt:
                self.log("reached EOD flatten time while still disconnected; stopping reconnect.")
                return False
            attempt += 1
            try:
                self.ib.connect(self.host, self.port, clientId=self.client_id, account=self.account or "")
                try:
                    self.ib.reqMarketDataType(self.market_data_type)
                except Exception:
                    pass
                self.log(f"reconnected (attempt {attempt})")
                try:
                    self.sync_existing()   # re-adopt live position + stop; refresh stale Trades
                except Exception as e:
                    self.log(f"post-reconnect sync_existing error: {e}")
                return True
            except Exception as e:
                wait = 5 if attempt <= 3 else steady   # quick retries first, then ~every minute
                self.log(f"reconnect attempt {attempt} failed: {e}; retrying in {wait}s")
                try:
                    self.ib.sleep(wait)
                except Exception:
                    import time as _t
                    _t.sleep(wait)

    def disconnect(self):
        try:
            if self.ib and self.ib.isConnected():
                self.ib.disconnect()
        except Exception:
            pass

    # ----------------------------------------------------------------- data
    def qualify(self, symbol: str):
        c = Stock(symbol, "SMART", "USD")
        try:
            self.ib.qualifyContracts(c)
        except Exception as e:
            self.log(f"qualify error {symbol}: {e}")
        return c

    def min_tick(self, symbol: str, contract) -> float:
        if symbol in self._ticks:
            return self._ticks[symbol]
        tick = 0.01
        try:
            self.rate.acquire(self.ib)
            cds = self.ib.reqContractDetails(contract)
            if cds and getattr(cds[0], "minTick", 0):
                tick = float(cds[0].minTick)
        except Exception:
            pass
        self._ticks[symbol] = tick
        return tick

    def hist(self, contract):
        self.rate.acquire(self.ib)
        try:
            return self.ib.reqHistoricalData(contract, "", self.hist_duration, self.bar_size,
                                             "TRADES", self.use_rth, 1) or []
        except Exception as e:
            self.log(f"hist error {getattr(contract, 'symbol', '?')}: {e}")
            return []

    def st_state(self, symbol, bars):
        """Supertrend on the last completed bar via the shared indicator, called with this
        bot's config (symbol/timeframe/atr params). Returns
        (bull_now, bull_prev, line_now, last_close, bar_time) or None. `bars` is the already
        fetched history, passed so the supertrend + DEMA indicators share one IBKR pull."""
        res = supertrend_value(symbol=symbol, bar_size=self.bar_size, bars=bars,
                               atr_period=self.atr_period, multiplier=self.mult)
        if res is None:
            return None
        return (res.bull, res.prev_bull, res.value, res.close, res.time)

    def dema_filter_ok(self, symbol, bars, side) -> bool:
        """True if the DEMA trend filter permits an entry on `side` (or if it's disabled).
        Calls the shared DEMA indicator with this bot's config (symbol/timeframe/period). A
        missing DEMA (not enough history) blocks the entry so we never trade a filter we
        cannot evaluate — widen hist_duration if you see this for a large dema period."""
        if not self.dema_enabled or side == FLAT:
            return True
        res = dema_value(symbol=symbol, bar_size=self.bar_size, period=self.dema_period, bars=bars)
        if res is None:
            self.log(f"{symbol} DEMA{self.dema_period} filter: insufficient bars "
                     f"(have {len(bars)}); blocking {side} entry — increase hist_duration")
            return False
        close, d = res.close, res.value
        ok = close > d if side == LONG else close < d
        if not ok:
            self.log(f"{symbol} DEMA{self.dema_period} filter blocks {side}: "
                     f"close {close:.2f} vs DEMA {d:.2f}")
        return ok

    # ----------------------------------------------------------------- sizing
    def resolve_stop(self, side, entry, structural_stop):
        """Floor the stop distance to min_stop_pct so a too-tight Supertrend line can't
        blow up share count. Returns the WIDER stop on the correct side of entry."""
        if side == LONG:
            return min(structural_stop, entry * (1 - self.min_stop_pct))   # below entry
        return max(structural_stop, entry * (1 + self.min_stop_pct))       # above entry (short)

    def size_position(self, entry, stop) -> int:
        rps = abs(entry - stop)
        if rps <= 0:
            return 0
        if self.fixed_stocks > 0:
            qty = self.fixed_stocks
        else:
            qty = math.floor((self.strategy_capital * self.risk_pct) / rps)
        if self.max_notional and qty * entry > self.max_notional:
            qty = math.floor(self.max_notional / entry)
        return max(int(qty), 0)

    # ----------------------------------------------------------------- orders
    def place_entry_with_stop(self, contract, side, qty, entry_ref, stop_trigger, ref, tick):
        """Enter with a MARKET order and attach the protective stop as a child. The parent
        (market) carries transmit=False and the stop child transmit=True, so both are sent
        together and the stop is server-side the instant the market entry fills — no naked
        position window. `entry_ref` is only the expected price (for logging/sizing)."""
        entry_ref = round_to_tick(entry_ref, tick)
        stop_trigger = round_to_tick(stop_trigger, tick)
        entry_action = "BUY" if side == LONG else "SELL"
        stop_action = "SELL" if side == LONG else "BUY"
        parent = MarketOrder(entry_action, qty)
        parent.orderId = self.ib.client.getReqId()
        parent.transmit = False
        parent.orderRef = ref
        parent.tif = "DAY"
        stop = StopOrder(stop_action, qty, stop_trigger)
        stop.orderId = self.ib.client.getReqId()
        stop.parentId = parent.orderId
        stop.transmit = True                       # transmits parent+stop atomically
        stop.orderRef = ref
        stop.tif = "DAY" if self.intraday_mode else "GTC"
        if self.account:
            parent.account = stop.account = self.account
        assert parent.action == entry_action and stop.action == stop_action, "side invariant"
        pt = self.ib.placeOrder(contract, parent)
        st = self.ib.placeOrder(contract, stop)
        self.log(f"[{ref}] {entry_action} {qty} {contract.symbol} ({side}) MKT (~{entry_ref}) "
                 f"stop {stop_trigger} ({'GTC' if not self.intraday_mode else 'DAY'})")
        return pt, st

    def modify_stop(self, contract, st_trade, new_trigger, qty, tick):
        o = st_trade.order
        o.totalQuantity = qty
        o.auxPrice = round_to_tick(new_trigger, tick)
        o.transmit = True
        try:
            return self.ib.placeOrder(contract, o)
        except Exception as e:
            self.log(f"modify_stop error: {e}")
            return st_trade

    def resize_stop(self, contract, st_trade, new_qty) -> bool:
        o = st_trade.order
        o.totalQuantity = new_qty
        o.transmit = True
        try:
            t2 = self.ib.placeOrder(contract, o)
            self.ib.sleep(1)
            if t2 and t2.orderStatus and t2.orderStatus.status in (
                    "Rejected", "Cancelled", "ApiCancelled", "Inactive"):
                return False
        except Exception as e:
            self.log(f"resize_stop error: {e}")
            return False
        return True

    def cancel(self, trade):
        try:
            if trade and trade.orderStatus.status not in (
                    "Filled", "Cancelled", "ApiCancelled", "PendingCancel", "Inactive"):
                self.ib.cancelOrder(trade.order)
        except Exception:
            pass

    def flatten(self, contract, side, qty, ref, wait_sec=20):
        """Close a position with a market order (BUY to cover a short, SELL to exit a long)."""
        if qty <= 0:
            return None
        action = "SELL" if side == LONG else "BUY"
        o = MarketOrder(action, qty)
        o.orderRef = ref + "_FLAT"
        if self.account:
            o.account = self.account
        tr = self.ib.placeOrder(contract, o)
        self.log(f"[{ref}] FLATTEN market {action} {qty} {contract.symbol} ({side})")
        waited = 0
        while waited < wait_sec:
            self.ib.sleep(1)
            waited += 1
            if tr.orderStatus.status in ("Filled", "Cancelled", "ApiCancelled", "Inactive"):
                break
        return tr

    # ----------------------------------------------------------------- entry / exit
    def _ref(self, symbol):
        return f"supertrend.{self.client_id}.{symbol}"

    def desired_side(self, bull: bool) -> str:
        if self.direction == "long_only":
            return LONG if bull else FLAT
        if self.direction == "short_only":
            return SHORT if not bull else FLAT
        return LONG if bull else SHORT          # long_short: always in the market

    def open_position(self, symbol, side, contract, st_line, work_price, tick, bar_time):
        # Market entry: work_price (last completed-bar close) is just the reference used to
        # derive the stop + size; the actual entry is at the market fill price.
        entry_ref = work_price
        if side == LONG:
            stop = self.resolve_stop(LONG, entry_ref, st_line)
            if stop >= entry_ref:
                self.log(f"{symbol} skip LONG: stop {stop:.2f} not below price {entry_ref:.2f}")
                return
        else:
            stop = self.resolve_stop(SHORT, entry_ref, st_line)
            if stop <= entry_ref:
                self.log(f"{symbol} skip SHORT: stop {stop:.2f} not above price {entry_ref:.2f}")
                return
        qty = self.size_position(entry_ref, stop)
        if qty <= 0:
            self.log(f"{symbol} skip: qty 0 (stop too tight / capital too small)")
            return
        ref = self._ref(symbol)
        pt, st = self.place_entry_with_stop(contract, side, qty, entry_ref, stop, ref, tick)

        waited = 0
        while waited < self.entry_timeout_sec:
            self.ib.sleep(1)
            waited += 1
            if pt.orderStatus.status == "Filled":
                break
            if pt.orderStatus.status in ("Cancelled", "ApiCancelled", "Inactive"):
                break
        filled = int(pt.orderStatus.filled or 0)
        if pt.orderStatus.status != "Filled":
            self.cancel(pt)
            self.ib.sleep(1)
            if filled > 0:
                if not self.resize_stop(contract, st, filled):
                    self.cancel(st)
                    self.ib.sleep(1)
                    self.flatten(contract, side, filled, ref)
                    self.log(f"{symbol} partial protection failed -> flattened {filled}")
                    return
            else:
                self.cancel(st)
                self.log(f"{symbol} no fill within {self.entry_timeout_sec}s -> skip")
                return
        qty_final = int(pt.orderStatus.filled or filled or qty)
        fill = float(pt.orderStatus.avgFillPrice or entry_ref)
        self.positions[symbol] = {
            "contract": contract, "side": side, "qty": qty_final, "entry": fill, "stop": stop,
            "st": st, "ref": ref, "opened": now_et(),
        }
        self._entry_bar[symbol] = bar_time     # one entry per completed bar
        self.log(f"OPENED {side} {symbol} qty {qty_final} entry {fill:.2f} stop {stop:.2f}")

    def close_position(self, symbol, exit_px, reason):
        p = self.positions.pop(symbol, None)
        if not p:
            return
        if p["side"] == LONG:
            pnl = (exit_px - p["entry"]) * p["qty"]
            ret = (exit_px / p["entry"] - 1) * 100 if p["entry"] else 0.0
        else:
            pnl = (p["entry"] - exit_px) * p["qty"]
            ret = (p["entry"] / exit_px - 1) * 100 if exit_px else 0.0
        hold = str(now_et() - p["opened"]).split(".")[0]
        self.record_trade({
            "time": now_et().strftime("%Y-%m-%d %H:%M:%S"), "symbol": symbol, "side": p["side"],
            "qty": p["qty"], "entry": round(p["entry"], 4), "exit": round(exit_px, 4),
            "stop": round(p["stop"], 4), "pnl": round(pnl, 2), "ret_pct": round(ret, 2),
            "reason": reason, "hold": hold,
        })
        self.log(f"CLOSED {p['side']} {symbol} {reason} exit {exit_px:.2f} pnl {pnl:.2f} ({ret:+.2f}%)")

    # ----------------------------------------------------------------- restart sync
    def sync_existing(self):
        """Startup reconciliation. Check existing positions + open orders for each configured
        symbol; recompute the Supertrend for its timeframe and bring the protective stop into
        line with the CURRENT Supertrend value (modifying a resting stop in place, or placing
        one if missing). If the Supertrend has already flipped against the position, flatten
        it immediately (the Supertrend 'sell' is the stop). Prevents double-trading and stops
        the bot from carrying a stale stop after a restart."""
        try:
            self.ib.reqAllOpenOrders()
            self.ib.sleep(1)
            open_trades = self.ib.openTrades()
            held = {p.contract.symbol: p for p in self.ib.positions() if p.position}
        except Exception as e:
            self.log(f"sync_existing error: {e}")
            return
        for symbol in self.symbols:
            pos = held.get(symbol)
            if not pos:
                continue
            side = LONG if pos.position > 0 else SHORT
            qty = abs(int(pos.position))
            contract = self.contracts[symbol]
            tick = self.min_tick(symbol, contract)
            mult = int(getattr(contract, "multiplier", 1) or 1)
            entry = float(pos.avgCost or 0) / (mult or 1)
            ref = self._ref(symbol)
            want_action = "SELL" if side == LONG else "BUY"
            # any protective stop already resting on the book for this symbol/side
            st_trade = None
            for t in open_trades:
                if (getattr(t.contract, "symbol", "") == symbol
                        and getattr(t.order, "action", "") == want_action
                        and getattr(t.order, "orderType", "") in ("STP", "STP LMT")):
                    st_trade = t
                    break

            # recompute the Supertrend for this stock + timeframe at startup
            state = self.st_state(symbol, self.hist(contract))
            bull = state[0] if state else None
            line = state[2] if state else None
            close = state[3] if state else entry

            # if the Supertrend has already flipped against the held side, the 'sell' level
            # is hit -> flatten now rather than carry a stale position/stop.
            if state is not None and self.desired_side(bull) != side:
                self.cancel(st_trade)
                tr = self.flatten(contract, side, qty, ref)
                exit_px = (float(tr.orderStatus.avgFillPrice)
                           if (tr and tr.orderStatus.avgFillPrice) else (line or entry))
                self.log(f"sync {symbol}: Supertrend flipped against {side} at startup "
                         f"-> exited {qty} @ {exit_px:.2f}")
                continue

            # otherwise set the stop to the CURRENT Supertrend line (clamped to a valid side)
            if line is not None:
                stop = self._st_stop(side, line, close, tick)
            elif st_trade is not None:
                stop = round_to_tick(float(st_trade.order.auxPrice), tick)   # no fresh ST -> keep
            else:
                floor = (1 - self.min_stop_pct) if side == LONG else (1 + self.min_stop_pct)
                stop = round_to_tick(entry * floor, tick)

            if st_trade is not None:
                old = float(st_trade.order.auxPrice)
                st_trade = self.modify_stop(contract, st_trade, stop, qty, tick)
                self.log(f"sync {symbol}: updated open stop {old:.2f} -> {stop:.2f} "
                         f"(Supertrend) on {side} {qty}")
            else:
                s = StopOrder(want_action, qty, stop)
                s.orderRef = ref
                s.tif = "DAY" if self.intraday_mode else "GTC"
                if self.account:
                    s.account = self.account
                st_trade = self.ib.placeOrder(contract, s)
                self.log(f"sync {symbol}: placed protective stop {stop:.2f} on adopted {side} {qty}")
            self.positions[symbol] = {
                "contract": contract, "side": side, "qty": qty, "entry": entry, "stop": stop,
                "st": st_trade, "ref": ref, "opened": now_et(),
            }
            self.log(f"sync {symbol}: adopted {side} qty {qty} entry {entry:.2f} stop {stop:.2f}")

    # ----------------------------------------------------------------- main loop
    def entries_allowed(self) -> bool:
        if not is_weekday():
            return False
        s, e = self.entry_window
        return at_et(s) <= now_et() <= at_et(e)

    def _st_stop(self, side, line, ref_price, tick):
        """The protective-stop price = the Supertrend line, clamped to the valid side of the
        reference price (a SELL stop must sit just below market, a BUY stop just above)."""
        if side == LONG:
            return min(round_to_tick(line, tick), round_to_tick(ref_price * (1 - 1e-4), tick))
        return max(round_to_tick(line, tick), round_to_tick(ref_price * (1 + 1e-4), tick))

    def _trail(self, symbol, p, line, close, tick):
        """Move the stop to the current Supertrend line (only ever in the favorable
        direction). The Supertrend line is the live 'sell' level, so the stop always tracks
        the Supertrend for this stock/timeframe (req: stop loss = Supertrend sell)."""
        new_stop = self._st_stop(p["side"], line, close, tick)
        if p["side"] == LONG:
            if new_stop > p["stop"] + tick / 2:
                self.modify_stop(p["contract"], p["st"], new_stop, p["qty"], tick)
                self.log(f"{symbol} trail LONG stop -> {new_stop:.2f} (Supertrend)")
                p["stop"] = new_stop
        else:
            if new_stop < p["stop"] - tick / 2:
                self.modify_stop(p["contract"], p["st"], new_stop, p["qty"], tick)
                self.log(f"{symbol} trail SHORT stop -> {new_stop:.2f} (Supertrend)")
                p["stop"] = new_stop

    def manage_symbol(self, symbol):
        contract = self.contracts[symbol]
        bars = self.hist(contract)
        state = self.st_state(symbol, bars)
        if state is None:
            return
        bull, bull_prev, line, close, bar_time = state
        # Track bar-close transitions on EVERY poll (even while holding), so an entry can only
        # fire at a new-bar-open boundary -- never in the middle of a bar (e.g. on a mid-bar
        # restart). Seeds silently on first sight: the first entry waits for the next close.
        prev_seen = self._seen_bar.get(symbol)
        self._seen_bar[symbol] = bar_time
        fresh_bar = prev_seen is not None and bar_time > prev_seen
        tick = self.min_tick(symbol, contract)
        desired = self.desired_side(bull)
        p = self.positions.get(symbol)

        if p:
            # 1) stopped out (server-side)?
            if p["st"] and p["st"].orderStatus.status == "Filled":
                exit_px = float(p["st"].orderStatus.avgFillPrice or p["stop"])
                self.close_position(symbol, exit_px, "STOP")
                p = None
            # 2) signal changed -> exit (to cash) or prepare to reverse
            elif desired != p["side"]:
                self.cancel(p["st"])
                tr = self.flatten(contract, p["side"], p["qty"], p["ref"])
                exit_px = float(tr.orderStatus.avgFillPrice) if (tr and tr.orderStatus.avgFillPrice) else close
                self.close_position(symbol, exit_px, "FLIP")
                p = None
            else:
                # 3) same side -> trail the stop toward the Supertrend line
                self._trail(symbol, p, line, close, tick)
                return

        # flat now -> consider opening the desired side
        if desired == FLAT:
            return
        if not self.entries_allowed():
            return
        if len(self.positions) >= self.max_positions:
            return
        if bar_time == self._entry_bar.get(symbol):   # already acted on this completed bar
            return
        if not fresh_bar:                              # only open at a new-bar-open boundary
            return
        if self.entry_on_flip_only:
            fresh = (bull and not bull_prev) if desired == LONG else ((not bull) and bull_prev)
            if not fresh:
                return
        if not self.dema_filter_ok(symbol, bars, desired):
            return
        self.open_position(symbol, desired, contract, line, close, tick, bar_time)

    def run(self):
        if not self.connect():
            return
        try:
            if not is_weekday():
                self.log("weekend (ET); exiting. (Holiday calendar not modelled — see README.)")
                return
            self.contracts = {s: self.qualify(s) for s in self.symbols}
            self.log(f"direction={self.direction} symbols={self.symbols} bar={self.bar_size} "
                     f"ST({self.atr_period},{self.mult}) "
                     f"DEMA={'on(' + str(self.dema_period) + ')' if self.dema_enabled else 'off'} "
                     f"mode={'INTRADAY' if self.intraday_mode else 'SWING'} "
                     f"sizing={'fixed ' + str(self.fixed_stocks) if self.fixed_stocks else f'{self.risk_pct:.1%} risk'}")
            self.sync_existing()

            flat_dt = at_et(self.eod_flatten_time)
            while True:
                if not self.ensure_connected():
                    self.log("CRITICAL: cannot reconnect; positions protected by server-side stops. Exiting.")
                    break
                if self.intraday_mode and now_et() >= flat_dt:
                    for symbol in list(self.positions):
                        p = self.positions[symbol]
                        self.cancel(p["st"])
                        tr = self.flatten(p["contract"], p["side"], p["qty"], p["ref"])
                        exit_px = (float(tr.orderStatus.avgFillPrice)
                                   if (tr and tr.orderStatus.avgFillPrice) else p["entry"])
                        self.close_position(symbol, exit_px, "EOD")
                    self.log("intraday EOD flatten complete; exiting for the day.")
                    break
                for symbol in self.symbols:
                    try:
                        self.manage_symbol(symbol)
                    except Exception as e:
                        self.log(f"manage error {symbol}: {e}")
                self.ib.sleep(self.poll)
        finally:
            self.disconnect()


def main():
    # When frozen by PyInstaller, __file__ lives in the temp _MEIxxxx extraction dir; the
    # config + logs + trade CSV must resolve next to the .exe instead. Matches runner.py.
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    cfg_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(base, "supertrend.json")
    if not os.path.isabs(cfg_path):
        cfg_path = os.path.join(base, cfg_path)
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    SupertrendBot(cfg, base).run()


if __name__ == "__main__":
    main()
