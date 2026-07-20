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

Indicators live in the shared `Indicators/` package at `Trading Strategies/Indicators`
(resolved by walking up from this file to the ancestor that contains it, so the bot can sit at
any depth, e.g. `Indicator Strategies/supertrend/`; EVERY strategy family reuses them). They are
config-driven: this bot asks for a value by passing a symbol + timeframe + params, e.g.
`supertrend_value(symbol="SOXL", bar_size="15 mins", atr_period=10, multiplier=3.0, ...)`
and `dema_value(symbol=..., bar_size=..., period=200, ...)`. Here we pass the already-fetched
`bars=` so the Supertrend and DEMA indicators share a single IBKR historical pull per symbol.

Core entry gate (config `dema_filter`, enabled by default): BUY only when the Supertrend is
bullish AND price is above the DEMA (default 200) — longs only when close > DEMA, shorts only
when close < DEMA. The protective stop loss is the Supertrend line itself for that stock and
timeframe (the live 'sell' level), trailed as the Supertrend advances.

Optional stacked entry filters (all off by default, evaluated on the last completed bar on TOP
of the Supertrend signal + DEMA gate): `adx_filter` (trend STRENGTH: ADX>=threshold),
`rsi_filter` (MOMENTUM: LONG only when RSI>long_min, SHORT only when RSI<short_max — default
straddles the 50 midline), and `macd_filter` (MOMENTUM: LONG only when the MACD histogram>0,
SHORT only when <0). The RSI/MACD momentum filters must AGREE with the Supertrend direction and
filter out low-conviction flips — backtests show RSI>50/<50 improves win rate and drawdown on
30m/1h. A filter that can't be evaluated (too little history) blocks the entry.

REGIME-ADAPTIVE gate (`regime_filter`, off by default): classifies the tape TREND vs CHOP each
bar via the Choppiness Index + ADX with hysteresis, and adapts entries — a trend-follower earns
its edge in trends and bleeds in chop. When enabled it SUPERSEDES the always-on rsi/macd gates:
in a TREND regime it enters on the Supertrend signal (optionally requiring rsi+macd if
`trend_momentum`); in a CHOP regime it either stands aside (`chop_action:"stand_aside"`, default
— take no new entries, only manage/exit existing) or requires rsi+macd momentum agreement
(`"momentum"`). Backtests over full multi-regime history favour stand_aside (~halves drawdown,
beats always-on rsi+macd in 5/6 series). Exits/stops/flip-exits are never gated — only NEW entries.

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
import threading
from datetime import datetime
from zoneinfo import ZoneInfo

from ib_async import IB, Stock, Future, MarketOrder, StopOrder, LimitOrder, StopLimitOrder

# Shared indicator library at <Trading Strategies>/Indicators, reused by every strategy family.
# The bot may sit at any depth below <Trading Strategies> (e.g. Indicator Strategies/supertrend/),
# so walk UP from this file until we find the ancestor that contains the Indicators package and
# add it to sys.path. Keeps `from Indicators...` working from source regardless of nesting; when
# frozen the package is bundled into the exe (build passes --paths <root> / --collect-submodules).
_BOT_DIR = os.path.dirname(os.path.abspath(__file__))
_SHARED_ROOT = os.path.dirname(_BOT_DIR)          # default: parent (back-compat)
_d = _BOT_DIR
for _ in range(8):
    _d = os.path.dirname(_d)
    if not _d or _d == os.path.dirname(_d):       # reached filesystem root
        break
    if os.path.isdir(os.path.join(_d, "Indicators")):
        _SHARED_ROOT = _d
        break
for _p in (_SHARED_ROOT, _BOT_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from Indicators.trend.supertrend import supertrend_value  # noqa: E402
from Indicators.dema import dema_value                     # noqa: E402
from Indicators.trend.adx import adx_value                 # noqa: E402
from Indicators.trend.choppiness import choppiness_value   # noqa: E402
from Indicators.momentum.rsi import rsi_value              # noqa: E402
from Indicators.momentum.macd import macd_value            # noqa: E402

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
        self.name = str(cfg.get("name", cfg.get("account", "supertrend"))).strip() or "supertrend"
        self.safe_name = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in self.name)
        self.accounts = [str(a).strip() for a in cfg.get("accounts", []) if a is not None]
        self.default_account = str(cfg.get("default_account", "")).strip()
        self.account = str(cfg.get("account", "")).strip() or self.default_account
        if self.accounts:
            if self.account not in self.accounts:
                self.account = self.default_account if self.default_account in self.accounts else self.accounts[0]
        self.market_data_type = int(cfg.get("market_data_type", 3))

        # direction: long_only (default) | short_only | long_short
        d = str(cfg.get("direction", "long_only")).lower().strip()
        self.direction = d if d in ("long_only", "short_only", "long_short") else "long_only"
        self.allow_long = self.direction in ("long_only", "long_short")
        self.allow_short = self.direction in ("short_only", "long_short")

        self.symbols = [s.upper() for s in cfg.get("symbols", [])]
        # Instrument type: STK (default, equities on SMART) or FUT (CME/GLOBEX futures such as
        # MNQ/MES). Futures qualify to the nearest (front-month) expiry automatically, trade
        # their native ~24h session (no OVERNIGHT venue), and size by contract multiplier.
        self.sec_type = str(cfg.get("sec_type", "STK")).upper().strip() or "STK"
        self.is_future = self.sec_type in ("FUT", "FUTURE", "CONTFUT")
        self.exchange = str(cfg.get("exchange", "")).strip() or ("CME" if self.is_future else "SMART")
        self.currency = str(cfg.get("currency", "USD")).strip() or "USD"
        self.bar_size = cfg.get("bar_size", "15 mins")
        st = cfg.get("supertrend", {})
        self.atr_period = int(st.get("atr_period", 10))
        self.mult = float(st.get("multiplier", 3.0))
        # hist_duration is DERIVED below (after DEMA/ADX are known) unless explicitly configured.
        # market_hours: RTH (regular 09:30-16:00), ETH (extended 04:00-20:00), or 24H (all).
        # The Supertrend + DEMA are computed on the bars of the chosen session (RTH pulls RTH
        # only; ETH/24H pull all hours and ETH is then filtered to 04:00-20:00). ETH/24H also
        # flag orders/stops outsideRth so they can execute/trigger outside regular hours.
        mh = str(cfg.get("market_hours", "")).upper().strip()
        if mh not in ("RTH", "ETH", "24H"):
            mh = "RTH" if bool(cfg.get("use_rth", True)) else "ETH"   # back-compat from use_rth
        self.market_hours = mh
        self.use_rth = (mh == "RTH")
        self.outside_rth = (mh != "RTH")

        # Optional DEMA trend filter (Indicators/dema.py). When enabled, longs are only
        # taken when close > DEMA and shorts only when close < DEMA; otherwise the entry is
        # skipped. Computed on the same completed bar used for the Supertrend signal.
        dema_cfg = cfg.get("dema_filter", {})
        self.dema_enabled = bool(dema_cfg.get("enabled", False))
        self.dema_period = int(dema_cfg.get("period", 200))

        # Optional ADX trend-STRENGTH filter (Indicators/trend/adx.py). When enabled, an entry
        # is only taken when ADX(period) >= threshold on the last completed bar — i.e. the market
        # is trending strongly enough — on TOP of the Supertrend signal and the DEMA filter.
        # Two config forms (both optional):
        #   "adx_filter": { "enabled": true, "period": 14, "threshold": 20 }
        #   "adx": 20                      # shorthand -> enabled, threshold 20, period 14
        adx_cfg = cfg.get("adx_filter", {})
        if not isinstance(adx_cfg, dict):
            adx_cfg = {}
        adx_short = cfg.get("adx")
        self.adx_period = int(adx_cfg.get("period", 14))
        if adx_cfg:
            self.adx_enabled = bool(adx_cfg.get("enabled", False))
            self.adx_threshold = float(adx_cfg.get("threshold", adx_cfg.get("level", 20.0)))
        elif adx_short is not None:
            self.adx_threshold = float(adx_short)
            self.adx_enabled = self.adx_threshold > 0
        else:
            self.adx_enabled = False
            self.adx_threshold = 20.0

        # Optional RSI momentum filter (Indicators/momentum/rsi.py). Momentum must AGREE with
        # the Supertrend direction: a LONG is only taken when RSI(period) > long_min and a SHORT
        # only when RSI(period) < short_max, on the last completed bar — filtering out the
        # low-conviction flips that whipsaw the raw Supertrend. Defaults straddle the 50 midline.
        # Two config forms (both optional):
        #   "rsi_filter": { "enabled": true, "period": 14, "long_min": 50, "short_max": 50 }
        #   "rsi": 50                      # shorthand -> enabled, midline 50 (long>50 / short<50)
        rsi_cfg = cfg.get("rsi_filter", {})
        if not isinstance(rsi_cfg, dict):
            rsi_cfg = {}
        rsi_short = cfg.get("rsi")
        self.rsi_period = int(rsi_cfg.get("period", 14))
        if rsi_cfg:
            self.rsi_enabled = bool(rsi_cfg.get("enabled", False))
            self.rsi_long_min = float(rsi_cfg.get("long_min", rsi_cfg.get("midline", 50.0)))
            self.rsi_short_max = float(rsi_cfg.get("short_max", rsi_cfg.get("midline", 50.0)))
        elif rsi_short is not None:
            mid = float(rsi_short)
            self.rsi_enabled = True
            self.rsi_long_min = self.rsi_short_max = mid
        else:
            self.rsi_enabled = False
            self.rsi_long_min = self.rsi_short_max = 50.0

        # Optional MACD momentum filter (Indicators/momentum/macd.py). The MACD histogram sign
        # must AGREE with the Supertrend direction: a LONG is only taken when the histogram > 0
        # (macd line above signal) and a SHORT only when histogram < 0, on the last completed bar.
        #   "macd_filter": { "enabled": true, "fast": 12, "slow": 26, "signal": 9 }
        macd_cfg = cfg.get("macd_filter", {})
        if not isinstance(macd_cfg, dict):
            macd_cfg = {}
        self.macd_enabled = bool(macd_cfg.get("enabled", False))
        self.macd_fast = int(macd_cfg.get("fast", 12))
        self.macd_slow = int(macd_cfg.get("slow", 26))
        self.macd_signal = int(macd_cfg.get("signal", 9))

        # Optional REGIME FILTER (Indicators/trend/choppiness.py + adx.py). Classifies the tape as
        # TREND vs CHOP (Choppiness Index + ADX, with hysteresis) and adapts how entries are taken —
        # a trend-follower earns its edge in trends and bleeds in chop, so this gates WHEN/HOW it
        # trades. When enabled it SUPERSEDES the always-on rsi/macd gates and applies momentum by
        # regime instead. Hysteresis: flip to TREND when CHOP < chop_trend AND ADX > adx_trend; flip
        # to CHOP when CHOP > chop_range; otherwise hold the current regime (no flip-flop at the edge).
        #   TREND regime: enter on the Supertrend signal; require rsi+macd momentum only if trend_momentum.
        #   CHOP  regime: chop_action = "stand_aside" (default -> take NO new entries, only manage/exit
        #                 existing) OR "momentum" (require rsi+macd momentum agreement to enter).
        # Backtests (MNQ/MES, full multi-regime history) favour "stand_aside": ~halves drawdown and
        # beats the always-on rsi+macd config in 5/6 series. Config:
        #   "regime_filter": { "enabled": true, "adx_period": 14, "chop_period": 14,
        #                       "adx_trend": 25, "chop_trend": 38, "chop_range": 61,
        #                       "chop_action": "stand_aside", "trend_momentum": false }
        rgm = cfg.get("regime_filter", {})
        if not isinstance(rgm, dict):
            rgm = {}
        self.regime_enabled = bool(rgm.get("enabled", False))
        self.regime_adx_period = int(rgm.get("adx_period", 14))
        self.regime_chop_period = int(rgm.get("chop_period", 14))
        self.regime_adx_trend = float(rgm.get("adx_trend", 25.0))
        self.regime_chop_trend = float(rgm.get("chop_trend", 38.0))
        self.regime_chop_range = float(rgm.get("chop_range", 61.0))
        ca = str(rgm.get("chop_action", "stand_aside")).lower().strip()
        self.regime_chop_action = ca if ca in ("stand_aside", "momentum") else "stand_aside"
        self.regime_trend_momentum = bool(rgm.get("trend_momentum", False))
        self._regime: dict[str, str] = {}   # symbol -> "TREND"/"CHOP" (hysteresis state)

        self.intraday_mode = bool(cfg.get("intraday_mode", False))
        self.eod_flatten_time = cfg.get("eod_flatten_time", "15:55")
        # Entry window defaults to the market_hours session so a 24H/ETH strategy can actually
        # enter outside RTH (otherwise entries are silently blocked after 15:45). An explicit
        # entry_window in the config still overrides this.
        self.entry_window = cfg.get("entry_window") or {
            "RTH": ["09:35", "15:55"], "ETH": ["04:00", "20:00"], "24H": ["00:00", "23:59"],
        }[self.market_hours]
        self.entry_on_flip_only = bool(cfg.get("entry_on_flip_only", False))
        self.poll = int(cfg.get("poll_interval_sec", 30))

        s = cfg.get("sizing", {})
        self.strategy_capital = float(s.get("strategy_capital", 100000))
        self.fixed_stocks = int(s.get("fixed_stocks", 0))
        self.risk_pct = float(s.get("risk_per_trade_pct", 0.01))
        self.min_stop_pct = float(s.get("min_stop_pct", 0.005))
        self.max_notional = float(s.get("max_position_notional", 0) or 0)
        self.max_positions = int(cfg.get("max_concurrent_positions", len(self.symbols) or 1))
        self.entry_offset_pct = float(cfg.get("entry_offset_pct", 0.0005))   # initial marketable buffer
        self.entry_timeout_sec = int(cfg.get("entry_timeout_sec", 60))
        # ETH/24H marketable-limit walk: TOTAL time (default 60s) to keep ONE order working for
        # the WHOLE quantity to fill, spread across the chase levels. A large order (e.g. 1500
        # shares in thin extended/overnight liquidity) gets a full minute to complete instead of
        # being cut off after a few seconds with a partial fill.
        self.entry_fill_wait_sec = int(cfg.get("entry_fill_wait_sec", 60))
        # marketable-limit chase: if unfilled, bump the limit buffer up to max_chase_pct over
        # entry_chase_levels steps until it fills (works outside RTH where market orders reject).
        self.max_chase_pct = float(cfg.get("max_chase_pct", 0.005))
        self.entry_chase_levels = max(1, int(cfg.get("entry_chase_levels", 4)))
        # stop-LIMIT band: the limit sits this far the far side of the trigger so the stop is
        # marketable when hit (required outside RTH where stop-market orders reject).
        self.stop_limit_offset_pct = float(cfg.get("stop_limit_offset_pct", 0.003))

        self.rate = RateLimiter(float(cfg.get("hist_min_interval_sec", 2.0)))
        self.ib: IB | None = None
        self._conn_ok = True          # False between IB error 1100 (lost) and 1102 (restored)
        self._farm_wake_needed = False  # set on 1102 -> re-wake the data farm on next manage tick
        self._cycle_data_ok = False   # any symbol returned bars this poll cycle (watchdog input)
        self._data_fail = 0           # consecutive no-data poll cycles
        self.hist_timeout_sec = int(cfg.get("hist_timeout_sec", 20))
        # after this many consecutive no-data cycles WHILE the socket looks connected, force a
        # full session reset (disconnect -> fresh reconnect). Covers the case a competing login
        # steals the data line WITHOUT dropping the socket or sending 1100 (Error 162 timeouts),
        # which is exactly the "bot doesn't resume after phone interruption" symptom.
        self.data_fail_reconnect_cycles = int(cfg.get("data_fail_reconnect_cycles", 4))
        self.contracts: dict[str, object] = {}
        self._on_contracts: dict[str, object] = {}   # OVERNIGHT-venue contracts (24H), cached
        self.positions: dict[str, dict] = {}     # symbol -> live position state
        self._ticks: dict[str, float] = {}
        self._entry_bar: dict[str, object] = {}   # one entry per completed bar per symbol
        self._seen_bar: dict[str, object] = {}    # last completed bar time observed per symbol
        self._last_log_bar: dict[str, object] = {}   # last bar time we logged a status line for
        self._last_hb_time: dict[str, object] = {}   # last idle-heartbeat log time per symbol

        stamp = now_et().strftime("%Y%m%d")
        log_dir = os.path.join(self.base, cfg.get("log_dir", "logs"))
        os.makedirs(log_dir, exist_ok=True)
        self._log_path = os.path.join(log_dir, f"supertrend_{self.safe_name}_{stamp}.log")
        # per-strategy trade CSV: insert this strategy's safe_name so concurrent multi-account
        # threads never append to (and corrupt) the SAME file. The configured trade_log_csv is
        # treated as a BASE name; e.g. "supertrend_trades.csv" -> "supertrend_trades_<name>.csv".
        _csv_base, _csv_ext = os.path.splitext(cfg.get("trade_log_csv", "supertrend_trades.csv"))
        self._csv_path = os.path.join(self.base, f"{_csv_base}_{self.safe_name}{_csv_ext or '.csv'}")

        # hist_duration: use the configured value, else DERIVE one that covers the indicators'
        # warmup at this bar size (so it need not be configured — e.g. 15-min + DEMA(200) -> ~30D).
        self.hist_duration = cfg.get("hist_duration") or self._derive_hist_duration()
        # Then clamp to a safe max for the bar size. IBKR TIMES OUT on over-large small-bar
        # requests -- e.g. "30 D" of 1-min all-hours (ETH/24H) is tens of thousands of bars and
        # gets cancelled (Error 162).
        _bs = self._bar_seconds()
        _max_days = (10 if _bs <= 60 else 40 if _bs <= 300 else
                     90 if _bs < 3600 else 365 if _bs < 24 * 3600 else 3650)
        _req_days = self._duration_days(self.hist_duration)
        if _req_days is not None and _req_days > _max_days:
            self.log(f"hist_duration '{self.hist_duration}' too large for {self.bar_size} bars "
                     f"(IBKR would time out); capping to {_max_days} D")
            self.hist_duration = f"{_max_days} D"

    @staticmethod
    def _duration_days(dur) -> float | None:
        """Parse an IBKR duration string ('30 D', '2 W', '1 M', '1 Y', '3600 S') to days."""
        try:
            n, u = str(dur).strip().split()
            return float(n) * {"S": 1 / 86400.0, "D": 1.0, "W": 7.0,
                               "M": 30.0, "Y": 365.0}.get(u.upper(), 1.0)
        except Exception:
            return None

    def _derive_hist_duration(self) -> str:
        """History window sized to comfortably cover the indicators' warmup — ~2x the largest
        lookback (DEMA / ADX / ATR) in bars — at this bar size, so hist_duration need not be
        configured. Uses a conservative RTH bars/day estimate (never under-fetches; ETH/24H
        have MORE bars/day so they're covered too) and pads a little. The caller clamps it to
        the per-bar-size max. Example: 15-min + DEMA(200) -> ~450 bars / ~26 RTH bars-per-day
        -> ~19-30 D."""
        bs = self._bar_seconds()
        needed = max(self.atr_period,
                     self.dema_period if self.dema_enabled else 0,
                     self.adx_period if self.adx_enabled else 0)
        target_bars = max(int(needed) * 2 + 100, 250)
        if bs >= 24 * 3600:                              # daily+ bars
            return f"{min(int(target_bars * 1.5), 3650)} D"
        bars_per_day = max(1.0, 6.5 * 3600 / bs)         # RTH hours (conservative)
        return f"{max(5, math.ceil(target_bars / bars_per_day) + 3)} D"

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
        header = ["time", "strategy", "account", "symbol", "side", "qty", "entry", "exit",
                  "stop", "pnl", "ret_pct", "reason", "hold"]
        row = {**row, "strategy": self.name, "account": self.account}
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
    def _wire_events(self):
        # errorEvent carries IB 1100/1101/1102 connectivity notices even while the local API
        # socket stays up (the usual "logged in elsewhere" case bumps the Gateway's UPSTREAM
        # link, not the socket). disconnectedEvent fires on a real socket drop.
        try:
            self.ib.errorEvent += self._on_error
        except Exception:
            pass
        try:
            self.ib.disconnectedEvent += self._on_disconnected
        except Exception:
            pass

    def _on_error(self, *args):
        code = args[1] if len(args) > 1 else None
        if code == 1100:                       # connectivity between IB and TWS/Gateway lost
            self._conn_ok = False
            self.log("IB error 1100: connectivity to IB LOST — data/orders will fail until restored")
        elif code in (1101, 1102):             # restored (1101 = with data loss, 1102 = maintained)
            self._conn_ok = True
            self._farm_wake_needed = True
            self.log(f"IB error {code}: connectivity RESTORED — resuming")

    def _on_disconnected(self):
        self.log("API socket disconnected — will reconnect on next tick")

    def _connect_once(self) -> bool:
        """(Re)open a FRESH IB client and connect. A new IB() per attempt is deliberate:
        reconnecting on the object whose socket was just dropped often fails with
        clientId-in-use / dead-transport errors, which is the reconnect-doesn't-work bug."""
        try:
            if self.ib is not None and self.ib.isConnected():
                self.ib.disconnect()
        except Exception:
            pass
        self.ib = IB()                          # fresh client, bound to this thread's loop
        self._wire_events()
        self.ib.connect(self.host, self.port, clientId=self.client_id, account=self.account or "")
        try:
            self.ib.reqMarketDataType(self.market_data_type)
        except Exception as e:
            self.log(f"reqMarketDataType failed (continuing): {e}")
        # Resolve the EFFECTIVE account to what this login actually manages. If the configured
        # account isn't managed (e.g. a live-account config pointed at the paper gateway, which
        # only manages DU672616) and there's exactly one managed account, adopt it. Otherwise
        # held_qty / stop filters / order routing all silently mismatch -> the bot reads held=0
        # (buys the full target instead of the shortfall) and can't find the stops to cancel.
        try:
            mgd = list(self.ib.managedAccounts() or [])
        except Exception:
            mgd = []
        if mgd and self.account not in mgd:
            if len(mgd) == 1:
                self.log(f"configured account '{self.account or '(none)'}' is not managed by this "
                         f"login; using the only managed account {mgd[0]}")
                self.account = mgd[0]
            else:
                self.log(f"WARNING: account '{self.account}' not in managed accounts {mgd}; "
                         f"held/stop reconciliation and orders will mismatch — fix the config account")
        try:
            self.ib.reqPositions()   # subscribe once so positions() cache stays populated
        except Exception:
            pass
        self._conn_ok = True
        return True

    def connect(self) -> bool:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self.ib = None
        try:
            self._connect_once()
            self.log(f"connected clientId={self.client_id} account={self.account} "
                     f"port={self.port} mktDataType={self.market_data_type}")
            return True
        except Exception as e:
            self.log(f"CONNECT FAILED: {e}")
            return False

    def _post_restore_wake(self):
        """After connectivity is restored (1102), the HMDS data farm often needs one throwaway
        request to wake; then re-adopt the live position/stop in case anything changed."""
        self._farm_wake_needed = False
        try:
            if self.contracts:
                self.hist(next(iter(self.contracts.values())))   # throwaway pull to wake HMDS
            self.sync_existing()
            self.log("connectivity restored: data farm re-woken and state re-synced")
        except Exception as e:
            self.log(f"post-restore wake error: {e}")

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
            # Socket is up. If IB signalled 1100 (connectivity lost) and hasn't restored yet,
            # the link is unusable even though the socket is alive -> WAIT for 1102 rather than
            # tearing down a healthy socket (a competing login bumps the Gateway's UPSTREAM,
            # not our socket). Never return False here in swing mode (that would exit the bot);
            # only intraday-past-EOD returns False (handled by the caller as a clean stop).
            if not self._conn_ok:
                self.log("IB connectivity lost (1100); socket alive, waiting for restore (1102)...")
                while self.ib.isConnected() and not self._conn_ok:
                    if self.intraday_mode and now_et() >= at_et(self.eod_flatten_time):
                        return False
                    self.ib.sleep(2)          # let errorEvent(1102) fire
                if not self.ib.isConnected():
                    pass                       # socket dropped during blackout -> reconnect below
                else:
                    self._post_restore_wake()
                    return True
            elif self._farm_wake_needed:
                self._post_restore_wake()
            if self.ib.isConnected():
                return True
        steady = int(self.cfg.get("reconnect_backoff_sec", 60))
        flat_dt = at_et(self.eod_flatten_time)
        self.log(f"socket down (TWS/IBKR app may have bumped the session); retrying "
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
                self._connect_once()          # FRESH IB() each attempt (see _connect_once)
                self.log(f"reconnected (attempt {attempt})")
                try:
                    self.contracts = {s: self.qualify(s) for s in self.symbols}  # rebind on fresh client
                    self.sync_existing()       # re-adopt live position + stop; refresh stale Trades
                except Exception as e:
                    self.log(f"post-reconnect sync_existing error: {e}")
                return True
            except Exception as e:
                wait = 5 if attempt <= 3 else steady   # quick retries first, then ~every minute
                self.log(f"reconnect attempt {attempt} failed: {e}; retrying in {wait}s "
                         f"(is IB Gateway logged in? a competing login can log it OUT — "
                         f"enable Gateway auto-restart so it relogs in)")
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
        if self.is_future:
            return self._qualify_future(symbol)
        c = Stock(symbol, self.exchange or "SMART", self.currency or "USD")
        try:
            self.ib.qualifyContracts(c)
        except Exception as e:
            self.log(f"qualify error {symbol}: {e}")
        return c

    def _qualify_future(self, symbol: str):
        """Resolve a futures symbol (e.g. MNQ, MES) to the CLOSEST (front-month) live contract.
        Asks IBKR for every listed expiry on the exchange and picks the nearest one that has not
        yet expired, so specifying just "MNQ" auto-selects the front month. Caches the min tick
        from the same lookup (saves a reqContractDetails round-trip)."""
        exch = self.exchange or "CME"
        base = Future(symbol=symbol, exchange=exch, currency=self.currency or "USD")
        try:
            self.rate.acquire(self.ib)
            cds = list(self.ib.reqContractDetails(base) or [])
        except Exception as e:
            self.log(f"future lookup error {symbol} on {exch}: {e}")
            cds = []
        if not cds:
            self.log(f"no futures contracts found for {symbol} on {exch} — check symbol/exchange")
            return base
        today = now_et().strftime("%Y%m%d")

        def expkey(cd):
            e = str(getattr(cd.contract, "lastTradeDateOrContractMonth", "") or "")
            return e if len(e) >= 8 else (e + "31")[:8]   # month-only -> treat as month-end

        live = [cd for cd in cds if expkey(cd) >= today]      # not yet expired
        chosen = min(live or cds, key=expkey)                 # nearest expiry
        c = chosen.contract
        try:
            mt = float(getattr(chosen, "minTick", 0) or 0)
            if mt > 0:
                self._ticks[symbol] = mt
        except Exception:
            pass
        self.log(f"{symbol} front-month future: {getattr(c, 'localSymbol', '') or symbol} "
                 f"expiry {expkey(chosen)} on {c.exchange} x{getattr(c, 'multiplier', '?')} "
                 f"tick {self._ticks.get(symbol, '?')}")
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

    def _hist_one(self, contract):
        """Single reqHistoricalData pull (bounded timeout so a stall fails fast)."""
        self.rate.acquire(self.ib)
        try:
            return self.ib.reqHistoricalData(contract, "", self.hist_duration, self.bar_size,
                                             "TRADES", self.use_rth, 1,
                                             timeout=self.hist_timeout_sec) or []
        except Exception as e:
            self.log(f"hist error {getattr(contract, 'symbol', '?')}: {e}")
            return []

    def hist(self, contract):
        bars = self._hist_one(contract)
        # 24H: the SMART feed only covers 04:00-20:00; the IBKR OVERNIGHT venue carries the
        # 20:00-04:00 session. Merge both into one continuous series so the Supertrend/DEMA
        # (and logging) keep running overnight.
        if self.market_hours == "24H":
            onc = self._overnight_contract(contract)
            if onc is not None:
                bars = self._merge_bars(bars, self._hist_one(onc))
        bars = self._filter_session(bars)   # RTH/ETH filter; 24H = no filter (keep all)
        if bars:
            self._cycle_data_ok = True   # signal to the run-loop data watchdog
        return bars

    def _overnight_contract(self, contract):
        """A qualified OVERNIGHT-venue contract for `contract`'s symbol (cached). Used for both
        overnight history and overnight order routing. None if it can't be qualified. The
        OVERNIGHT venue is an EQUITIES venue — futures trade their own ~24h session, so this is
        never used for futures."""
        if self.is_future:
            return None
        sym = getattr(contract, "symbol", "")
        if sym not in self._on_contracts:
            oc = None
            try:
                oc = Stock(sym, "OVERNIGHT", "USD")
                self.ib.qualifyContracts(oc)
            except Exception as e:
                self.log(f"overnight contract unavailable for {sym}: {e}"); oc = None
            self._on_contracts[sym] = oc
        return self._on_contracts.get(sym)

    @staticmethod
    def _merge_bars(a, b):
        """Merge two bar lists into one time-sorted, de-duplicated (by bar time) series."""
        d = {}
        for bar in (a or []):
            d[bar.date] = bar
        for bar in (b or []):
            d[bar.date] = bar
        return [d[k] for k in sorted(d)]

    @staticmethod
    def _in_overnight():
        """True during the IBKR overnight window (~20:00-04:00 ET)."""
        m = now_et().hour * 60 + now_et().minute
        return m >= 20 * 60 or m < 4 * 60

    @staticmethod
    def _is_overnight(contract) -> bool:
        """True if `contract` is routed to the IBKR OVERNIGHT venue. That venue accepts ONLY
        LIMIT/Adaptive orders (no STP/STP LMT/MKT) and does NOT support GTC — so a native
        server-side protective stop cannot rest there; the bot uses a SYNTHETIC stop instead
        (monitor price each bar, fire a marketable LIMIT exit when the stop level is breached)."""
        return getattr(contract, "exchange", "") == "OVERNIGHT"

    def _order_contract(self, contract):
        """Route orders to the OVERNIGHT venue during the overnight window (24H only); SMART
        otherwise. Overnight orders must be placed on the OVERNIGHT contract."""
        if self.market_hours == "24H" and self._in_overnight():
            onc = self._overnight_contract(contract)
            if onc is not None:
                return onc
        return contract

    def _filter_session(self, bars):
        """Restrict intraday bars to the configured market_hours session so the Supertrend/DEMA
        are computed on those hours: RTH 09:30-16:00, ETH 04:00-20:00, 24H no filter. Daily+
        bars (no intraday time) pass through unchanged."""
        if self.market_hours == "24H" or not bars:
            return bars
        lo, hi = (9 * 60 + 30, 16 * 60) if self.market_hours == "RTH" else (4 * 60, 20 * 60)
        out = []
        for b in bars:
            t = getattr(b, "date", None)
            if t is None or not hasattr(t, "hour"):
                out.append(b); continue          # daily bar -> not session-filtered
            m = t.hour * 60 + t.minute
            if lo <= m < hi:
                out.append(b)
        return out

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

    def adx_filter_ok(self, symbol, bars, side) -> bool:
        """True if the ADX trend-strength filter permits an entry on `side` (or if it's
        disabled). Requires ADX(period) >= threshold on the last completed bar — the market is
        trending strongly enough. A missing ADX (not enough history) blocks the entry so we
        never trade a filter we cannot evaluate — widen hist_duration if you see this."""
        if not self.adx_enabled or side == FLAT:
            return True
        res = adx_value(symbol=symbol, bar_size=self.bar_size, period=self.adx_period,
                        trend_level=self.adx_threshold, bars=bars)
        if res is None:
            self.log(f"{symbol} ADX{self.adx_period} filter: insufficient bars "
                     f"(have {len(bars)}); blocking {side} entry — increase hist_duration")
            return False
        ok = res.value >= self.adx_threshold
        if not ok:
            self.log(f"{symbol} ADX{self.adx_period} filter blocks {side}: "
                     f"ADX {res.value:.1f} < {self.adx_threshold:.0f}")
        return ok

    def rsi_filter_ok(self, symbol, bars, side) -> bool:
        """True if the RSI momentum filter permits an entry on `side` (or if it's disabled).
        Momentum must agree with the Supertrend direction: LONG requires RSI(period) > long_min
        and SHORT requires RSI(period) < short_max on the last completed bar — filtering out the
        low-conviction flips that whipsaw the raw Supertrend. A missing RSI (not enough history)
        blocks the entry so we never trade a filter we cannot evaluate."""
        if not self.rsi_enabled or side == FLAT:
            return True
        res = rsi_value(symbol=symbol, bar_size=self.bar_size, period=self.rsi_period, bars=bars)
        if res is None:
            self.log(f"{symbol} RSI{self.rsi_period} filter: insufficient bars "
                     f"(have {len(bars)}); blocking {side} entry — increase hist_duration")
            return False
        ok = res.value > self.rsi_long_min if side == LONG else res.value < self.rsi_short_max
        if not ok:
            lvl = self.rsi_long_min if side == LONG else self.rsi_short_max
            rel = ">" if side == LONG else "<"
            self.log(f"{symbol} RSI{self.rsi_period} filter blocks {side}: "
                     f"RSI {res.value:.1f} not {rel} {lvl:.0f}")
        return ok

    def macd_filter_ok(self, symbol, bars, side) -> bool:
        """True if the MACD momentum filter permits an entry on `side` (or if it's disabled).
        The MACD histogram sign must agree with the Supertrend direction: LONG requires
        histogram > 0 (macd above signal) and SHORT requires histogram < 0, on the last
        completed bar. A missing MACD (not enough history) blocks the entry."""
        if not self.macd_enabled or side == FLAT:
            return True
        res = macd_value(symbol=symbol, bar_size=self.bar_size, fast=self.macd_fast,
                         slow=self.macd_slow, signal=self.macd_signal, bars=bars)
        if res is None:
            self.log(f"{symbol} MACD({self.macd_fast},{self.macd_slow},{self.macd_signal}) filter: "
                     f"insufficient bars (have {len(bars)}); blocking {side} entry")
            return False
        ok = res.hist > 0 if side == LONG else res.hist < 0
        if not ok:
            self.log(f"{symbol} MACD filter blocks {side}: hist {res.hist:+.3f} "
                     f"({'not >0' if side == LONG else 'not <0'})")
        return ok

    def current_regime(self, symbol, bars):
        """Classify TREND vs CHOP for `symbol` on the last completed bar via Choppiness Index +
        ADX, with HYSTERESIS (persisted per symbol in self._regime) so it doesn't flip-flop at
        the boundary: flip to TREND only when CHOP < chop_trend AND ADX > adx_trend; flip to CHOP
        only when CHOP > chop_range; otherwise hold the current regime. Returns
        (regime, chop_value, adx_value) where regime is 'TREND' or 'CHOP'; chop/adx may be None
        if there is not enough history (the regime then just holds its prior state)."""
        prev = self._regime.get(symbol, "CHOP")   # start conservative (assume chop until proven)
        cres = choppiness_value(symbol=symbol, bar_size=self.bar_size,
                                period=self.regime_chop_period, bars=bars)
        ares = adx_value(symbol=symbol, bar_size=self.bar_size, period=self.regime_adx_period,
                         trend_level=self.regime_adx_trend, bars=bars)
        chop = cres.value if cres else None
        adx = ares.value if ares else None
        regime = prev
        if chop is not None and adx is not None:
            if chop < self.regime_chop_trend and adx > self.regime_adx_trend:
                regime = "TREND"
            elif chop > self.regime_chop_range:
                regime = "CHOP"
        self._regime[symbol] = regime
        return regime, chop, adx

    def regime_gate_ok(self, symbol, bars, side) -> bool:
        """Regime-adaptive entry gate (only consulted when regime_filter is enabled; it then
        REPLACES the always-on rsi/macd gates). In a TREND regime, enter on the Supertrend signal
        (optionally requiring rsi+macd momentum if trend_momentum). In a CHOP regime, either stand
        aside (no new entries) or require rsi+macd momentum agreement, per chop_action."""
        if not self.regime_enabled or side == FLAT:
            return True
        regime, chop, adx = self.current_regime(symbol, bars)
        ctxt = f"CHOP {chop:.0f}" if chop is not None else "CHOP n/a"
        atxt = f"ADX {adx:.0f}" if adx is not None else "ADX n/a"
        if regime == "CHOP":
            if self.regime_chop_action == "stand_aside":
                self.log(f"{symbol} regime CHOP ({ctxt}/{atxt}) -> stand aside, no {side} entry")
                return False
            ok = self.rsi_filter_ok(symbol, bars, side) and self.macd_filter_ok(symbol, bars, side)
            if not ok:
                self.log(f"{symbol} regime CHOP ({ctxt}/{atxt}) -> momentum gate blocks {side}")
            return ok
        # TREND regime
        if self.regime_trend_momentum:
            return self.rsi_filter_ok(symbol, bars, side) and self.macd_filter_ok(symbol, bars, side)
        return True

    # ----------------------------------------------------------------- sizing
    def resolve_stop(self, side, entry, structural_stop):
        """Floor the stop distance to min_stop_pct so a too-tight Supertrend line can't
        blow up share count. Returns the WIDER stop on the correct side of entry."""
        if side == LONG:
            return min(structural_stop, entry * (1 - self.min_stop_pct))   # below entry
        return max(structural_stop, entry * (1 + self.min_stop_pct))       # above entry (short)

    @staticmethod
    def _contract_mult(contract) -> float:
        """Contract multiplier: 1 for equities, e.g. 2 for MNQ / 5 for MES. Notional and
        %-risk sizing scale by this ($ per point = price * multiplier)."""
        try:
            return float(getattr(contract, "multiplier", 1) or 1)
        except Exception:
            return 1.0

    def size_position(self, entry, stop, mult=1.0) -> int:
        """Desired TOTAL position size (a target, not a per-order size) in shares/contracts. In
        fixed_stocks mode the configured count is AUTHORITATIVE — the max_position_notional cap
        does NOT shrink it (that would silently defeat "hold exactly N"); we only warn if the
        target exceeds the cap. `mult` is the contract multiplier (1 for stocks, 2 for MNQ, 5
        for MES) so notional (price*mult*qty) and 1%-risk-at-stop sizing are correct for futures."""
        mult = float(mult or 1.0)
        if self.fixed_stocks > 0:
            notional = self.fixed_stocks * entry * mult
            if self.max_notional and notional > self.max_notional and entry > 0:
                self.log(f"WARNING: fixed_stocks {self.fixed_stocks} (~${notional:,.0f}) "
                         f"exceeds max_position_notional ${self.max_notional:,.0f} — honoring "
                         f"fixed_stocks. Raise/remove the cap or lower fixed_stocks if unintended.")
            return int(self.fixed_stocks)
        rps = abs(entry - stop) * mult                       # $ risk per contract at the stop
        if rps <= 0:
            return 0
        qty = math.floor((self.strategy_capital * self.risk_pct) / rps)
        if self.max_notional and qty * entry * mult > self.max_notional:
            qty = math.floor(self.max_notional / (entry * mult))
        return max(int(qty), 0)

    def held_qty(self, symbol) -> int:
        """Signed shares currently held for `symbol` on THIS account, from a LIVE snapshot
        (reqPositions blocks until positionEnd). Using reqPositions rather than the cached
        ib.positions() is essential right after a reconnect, when the cache hasn't repopulated
        yet -- reading it empty is what made the bot re-enter a fresh position every reconnect
        instead of topping up the one it already held."""
        try:
            poslist = self.ib.reqPositions()
        except Exception:
            poslist = self.ib.positions()
        return sum(int(p.position) for p in (poslist or [])
                   if getattr(p.contract, "symbol", "") == symbol
                   and (not self.account or getattr(p, "account", "") == self.account))

    def reconcile_stops(self, symbol, contract, side, total_qty, stop_trigger, tick):
        """Cancel EVERY resting protective stop for this symbol on this account, then place ONE
        consolidated stop covering the full position. Guarantees a single stop for the whole
        holding instead of a pile of per-entry stops."""
        stop_action = "SELL" if side == LONG else "BUY"
        try:
            self.ib.reqAllOpenOrders(); self.ib.sleep(1)
            for t in list(self.ib.openTrades()):
                o = getattr(t, "order", None)
                if (o is not None and getattr(t.contract, "symbol", "") == symbol
                        and getattr(o, "action", "") == stop_action
                        and getattr(o, "orderType", "") in ("STP", "STP LMT")
                        and (not self.account or getattr(o, "account", "") in ("", self.account))
                        and t.orderStatus.status not in ("Filled", "Cancelled", "ApiCancelled", "Inactive")):
                    self.cancel(t)
        except Exception as e:
            self.log(f"reconcile_stops cancel error: {e}")
        self.ib.sleep(1)
        if total_qty <= 0:
            return None
        trig = round_to_tick(stop_trigger, tick)
        if self._is_overnight(contract):
            # OVERNIGHT venue rejects stop orders (Error 387) and GTC — no native stop can rest
            # here. Return None so the caller stores a SYNTHETIC stop; manage_symbol enforces it
            # each bar (marketable LIMIT exit when price breaches `stop_trigger`).
            self.log(f"[{self._ref(symbol)}] OVERNIGHT venue (LMT-only): protecting "
                     f"{int(total_qty)} {symbol} with a SYNTHETIC stop @ {trig} (no native stop)")
            return None
        if self.outside_rth:
            # stop-LIMIT (stop-market is rejected outside RTH); limit sits the far side of the
            # trigger so it's marketable when hit.
            lim = round_to_tick(trig * (1 - self.stop_limit_offset_pct) if stop_action == "SELL"
                                else trig * (1 + self.stop_limit_offset_pct), tick)
            o = StopLimitOrder(stop_action, int(total_qty), lim, trig)
            desc = f"STP LMT {trig}/{lim}"
        else:
            o = StopOrder(stop_action, int(total_qty), trig)
            desc = f"STP {trig}"
        o.orderRef = self._ref(symbol)
        o.tif = "DAY" if self.intraday_mode else "GTC"
        o.outsideRth = self.outside_rth        # ETH/24H: let the stop trigger outside RTH
        if self.account:
            o.account = self.account
        st = self.ib.placeOrder(contract, o)
        self.log(f"[{self._ref(symbol)}] consolidated STOP {stop_action} {int(total_qty)} {symbol} @ {desc}")
        return st

    # ----------------------------------------------------------------- orders
    def _build_bracket(self, side, qty, entry_action, stop_action, limit_px, stop_trigger, ref, tick):
        """Build a parent entry + attached protective-stop child (transmit chained, so the stop
        is live the instant the entry fills). RTH: MARKET entry + stop-MARKET. ETH/24H: LIMIT
        entry + stop-LIMIT (market & stop-market are rejected outside regular hours)."""
        if self.outside_rth:
            parent = LimitOrder(entry_action, qty, round_to_tick(limit_px, tick))
            sl = round_to_tick(stop_trigger * (1 - self.stop_limit_offset_pct) if stop_action == "SELL"
                               else stop_trigger * (1 + self.stop_limit_offset_pct), tick)
            stop = StopLimitOrder(stop_action, qty, sl, round_to_tick(stop_trigger, tick))
        else:
            parent = MarketOrder(entry_action, qty)
            stop = StopOrder(stop_action, qty, round_to_tick(stop_trigger, tick))
        parent.orderId = self.ib.client.getReqId()
        parent.transmit = False
        parent.orderRef = ref
        parent.tif = "DAY"
        parent.outsideRth = self.outside_rth
        stop.orderId = self.ib.client.getReqId()
        stop.parentId = parent.orderId
        stop.transmit = True                       # transmits parent+stop atomically
        stop.orderRef = ref
        stop.tif = "DAY" if self.intraday_mode else "GTC"
        stop.outsideRth = self.outside_rth
        if self.account:
            parent.account = stop.account = self.account
        assert parent.action == entry_action and stop.action == stop_action, "side invariant"
        return parent, stop

    def _overnight_limit(self, action, qty, px, ref):
        """A standalone LIMIT for the OVERNIGHT venue (the only supported type there). No stop
        child — protection is synthetic. outsideRth is left False (it's ignored on OVERNIGHT
        and otherwise triggers warning 2109); tif DAY behaves as the overnight session order."""
        o = LimitOrder(action, qty, px)
        o.orderId = self.ib.client.getReqId()
        o.transmit = True
        o.orderRef = ref
        o.tif = "DAY"
        o.outsideRth = False
        if self.account:
            o.account = self.account
        return o

    def place_entry_with_stop(self, contract, side, qty, entry_ref, stop_trigger, ref, tick):
        """Enter + attach a protective stop, waiting for the fill. RTH uses a MARKET entry
        (immediate). ETH/24H uses a **marketable-LIMIT** entry that starts at
        entry_offset_pct beyond the reference price and **chases** up to max_chase_pct over
        entry_chase_levels steps until it fills (market orders are rejected outside RTH); the
        stop child is a stop-LIMIT. Returns (parent_trade, stop_trade)."""
        entry_ref = round_to_tick(entry_ref, tick)
        stop_trigger = round_to_tick(stop_trigger, tick)
        entry_action = "BUY" if side == LONG else "SELL"
        stop_action = "SELL" if side == LONG else "BUY"

        if not self.outside_rth:
            parent, stop = self._build_bracket(side, qty, entry_action, stop_action, None, stop_trigger, ref, tick)
            pt = self.ib.placeOrder(contract, parent)
            st = self.ib.placeOrder(contract, stop)
            self.log(f"[{ref}] {entry_action} {qty} {contract.symbol} ({side}) MKT (~{entry_ref}) "
                     f"stop {stop_trigger} ({'GTC' if not self.intraday_mode else 'DAY'})")
            waited = 0
            while waited < self.entry_timeout_sec:
                self.ib.sleep(1); waited += 1
                if pt.orderStatus.status in ("Filled", "Cancelled", "ApiCancelled", "Inactive"):
                    break
            return pt, st

        # ETH/24H: marketable-limit walk. Off-RTH the stop child is a stop-LIMIT; on the
        # OVERNIGHT venue NO stop child is attached (that venue rejects stop orders) — the
        # position is protected by a SYNTHETIC stop enforced each bar in manage_symbol.
        #
        # ONE order is placed and its limit price is BUMPED up each buffer level (rather than
        # cancel+replace), so partial fills ACCUMULATE on the same order and pt.orderStatus
        # (filled / avgFillPrice) stays cumulative for the caller. The order is kept working for
        # a TOTAL of entry_fill_wait_sec (default 60s ≈ "wait 1 min for the whole qty to fill"),
        # split across the chase levels, and it NEVER bails early on a partial fill.
        overnight = self._is_overnight(contract)
        levels = self.entry_chase_levels
        off, chase = self.entry_offset_pct, max(self.max_chase_pct, self.entry_offset_pct)
        step = (chase - off) / max(1, levels - 1) if levels > 1 else 0.0
        per_level = max(2, int(self.entry_fill_wait_sec) // max(1, levels))
        px0 = round_to_tick(entry_ref * (1 + off) if side == LONG else entry_ref * (1 - off), tick)
        if overnight:
            parent = self._overnight_limit(entry_action, qty, px0, ref)
            stop = None
            pt = self.ib.placeOrder(contract, parent)
            st = None
        else:
            parent, stop = self._build_bracket(side, qty, entry_action, stop_action, px0, stop_trigger, ref, tick)
            pt = self.ib.placeOrder(contract, parent)
            st = self.ib.placeOrder(contract, stop)
        for i in range(levels):
            frac = min(off + step * i, chase)
            px = round_to_tick(entry_ref * (1 + frac) if side == LONG else entry_ref * (1 - frac), tick)
            if i > 0:                                  # bump the SAME order's limit price
                parent.lmtPrice = px
                parent.transmit = True
                pt = self.ib.placeOrder(contract, parent)
            if overnight:
                self.log(f"[{ref}] {entry_action} {qty} {contract.symbol} ({side}) OVERNIGHT LMT {px} "
                         f"(buffer {frac*100:.2f}%) synthetic-stop @ {stop_trigger}")
            else:
                self.log(f"[{ref}] {entry_action} {qty} {contract.symbol} ({side}) LMT {px} "
                         f"(buffer {frac*100:.2f}%) stop-lmt {round_to_tick(stop_trigger, tick)}")
            waited = 0
            while waited < per_level:                  # keep working; ~1 min total for whole qty
                self.ib.sleep(1); waited += 1
                if pt.orderStatus.status == "Filled":
                    return pt, st                      # entire quantity filled
                if pt.orderStatus.status in ("Cancelled", "ApiCancelled", "Inactive"):
                    break
        # exhausted all levels: keep whatever filled (cumulative on pt), cancel the balance
        filled = int(pt.orderStatus.filled or 0)
        self.cancel(pt)
        if filled <= 0:
            self.log(f"[{ref}] no fill within chase to {chase*100:.2f}% -> skipping this bar")
        else:
            self.log(f"[{ref}] chase to {chase*100:.2f}% filled {filled}/{qty}; "
                     f"cancelling unfilled balance and keeping the partial")
        return pt, st

    def modify_stop(self, contract, st_trade, new_trigger, qty, tick):
        o = st_trade.order
        o.totalQuantity = qty
        trig = round_to_tick(new_trigger, tick)
        o.auxPrice = trig
        # for a stop-LIMIT, move the limit with the trigger (keep it the far side so it stays
        # marketable when hit); otherwise a trailed stop-limit would leave a stale limit. NOTE:
        # test orderType ONLY — a plain STP order's lmtPrice defaults to UNSET_DOUBLE (a huge,
        # truthy value), so `or o.lmtPrice` would wrongly set a limit on a stop-MARKET order.
        if getattr(o, "orderType", "") == "STP LMT":
            o.lmtPrice = round_to_tick(trig * (1 - self.stop_limit_offset_pct) if o.action == "SELL"
                                       else trig * (1 + self.stop_limit_offset_pct), tick)
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

    @staticmethod
    def _flatten_complete(tr, qty) -> bool:
        """True only if a flatten order FULLY filled `qty` — so the caller closes state only on
        a real exit (an off-RTH marketable limit can under-fill in thin liquidity)."""
        return tr is not None and int(tr.orderStatus.filled or 0) >= int(qty)

    def _shrink_to_fill(self, p, tr):
        """A flatten that only partially filled -> reduce the tracked qty by what DID exit so the
        remaining (still-held) shares are retried on the next bar instead of being lost."""
        filled = int(tr.orderStatus.filled or 0) if tr else 0
        if filled > 0:
            p["qty"] = max(0, int(p["qty"]) - filled)
            self.log(f"[{p['ref']}] flatten partial {filled} filled -> remaining held {p['qty']}; retry next bar")

    def flatten(self, contract, side, qty, ref, wait_sec=20, ref_price=None):
        """Close a position (SELL a long / BUY to cover a short). RTH: a MARKET order (fills
        immediately). ETH/24H/OVERNIGHT: a marketable LIMIT priced THROUGH the market, whose
        price is ESCALATED (1x -> 2x -> 3x exit_offset_pct) on the SAME order until it fills,
        then any unfilled balance is cancelled (never leaves a stray working exit order). The
        caller must check the returned trade's `filled` vs qty and only treat the position as
        closed on a full fill — a partial/none means the position is still (partly) live."""
        if qty <= 0:
            return None
        action = "SELL" if side == LONG else "BUY"
        overnight = self._is_overnight(contract)   # OVERNIGHT venue: LIMIT only (no MKT)

        if not (self.outside_rth or overnight):
            o = MarketOrder(action, qty)
            o.orderRef = ref + "_FLAT"
            if self.account:
                o.account = self.account
            tr = self.ib.placeOrder(contract, o)
            self.log(f"[{ref}] FLATTEN MKT {action} {qty} {contract.symbol} ({side})")
            waited = 0
            while waited < wait_sec:
                self.ib.sleep(1); waited += 1
                if tr.orderStatus.status in ("Filled", "Cancelled", "ApiCancelled", "Inactive"):
                    break
            return tr

        # ETH/24H/OVERNIGHT: marketable LIMIT, escalated until filled
        if ref_price is None:
            try:
                ref_price = self.hist(contract)[-1].close
            except Exception:
                ref_price = None
        if not ref_price:
            self.log(f"[{ref}] cannot flatten off-RTH without a reference price -> retry next bar")
            return None
        tick = self.min_tick(getattr(contract, "symbol", ""), contract)
        base_off = float(self.cfg.get("exit_offset_pct", 0.01))
        o = LimitOrder(action, qty, round_to_tick(
            ref_price * (1 - base_off) if side == LONG else ref_price * (1 + base_off), tick))
        o.orderId = self.ib.client.getReqId()
        o.orderRef = ref + "_FLAT"
        o.tif = "DAY"
        o.transmit = True
        o.outsideRth = self.outside_rth and not overnight   # ignored on OVERNIGHT (warning 2109)
        if self.account:
            o.account = self.account
        tr = self.ib.placeOrder(contract, o)
        per = max(4, int(wait_sec) // 3)
        for i in range(3):                              # escalate 1x -> 2x -> 3x through market
            off = base_off * (i + 1)
            px = round_to_tick(ref_price * (1 - off) if side == LONG else ref_price * (1 + off), tick)
            if i > 0:
                o.lmtPrice = px; o.transmit = True
                tr = self.ib.placeOrder(contract, o)
            self.log(f"[{ref}] FLATTEN LMT {px} ({off*100:.1f}% through) {action} {qty} {contract.symbol} ({side})")
            waited = 0
            while waited < per:
                self.ib.sleep(1); waited += 1
                if tr.orderStatus.status == "Filled":
                    return tr
                if tr.orderStatus.status in ("Cancelled", "ApiCancelled", "Inactive"):
                    break
        filled = int(tr.orderStatus.filled or 0) if tr else 0
        if filled < qty:
            self.cancel(tr)   # don't leave a working exit order behind
            self.log(f"[{ref}] FLATTEN filled only {filled}/{qty} after escalation -> cancelled "
                     f"remainder; position still (partly) live, will retry next bar")
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
        target = self.size_position(entry_ref, stop, self._contract_mult(contract))   # desired TOTAL (not order size)
        if target <= 0:
            self.log(f"{symbol} skip: target qty 0 (stop too tight / capital too small)")
            return
        ref = self._ref(symbol)
        held = abs(self.held_qty(symbol))               # shares already held (live snapshot)
        oc = self._order_contract(contract)             # OVERNIGHT venue during overnight (24H)
        top_up = target - held
        if top_up <= 0:
            # already at/above target -> don't buy more; just consolidate the stop for the whole
            # position (this is also what stops the "re-enter a fresh position every reconnect").
            st = self.reconcile_stops(symbol, oc, side, held, stop, tick)
            prev = self.positions.get(symbol, {})
            self.positions[symbol] = {
                "contract": contract, "side": side, "qty": held,
                "entry": prev.get("entry", entry_ref), "stop": stop, "st": st, "ref": ref,
                "opened": prev.get("opened", now_et()),
            }
            self._entry_bar[symbol] = bar_time
            self.log(f"{symbol} already at target: held {held} >= target {target}; stop reconciled for {held}")
            return

        # buy only the SHORTFALL; place_entry_with_stop waits/chases and protects the new
        # shares (atomic stop child) — RTH: market+stop-market, ETH/24H: marketable-limit walk
        # + stop-limit. Routed to the OVERNIGHT venue during the overnight window.
        pt, st_child = self.place_entry_with_stop(oc, side, top_up, entry_ref, stop, ref, tick)
        filled = int(pt.orderStatus.filled or 0) if pt else 0
        if filled <= 0 and held <= 0:
            if st_child is not None:
                self.cancel(st_child)
            self.log(f"{symbol} top-up no fill (chased to max) and nothing held -> skip")
            return
        total = held + filled
        # ONE consolidated stop for the full position (cancels st_child + any prior/stacked stops)
        st = self.reconcile_stops(symbol, oc, side, total, stop, tick)
        fill = float(pt.orderStatus.avgFillPrice or entry_ref)
        self.positions[symbol] = {
            "contract": contract, "side": side, "qty": total, "entry": fill, "stop": stop,
            "st": st, "ref": ref, "opened": now_et(),
        }
        self._entry_bar[symbol] = bar_time     # one entry per completed bar
        verb = "OPENED" if held == 0 else "TOPPED UP"
        self.log(f"{verb} {side} {symbol}: held {held} + bought {filled} = {total} "
                 f"(target {target}) entry {fill:.2f} stop {stop:.2f} for {total}")

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
            acct = self.account
            # LIVE snapshot via reqPositions (blocks until positionEnd). The cached ib.positions()
            # is often EMPTY right after a reconnect -> reading it empty is what made the bot fail
            # to adopt and instead re-enter a fresh position every reconnect. Scope to THIS
            # account: an FA/advisor login returns every sub-account's positions.
            poslist = self.ib.reqPositions() or []
            held = {p.contract.symbol: p for p in poslist
                    if p.position and (not acct or getattr(p, "account", "") == acct)}
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
            oc = self._order_contract(contract)          # active venue (OVERNIGHT during 20-04)
            tick = self.min_tick(symbol, contract)
            mult = int(getattr(contract, "multiplier", 1) or 1)
            entry = float(pos.avgCost or 0) / (mult or 1)
            ref = self._ref(symbol)

            # recompute the Supertrend for this stock + timeframe at startup
            state = self.st_state(symbol, self.hist(contract))
            bull = state[0] if state else None
            line = state[2] if state else None
            close = state[3] if state else entry

            # if the Supertrend has already flipped against the held side -> cancel ALL stops
            # and flatten now (the Supertrend 'sell' level is hit).
            if state is not None and self.desired_side(bull) != side:
                self.reconcile_stops(symbol, oc, side, 0, entry, tick)   # cancel all stops
                tr = self.flatten(oc, side, qty, ref, ref_price=close)
                exit_px = (float(tr.orderStatus.avgFillPrice)
                           if (tr and tr.orderStatus.avgFillPrice) else (line or entry))
                self.log(f"sync {symbol}: Supertrend flipped against {side} at startup "
                         f"-> exited {qty} @ {exit_px:.2f}")
                continue

            # current Supertrend stop level (clamped to the valid side of price)
            if line is not None:
                stop = self._st_stop(side, line, close, tick)
            else:
                floor = (1 - self.min_stop_pct) if side == LONG else (1 + self.min_stop_pct)
                stop = round_to_tick(entry * floor, tick)

            # top up to the TARGET total if under-sized (honors fixed_stocks as authoritative)
            target = self.size_position(entry, stop, self._contract_mult(contract))
            if target > qty:
                top_up_qty = target - qty
                self.log(f"sync {symbol}: under-sized {side} qty {qty} < target {target}; topping up {top_up_qty}")
                if self._is_overnight(oc):
                    # OVERNIGHT venue: market orders reject -> marketable-limit walk, no native stop
                    pt, _ = self.place_entry_with_stop(oc, side, top_up_qty, close, stop, ref, tick)
                    f = int(pt.orderStatus.filled or 0) if pt else 0
                    fp = float(pt.orderStatus.avgFillPrice or entry) if pt else entry
                else:
                    action = "BUY" if side == LONG else "SELL"
                    o = MarketOrder(action, top_up_qty)
                    o.orderRef = ref
                    o.outsideRth = self.outside_rth
                    if self.account:
                        o.account = self.account
                    tr = self.ib.placeOrder(contract, o)
                    waited = 0
                    while waited < self.entry_timeout_sec:
                        self.ib.sleep(1)
                        waited += 1
                        if tr.orderStatus.status in ("Filled", "Cancelled", "ApiCancelled", "Inactive"):
                            break
                    f = int(tr.orderStatus.filled or 0)
                    fp = float(tr.orderStatus.avgFillPrice or entry)
                if f > 0:
                    entry = ((entry * qty) + (fp * f)) / (qty + f) if qty else fp
                    qty += f
                    self.log(f"sync {symbol}: topped up {f} -> qty {qty} entry avg {entry:.2f}")
                else:
                    self.log(f"sync {symbol}: top-up {top_up_qty} no fill; keeping qty {qty}")

            # ONE consolidated stop for the full held quantity (cancels any stacked stops). On
            # the OVERNIGHT venue reconcile_stops returns None -> protection is synthetic.
            st_trade = self.reconcile_stops(symbol, oc, side, qty, stop, tick)
            self.positions[symbol] = {
                "contract": contract, "side": side, "qty": qty, "entry": entry, "stop": stop,
                "st": st_trade, "ref": ref, "opened": now_et(),
            }
            self.log(f"sync {symbol}: adopted {side} qty {qty} entry {entry:.2f} "
                     f"stop {stop:.2f} (single stop for {qty})")

    # ----------------------------------------------------------------- main loop
    def _trading_now(self) -> bool:
        """Weekly session guard. RTH/ETH equities trade Mon-Fri only. 24H equities (IBKR
        overnight) and futures (Globex) also trade the Sunday-evening -> Friday window, so they
        are NOT blocked on Sunday night. Closed Saturday and Sunday before the ~18:00 ET open."""
        now = now_et(); wd = now.weekday()          # Mon=0 .. Sat=5, Sun=6
        if not (self.is_future or self.market_hours == "24H"):
            return wd < 5                            # RTH/ETH: weekday only
        if wd == 5:                                  # Saturday: fully closed
            return False
        if wd == 6:                                  # Sunday: only the evening session onward
            return (now.hour * 60 + now.minute) >= 18 * 60
        return True                                  # Mon-Fri (venue handles the daily halt)

    def entries_allowed(self) -> bool:
        if not self._trading_now():
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
        oc = self._order_contract(p["contract"])
        # A synthetic stop (OVERNIGHT venue) has no resting order to modify — only its level is
        # trailed in state; manage_symbol enforces the level each bar with a marketable LIMIT.
        synth = p.get("st") is None
        tag = "Supertrend, synthetic" if synth else "Supertrend"
        if p["side"] == LONG:
            if new_stop > p["stop"] + tick / 2:
                if not synth:
                    self.modify_stop(oc, p["st"], new_stop, p["qty"], tick)
                self.log(f"{symbol} trail LONG stop -> {new_stop:.2f} ({tag})")
                p["stop"] = new_stop
        else:
            if new_stop < p["stop"] - tick / 2:
                if not synth:
                    self.modify_stop(oc, p["st"], new_stop, p["qty"], tick)
                self.log(f"{symbol} trail SHORT stop -> {new_stop:.2f} ({tag})")
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

        # ---- per-bar status line (console + log) so every bar is visible even with no action.
        # Logged once per NEW completed bar (bar_time), so it fires every bar (e.g. every 5 min
        # on 5-min bars) without spamming heartbeat/daily re-evals of the same bar.
        if self._last_log_bar.get(symbol) != bar_time:
            self._last_log_bar[symbol] = bar_time
            self._last_hb_time[symbol] = now_et()
            if self.dema_enabled:
                dres = dema_value(symbol=symbol, bar_size=self.bar_size,
                                  period=self.dema_period, bars=bars)
                dtxt = f"DEMA{self.dema_period} {dres.value:.2f}" if dres else f"DEMA{self.dema_period} n/a"
            else:
                dtxt = "DEMA off"
            if self.adx_enabled:
                ares = adx_value(symbol=symbol, bar_size=self.bar_size,
                                 period=self.adx_period, trend_level=self.adx_threshold, bars=bars)
                atxt = (f"ADX{self.adx_period} {ares.value:.1f}/{self.adx_threshold:.0f}"
                        if ares else f"ADX{self.adx_period} n/a")
            else:
                atxt = "ADX off"
            if self.rsi_enabled:
                rres = rsi_value(symbol=symbol, bar_size=self.bar_size, period=self.rsi_period, bars=bars)
                rtxt = f"RSI{self.rsi_period} {rres.value:.1f}" if rres else f"RSI{self.rsi_period} n/a"
            else:
                rtxt = "RSI off"
            if self.macd_enabled:
                mres = macd_value(symbol=symbol, bar_size=self.bar_size, fast=self.macd_fast,
                                  slow=self.macd_slow, signal=self.macd_signal, bars=bars)
                mtxt = f"MACD {mres.hist:+.2f}" if mres else "MACD n/a"
            else:
                mtxt = "MACD off"
            if self.regime_enabled:
                regime, chop, adx = self.current_regime(symbol, bars)
                gtxt = (f"REGIME {regime} (CHOP {chop:.0f}"
                        + (f"/ADX {adx:.0f}" if adx is not None else "") + ")") \
                    if chop is not None else f"REGIME {regime}"
            else:
                gtxt = "REGIME off"
            postxt = (f"pos {p['side']} {p['qty']}@{p['entry']:.2f} stop {p['stop']:.2f}"
                      if p else "flat")
            self.log(f"{symbol} [{self.market_hours}] bar {bar_time} "
                     f"ST({self.atr_period},{self.mult}) {'BULL' if bull else 'BEAR'} "
                     f"line {line:.2f} close {close:.2f} | {dtxt} | {atxt} | {rtxt} | {mtxt} | "
                     f"{gtxt} | desired {desired} | {postxt}")
        else:
            # No NEW bar (e.g. after 20:00 ET a stock stops printing extended-hours bars, or a
            # holiday) -> emit a low-frequency heartbeat so it's clear the bot is alive/idle
            # rather than dead. Throttled to idle_heartbeat_sec (default 300s).
            hb = int(self.cfg.get("idle_heartbeat_sec", 300))
            lasthb = self._last_hb_time.get(symbol)
            if lasthb is None or (now_et() - lasthb).total_seconds() >= hb:
                self._last_hb_time[symbol] = now_et()
                postxt = (f"pos {p['side']} {p['qty']}@{p['entry']:.2f} stop {p['stop']:.2f}"
                          if p else "flat")
                self.log(f"{symbol} [{self.market_hours}] idle — no new bar since {bar_time} "
                         f"(symbol not trading this session) | {postxt}")

        if p:
            oc = self._order_contract(contract)          # active venue (OVERNIGHT during 20-04)
            overnight = self._is_overnight(oc)
            last_px = bars[-1].close if bars else close   # most recent price for synthetic stop
            st = p.get("st")
            # 1) protective stop hit? EITHER a native server-side stop filled, OR (on the
            #    OVERNIGHT venue, which has no native stops) the SYNTHETIC stop level is breached
            #    -> flatten now with a marketable LIMIT. st is None whenever protection is synthetic.
            native_filled = st is not None and st.orderStatus.status == "Filled"
            synth_hit = st is None and (
                (p["side"] == LONG and last_px <= p["stop"]) or
                (p["side"] == SHORT and last_px >= p["stop"]))
            if native_filled or synth_hit:
                if native_filled:
                    self.close_position(symbol, float(st.orderStatus.avgFillPrice or p["stop"]), "STOP")
                    p = None
                else:
                    self.log(f"{symbol} SYNTHETIC stop hit: {p['side']} px {last_px:.2f} "
                             f"vs stop {p['stop']:.2f} -> flattening")
                    tr = self.flatten(oc, p["side"], p["qty"], p["ref"], ref_price=last_px)
                    if self._flatten_complete(tr, p["qty"]):
                        exit_px = float(tr.orderStatus.avgFillPrice or last_px)
                        self.close_position(symbol, exit_px, "STOP")
                        p = None
                    else:
                        self._shrink_to_fill(p, tr)   # keep the (partial) position; retry next bar
                        return
            # 2) signal changed -> exit (to cash) or prepare to reverse
            elif desired != p["side"]:
                self.cancel(st)
                tr = self.flatten(oc, p["side"], p["qty"], p["ref"], ref_price=last_px)
                if self._flatten_complete(tr, p["qty"]):
                    exit_px = float(tr.orderStatus.avgFillPrice) if (tr and tr.orderStatus.avgFillPrice) else last_px
                    self.close_position(symbol, exit_px, "FLIP")
                    p = None
                else:
                    # exit didn't fully fill -> stay in the (reduced) position, DON'T reverse yet
                    self._shrink_to_fill(p, tr)
                    return
            else:
                # 3) same side -> keep protection correct for the ACTIVE venue, then trail.
                #    OVERNIGHT: no native stop can rest (LMT-only) -> protection is synthetic
                #    (enforced above); if a native stop from the prior day session is still
                #    resting, cancel it (reconcile_stops(OVERNIGHT) drops it and returns None).
                #    Non-OVERNIGHT: a native stop must be live and on this venue; re-place it if
                #    it went inactive or the venue just switched (a native order can't be re-routed).
                if overnight:
                    if st is not None:
                        self.log(f"{symbol} entering OVERNIGHT -> switching to synthetic stop")
                        p["st"] = self.reconcile_stops(symbol, oc, p["side"], p["qty"], p["stop"], tick)
                else:
                    alive = st is not None and st.orderStatus.status in (
                        "PreSubmitted", "Submitted", "PendingSubmit", "ApiPending")
                    st_exch = getattr(getattr(st, "contract", None), "exchange", None)
                    same_venue = st_exch == getattr(oc, "exchange", None)
                    if not alive or not same_venue:
                        why = "not live" if not alive else f"venue switch -> {getattr(oc, 'exchange', '?')}"
                        self.log(f"{symbol} protective stop {why} -> re-placing")
                        p["st"] = self.reconcile_stops(symbol, oc, p["side"], p["qty"], p["stop"], tick)
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
        if not self.adx_filter_ok(symbol, bars, desired):
            return
        if self.regime_enabled:
            # regime gate supersedes the always-on momentum gates: it applies rsi/macd (or stands
            # aside) according to the TREND/CHOP classification instead of unconditionally.
            if not self.regime_gate_ok(symbol, bars, desired):
                return
        else:
            if not self.rsi_filter_ok(symbol, bars, desired):
                return
            if not self.macd_filter_ok(symbol, bars, desired):
                return
        self.open_position(symbol, desired, contract, line, close, tick, bar_time)

    def _bar_seconds(self) -> int:
        """The bar length in seconds, parsed from bar_size ('5 mins' -> 300)."""
        b = str(self.bar_size).lower().strip()
        try:
            n = int(b.split()[0])
        except Exception:
            return max(self.poll, 60)
        if "sec" in b:
            return max(n, 5)
        if "min" in b:
            return n * 60
        if "hour" in b:
            return n * 3600
        if "day" in b:
            return 24 * 3600
        if "week" in b:
            return 7 * 24 * 3600
        return max(self.poll, 60)

    def _watch_stops(self):
        """Cheap between-bars check (no history pull): catch a server-side stop that filled so
        the CSV/state update isn't delayed until the next bar evaluation."""
        for symbol in list(self.positions):
            p = self.positions.get(symbol)
            if p and p.get("st") is not None and p["st"].orderStatus.status == "Filled":
                exit_px = float(p["st"].orderStatus.avgFillPrice or p["stop"])
                self.close_position(symbol, exit_px, "STOP")

    def run(self):
        if not self.connect():
            return
        try:
            if not self._trading_now():
                self.log("market closed for this strategy's session (ET); exiting. "
                         "(24H/futures trade Sun evening–Fri; RTH/ETH Mon–Fri. No holiday calendar.)")
                return
            self.contracts = {s: self.qualify(s) for s in self.symbols}
            self.log(f"direction={self.direction} symbols={self.symbols} "
                     f"sec_type={self.sec_type}{'@' + self.exchange if self.is_future else ''} "
                     f"bar={self.bar_size} ST({self.atr_period},{self.mult}) "
                     f"DEMA={'on(' + str(self.dema_period) + ')' if self.dema_enabled else 'off'} "
                     f"ADX={'on(' + str(self.adx_period) + '>=' + str(int(self.adx_threshold)) + ')' if self.adx_enabled else 'off'} "
                     f"mode={'INTRADAY' if self.intraday_mode else 'SWING'} "
                     f"sizing={'fixed ' + str(self.fixed_stocks) if self.fixed_stocks else f'{self.risk_pct:.1%} risk'}")
            self.sync_existing()

            flat_dt = at_et(self.eod_flatten_time)
            bar_secs = self._bar_seconds()
            buf = int(self.cfg.get("bar_ready_buffer_sec", 5))   # wait a few s after close for data
            # Evaluate PRICE/signal once per bar (e.g. every 5 min for 5-min bars), aligned to
            # the bar close. Between bars we still wake every poll_interval_sec as a heartbeat to
            # check connectivity + catch a server-side stop fill. Per-bar gating only applies to
            # intraday bars longer than the heartbeat; daily+ bars evaluate each heartbeat and
            # let the fresh-bar gate handle once-per-bar action.
            gate = 0 < bar_secs < 24 * 3600 and bar_secs > self.poll
            self._last_eval_bar = None
            while True:
                if not self.ensure_connected():
                    self.log("CRITICAL: cannot reconnect; positions protected by server-side stops. Exiting.")
                    break
                if self.intraday_mode and now_et() >= flat_dt:
                    for symbol in list(self.positions):
                        p = self.positions[symbol]
                        self.cancel(p["st"])
                        tr = self.flatten(self._order_contract(p["contract"]), p["side"], p["qty"], p["ref"])
                        exit_px = (float(tr.orderStatus.avgFillPrice)
                                   if (tr and tr.orderStatus.avgFillPrice) else p["entry"])
                        self.close_position(symbol, exit_px, "EOD")
                    self.log("intraday EOD flatten complete; exiting for the day.")
                    break

                now = now_et()
                sod = now.hour * 3600 + now.minute * 60 + now.second
                if gate:
                    cur_bar = int((sod - buf) // bar_secs)   # bar considered closed & data-ready
                    do_eval = cur_bar != self._last_eval_bar
                    if do_eval:
                        self._last_eval_bar = cur_bar
                else:
                    do_eval = True

                if do_eval:
                    self._cycle_data_ok = False
                    for symbol in self.symbols:
                        try:
                            self.manage_symbol(symbol)
                        except Exception as e:
                            self.log(f"manage error {symbol}: {e}")
                    # DATA WATCHDOG: socket up but no symbol returned data for several bar-evals
                    # (a competing login stealing the data line sends Error 162 timeouts WITHOUT
                    # dropping the socket or firing 1100) -> force a full session reset.
                    if self._cycle_data_ok:
                        self._data_fail = 0
                    else:
                        self._data_fail += 1
                        if self._data_fail >= self.data_fail_reconnect_cycles:
                            self.log(f"no market data for {self._data_fail} evals while connected; "
                                     f"forcing session reset (disconnect -> reconnect)")
                            try:
                                self.ib.disconnect()
                            except Exception:
                                pass
                            self._data_fail = 0
                else:
                    self._watch_stops()      # heartbeat: catch a stop fill between bars

                # sleep to the next bar boundary, but wake at least every poll for health
                if gate:
                    to_next = int((sod - buf) // bar_secs + 1) * bar_secs + buf - sod
                    nap = max(2, min(self.poll, to_next))
                else:
                    nap = self.poll
                self.ib.sleep(nap)
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
    # utf-8-sig transparently strips a leading UTF-8 BOM if present (editors like Notepad or a
    # PowerShell `>` redirect add one), which plain utf-8 would choke on ("Unexpected UTF-8 BOM").
    with open(cfg_path, "r", encoding="utf-8-sig") as f:
        cfg = json.load(f)

    strategies = cfg.get("strategies")
    # `strategies` may be either a flat LIST (legacy) or an OBJECT with "stocks" and "futures"
    # sections. For the object form, futures strategies are tagged sec_type=FUT unless they
    # already set it, so a futures block only needs symbols/exchange (e.g. MNQ on CME).
    if isinstance(strategies, dict):
        stock_strats = list(strategies.get("stocks", []) or [])
        fut_strats = []
        for s in (strategies.get("futures", []) or []):
            s = {**s}
            s.setdefault("sec_type", "FUT")
            fut_strats.append(s)
        strategies = stock_strats + fut_strats
    if strategies:
        threads = []
        allowed_accounts = [str(a).strip() for a in cfg.get("accounts", []) if a is not None]
        default_account = str(cfg.get("default_account", "")).strip()
        client_id_base = int(cfg.get("client_id_base", cfg.get("client_id", 40)))
        for i, strat in enumerate(strategies):
            merged = {**cfg, **strat}
            merged.pop("strategies", None)
            merged["accounts"] = allowed_accounts
            merged["default_account"] = default_account
            # Per-strategy account (fall back to default)
            merged["account"] = str(merged.get("account", "")).strip() or default_account
            if allowed_accounts and merged["account"] and merged["account"] not in allowed_accounts:
                print(f"Skipping strategy {merged.get('name', merged['account'])}: invalid account {merged['account']}")
                continue
            # assign a unique client id for each thread: prefer per-strat override,
            # otherwise use client_id_base + index to ensure uniqueness across threads
            merged["client_id"] = int(strat.get("client_id", int(client_id_base) + int(i)))
            name = merged.get("name") or merged.get("account") or f"supertrend_{i}"
            print(f"Starting strategy {name} account={merged['account']} clientId={merged['client_id']}")
            thread = threading.Thread(target=lambda cfg=merged: SupertrendBot(cfg, base).run(),
                                       name=name, daemon=True)
            threads.append(thread)
            thread.start()
        for thread in threads:
            thread.join()
    else:
        SupertrendBot(cfg, base).run()


if __name__ == "__main__":
    main()
