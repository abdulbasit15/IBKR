"""EquityStrategyBase - shared engine for the long-only intraday equity bots
(PDH Breakout, ORB Stocks-in-Play, Volume/Compression NR7).

Subclasses implement only:
    build_watchlist()                 -> list[str] of candidate symbols
    check_entry_signal(symbol, ctx)   -> Signal | None

Everything else (connection, ET-aware timing, 1% risk-at-stop sizing with a min-stop
floor, RVOL, VWAP, ATR/ADR, regime gate, native/stop-limit bracket placement, breakeven
+ trail management, a dedicated EOD-flatten check on every tick, journaling, and the
portfolio risk gate) lives here.

This is a PAPER-FIRST implementation. Single-target brackets with breakeven + trailing
stop are fully implemented; multi-tranche scale-out (PDH 2R/3R, ORB 1.5x/3x) is reserved
in config and is the documented next iteration (see README).
"""
from __future__ import annotations
import asyncio
import math
import os
import threading
from datetime import timedelta
from dataclasses import dataclass, field

from ib_async import IB, Stock, Index, ScannerSubscription, TagValue, StopOrder

import calendar_util as cal
import equity_order as eo


@dataclass
class Signal:
    entry: float                 # intended limit entry price
    stop: float                  # structural stop trigger (pre-floor)
    target: float                # take-profit price
    tick: float = 0.01
    use_stop_limit: bool = False         # True -> stop-LIMIT child (PDH, caps slippage)
    stop_limit_band: float = 0.002       # limit set this far below the (floored) stop trigger
    note: str = ""


@dataclass
class Position:
    order_ref: str
    symbol: str
    sector: str
    contract: object
    qty: int
    entry: float
    stop: float
    target: float
    r_unit: float
    pt: object
    tp: object
    st: object
    ticker: object = None
    breakeven_done: bool = False
    trail_active: bool = False
    high_water: float = 0.0


class EquityStrategyBase:
    strategy_type = "base"

    def __init__(self, name, cfg, shared, risk_mgr, log_fn, reporter=None):
        self.name = name
        self.cfg = cfg                      # per-strategy config block
        self.shared = shared                # shared_risk + host/port/account + helpers
        self.risk = risk_mgr                # per-strategy PortfolioRiskManager
        self._log = log_fn
        self.reporter = reporter            # per-strategy TradeReporter (analytics report)
        self.ib: IB | None = None
        self.account = shared.get("default_account")
        self.host = shared.get("host", "127.0.0.1")
        self.port = int(shared.get("port", 7497))
        self.client_id = int(cfg.get("client_id", 30))
        self.rate = shared["rate_limiter"]
        self.cache = shared["cache"]
        self.vol_scale = shared.get("vol_scale", 1)
        self.sector_map = shared.get("sector_map", {})
        sr = shared.get("shared_risk", {})
        self.risk_pct = float(cfg.get("risk_per_trade_pct", sr.get("risk_per_trade_pct", 0.01)))
        # per-strategy capital base (sizing uses THIS, not the account NetLiquidation)
        self.strategy_capital = float(cfg.get("strategy_capital", shared.get("start_equity", 0) or 0))
        self.fixed_stocks = int(cfg.get("fixed_stocks", 0))  # >0 -> fixed shares/ticker (ignores % risk)
        self.max_concurrent_tickers = int(cfg.get("max_concurrent_tickers",
                                          sr.get("max_concurrent_positions", 5)))
        self.min_stop_pct = float(cfg.get("min_stop_pct", sr.get("min_stop_pct", 0.003)))
        self.min_rr = float(cfg.get("min_rr", sr.get("min_rr", 1.5)))
        self.eod_flatten = sr.get("eod_flatten_time", cfg.get("eod_flatten_time", "15:55"))
        self.poll = int(cfg.get("poll_interval_sec", 5))
        # Configurable trade window(s): a list of [start, end] ET pairs in equity.json;
        # falls back to trade_start_time/trade_end_time (single window) for back-compat.
        w = cfg.get("windows")
        if not w:
            w = [[cfg.get("trade_start_time", cfg.get("entry_start", "09:35")),
                  cfg.get("trade_end_time", cfg.get("entry_end", "11:00"))]]
        self.windows = [[str(p[0]), str(p[1])] for p in w]
        self.window_start = min(p[0] for p in self.windows)
        self.window_end = max(p[1] for p in self.windows)
        self.positions: dict[str, Position] = {}
        self._md: dict[str, object] = {}   # base-owned market-data tickers (subscribe once, reuse)
        self._start_equity = float(shared.get("start_equity", 0) or 0)

    # ----------------------------------------------------------------- connect
    def connect(self) -> bool:
        # CRITICAL: every worker thread gets its OWN event loop BEFORE constructing IB()
        # (do not reuse ic.py's get_event_loop()-first pattern, which can grab the main
        # thread's loop). Never call util.startLoop() in a headless/threaded run.
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self.ib = IB()
        try:
            self.ib.connect(self.host, self.port, clientId=self.client_id, account=self.account or "")
            # 1=live, 2=frozen, 3=delayed, 4=delayed-frozen. Config-driven so an
            # unentitled paper account can still receive (delayed) data instead of NaNs.
            try:
                self.ib.reqMarketDataType(int(self.shared.get("market_data_type", 1)))
            except Exception as e:
                self.log(f"reqMarketDataType failed (continuing): {e}")
            try:
                self.ib.disconnectedEvent += self._on_disconnected
            except Exception:
                pass
            self.log(f"connected clientId={self.client_id} account={self.account} "
                     f"mktDataType={self.shared.get('market_data_type', 1)}")
            return True
        except Exception as e:
            self.log(f"CONNECT FAILED: {e}")
            return False

    def disconnect(self):
        try:
            if self.ib and self.ib.isConnected():
                self.ib.disconnect()
        except Exception:
            pass

    def _on_disconnected(self):
        self.log("WARNING: TWS/Gateway connection dropped")

    def ensure_connected(self):
        """True if connected. If the socket dropped -- e.g. you logged into TWS or the IBKR
        app with the SAME account, which bumps the bot's API client -- keep retrying until
        reconnected: fast at first (the clientId usually frees within a few seconds of an
        app-bump), then settling to roughly every `reconnect_backoff_sec` (default 60s). Never
        gives up before the EOD flatten time, so the bot survives an app-induced disconnect
        and resumes managing the open position instead of shutting down. On a successful
        reconnect, refresh server orders + market-data subscriptions so manage_open keeps
        tracking the LIVE OCA brackets rather than stale objects."""
        if self.ib and self.ib.isConnected():
            return True
        steady = int(self.shared.get("reconnect_backoff_sec", 60))
        flat_time = cal.effective_flatten_time(self.eod_flatten)
        self.log(f"connection lost (TWS/IBKR app may have bumped the API client); retrying "
                 f"until reconnected or EOD -- fast, then every {steady}s...")
        attempt = 0
        while cal.now_et() < flat_time:
            attempt += 1
            try:
                self.ib.connect(self.host, self.port, clientId=self.client_id, account=self.account or "")
                try:
                    self.ib.reqMarketDataType(int(self.shared.get("market_data_type", 1)))
                except Exception:
                    pass
                self.log(f"reconnected (attempt {attempt})")
                self._rebind_after_reconnect()
                return True
            except Exception as e:
                wait = 5 if attempt <= 3 else steady   # quick retries first, then ~every minute
                self.log(f"reconnect attempt {attempt} failed: {e}; retrying in {wait}s")
                try:
                    self.ib.sleep(wait)
                except Exception:
                    import time as _t
                    _t.sleep(wait)
        self.log("reached EOD flatten time while still disconnected; stopping reconnect.")
        return False

    def _rebind_after_reconnect(self):
        """Re-link our Position order legs to the refreshed server Trades (by orderId) and
        re-subscribe market data, since the prior session's Trade/Ticker objects are stale."""
        try:
            self.ib.reqAllOpenOrders()
            self.ib.sleep(1)
            open_by_id = {}
            for t in self.ib.openTrades():
                oid = getattr(getattr(t, "order", None), "orderId", None)
                if oid is not None:
                    open_by_id[oid] = t
            for p in self.positions.values():
                for attr in ("pt", "tp", "st"):
                    tr = getattr(p, attr, None)
                    oid = getattr(getattr(tr, "order", None), "orderId", None)
                    if oid in open_by_id:
                        setattr(p, attr, open_by_id[oid])
                self._md.pop(p.symbol, None)
                p.ticker = self.get_ticker(p.symbol, p.contract)
        except Exception as e:
            self.log(f"rebind after reconnect error: {e}")

    def adopt_existing_positions(self):
        """Startup reconciliation. Adopt any long position THIS strategy already has open on
        the server -- matched by the orderRef's `strategy_type` + `symbol` only (the client_id
        segment is IGNORED), so adoption survives a changed client_id_base or a reordered
        active_strategies list -- together with its resting take-profit + stop legs. A
        mid-session restart then keeps managing the LIVE bracket (breakeven / trail / EOD
        flatten) instead of ignoring the position or opening a duplicate on the same symbol.
        If a position is found with NO protective stop resting on the book, a fresh stop is
        placed at the floored min-stop level so it is never left naked. Registers with the
        risk manager so the entry loop won't re-open it. NOTE: matching on strategy_type alone
        means running two instances of the SAME strategy_type would cross-adopt; the runner
        gives each active strategy a distinct strategy_type, so this is safe here."""
        if not self.ib or not self.ib.isConnected():
            return
        try:
            self.ib.reqAllOpenOrders()
            self.ib.sleep(1)
            open_trades = list(self.ib.openTrades())
            held = [p for p in self.ib.positions() if p.position]
        except Exception as e:
            self.log(f"adopt_existing_positions error: {e}")
            return
        adopted = 0
        for pos in held:
            if pos.position <= 0:                    # long-only engine: ignore any short
                continue
            symbol = getattr(pos.contract, "symbol", None)
            if not symbol:
                continue
            ref = f"{self.strategy_type}.{self.client_id}.{symbol}"  # our in-memory key this run
            if ref in self.positions:                # already tracked in memory
                continue
            # match legs by strategy_type + symbol ONLY (ignore the client_id segment).
            # orderRef layout is "<strategy_type>.<client_id>.<symbol>" -> exactly 3 parts.
            legs = []
            for t in open_trades:
                parts = getattr(t.order, "orderRef", "").split(".")
                if (len(parts) == 3 and parts[0] == self.strategy_type
                        and parts[2] == symbol and getattr(t.order, "action", "") == "SELL"):
                    legs.append(t)
            if not legs:                             # not this strategy's (or bare) -> leave it
                continue
            tp = next((t for t in legs if t.order.orderType == "LMT"), None)
            st = next((t for t in legs if t.order.orderType in ("STP", "STP LMT")), None)
            contract = self.qualify(symbol)
            tick = self.min_tick(symbol, contract)
            mult = int(getattr(contract, "multiplier", 1) or 1)
            qty = int(abs(pos.position))
            entry = float(pos.avgCost or 0) / (mult or 1)
            if st is not None:
                stop = eo.round_to_tick(float(st.order.auxPrice), tick)
            else:
                # position with no resting stop -> protect it NOW at the floored min-stop level
                stop = eo.round_to_tick(entry * (1 - self.min_stop_pct), tick)
                so = StopOrder("SELL", qty, stop)
                so.orderRef = ref
                so.tif = "DAY"
                if self.account:
                    so.account = self.account
                try:
                    st = self.ib.placeOrder(contract, so)
                    self.log(f"adopt {symbol}: no resting stop found -> placed protective stop {stop}")
                except Exception as e:
                    self.log(f"adopt {symbol}: FAILED to place protective stop: {e}")
            target = eo.round_to_tick(float(tp.order.lmtPrice), tick) if tp is not None else entry
            r_unit = (entry - stop) if entry > stop else entry * self.min_stop_pct
            sector = self.sector_of(symbol, contract)
            tk = self.get_ticker(symbol, contract)
            self.positions[ref] = Position(ref, symbol, sector, contract, qty, entry, stop,
                                           target, r_unit, pt=st, tp=tp, st=st,
                                           ticker=tk, high_water=entry)
            self.risk.register_open(ref, symbol, sector, qty * r_unit, qty, entry, stop)
            adopted += 1
            self.log(f"ADOPTED {symbol} qty {qty} entry {entry:.2f} stop {stop:.2f} "
                     f"target {target if tp is not None else 'n/a'} "
                     f"(breakeven/trail/EOD will manage from here)")
        if adopted:
            self.log(f"startup reconciliation: adopted {adopted} existing position(s)")

    def log(self, msg):
        self._log(f"[{self.name}] {msg}")

    # ----------------------------------------------------------------- data
    def hist(self, contract, duration, bar_size, what="TRADES", use_rth=True):
        """Rate-limited reqHistoricalData wrapper."""
        self.rate.acquire()
        try:
            return self.ib.reqHistoricalData(contract, "", duration, bar_size, what, use_rth, 1) or []
        except Exception as e:
            self.log(f"hist error {getattr(contract,'symbol','?')}: {e}")
            return []

    def qualify(self, symbol):
        c = Stock(symbol, "SMART", "USD")
        try:
            self.ib.qualifyContracts(c)
        except Exception as e:
            self.log(f"qualify error {symbol}: {e}")
        return c

    def sector_of(self, symbol, contract):
        cached = self.cache.get(f"sector:{symbol}")
        if cached:
            return cached
        if symbol in self.sector_map:
            self.cache.put(f"sector:{symbol}", self.sector_map[symbol])
            return self.sector_map[symbol]
        sec = "UNKNOWN"
        try:
            self.rate.acquire()
            cds = self.ib.reqContractDetails(contract)
            if cds:
                sec = getattr(cds[0], "industry", None) or getattr(cds[0], "category", None) or "UNKNOWN"
        except Exception:
            pass
        self.cache.put(f"sector:{symbol}", sec)
        return sec

    def min_tick(self, symbol, contract):
        cached = self.cache.get(f"mintick:{symbol}")
        if cached:
            return cached
        tick = 0.01
        try:
            self.rate.acquire()
            cds = self.ib.reqContractDetails(contract)
            if cds and getattr(cds[0], "minTick", 0):
                tick = float(cds[0].minTick)
        except Exception:
            pass
        self.cache.put(f"mintick:{symbol}", tick)
        return tick

    def dollar_adv(self, symbol, contract, days=30):
        cached = self.cache.get(f"adv:{symbol}")
        if cached is not None:
            return cached
        bars = self.hist(contract, f"{days} D", "1 day", "TRADES", True)
        if not bars:
            self.cache.put(f"adv:{symbol}", 0)
            return 0
        vals = [float(b.volume) * self.vol_scale * float(b.close) for b in bars if b.volume and b.close]
        adv = sum(vals) / len(vals) if vals else 0
        self.cache.put(f"adv:{symbol}", adv)
        return adv

    def atr(self, contract, period=14, bar="1 day"):
        bars = self.hist(contract, f"{period + 6} D" if bar == "1 day" else "2 D", bar, "TRADES", True)
        if len(bars) < period + 1:
            return 0.0
        trs = []
        for i in range(1, len(bars)):
            h, l, pc = bars[i].high, bars[i].low, bars[i - 1].close
            trs.append(max(h - l, abs(h - pc), abs(l - pc)))
        window = trs[-period:]
        return sum(window) / len(window) if window else 0.0

    def adr_pct(self, contract, period=20):
        bars = self.hist(contract, f"{period + 4} D", "1 day", "TRADES", True)
        if len(bars) < period:
            return 0.0
        rngs = [(b.high - b.low) / b.close for b in bars[-period:] if b.close]
        return (sum(rngs) / len(rngs)) * 100 if rngs else 0.0

    def vwap(self, ticker):
        """Session VWAP from RTVolume tick 233 with a NaN guard. Returns None if not
        populated (delayed/frozen data) so callers can decide how to treat the gate."""
        v = getattr(ticker, "vwap", None)
        if v is None or (isinstance(v, float) and v != v) or v <= 0:
            return None
        return float(v)

    def session_vwap_from_bars(self, bars, end_idx=None):
        """Session VWAP = cumulative(typical_price * volume) / cumulative(volume) over the
        RTH session bars up to end_idx (default last). Computed FROM BARS so it works on
        delayed/unentitled data, where the RTVolume tick (ticker.vwap) is NaN. `bars` should
        be the current session's intraday bars (hist('1 D', ..., use_rth=True))."""
        if not bars:
            return None
        if end_idx is None:
            end_idx = len(bars) - 1
        pv = vv = 0.0
        for i in range(0, min(end_idx, len(bars) - 1) + 1):
            b = bars[i]
            vol = b.volume or 0
            pv += ((b.high + b.low + b.close) / 3.0) * vol
            vv += vol
        return (pv / vv) if vv > 0 else None

    def subscribe(self, contract):
        """reqMktData with RTVolume generic tick (233 -> ticker.vwap)."""
        try:
            return self.ib.reqMktData(contract, "233", False, False)
        except Exception as e:
            self.log(f"subscribe error: {e}")
            return None

    def get_ticker(self, symbol, contract):
        """Subscribe once per symbol and REUSE the same ticker everywhere (signals, VWAP,
        position management) so we never double-subscribe and a cancel can't kill another
        consumer's feed. All feeds are released together at disconnect()."""
        tk = self._md.get(symbol)
        if tk is None:
            tk = self.subscribe(contract)
            if tk is not None:
                self._md[symbol] = tk
        return tk

    def last_price(self, ticker):
        for attr in ("last", "marketPrice", "close"):
            v = getattr(ticker, attr, None)
            if callable(v):
                try:
                    v = v()
                except Exception:
                    v = None
            if v is not None and not (isinstance(v, float) and v != v) and v > 0:
                return float(v)
        return None

    # ----------------------------------------------------------------- scanner
    def scan(self, scan_code, tag_filters=None, rows=50, instrument="STK",
             location="STK.US.MAJOR", stock_type="ALL",
             above_price=None, below_price=None, above_volume=None):
        """One-shot IBKR market scanner snapshot -> list[str] of symbols (rate-limited,
        50-row capped). Price/volume bounds use the ScannerSubscription's BUILT-IN numeric
        fields (abovePrice/belowPrice/aboveVolume) which work WITHOUT a market-data
        subscription. The TagValue `tag_filters` (changePercAbove, avgVolumeAbove, ...) are
        OPTIONAL and require data entitlement -- they trigger error 162 otherwise -- so they
        default to none. Returns [] on error so callers fall back to the configured list."""
        try:
            sub = ScannerSubscription(instrument=instrument, locationCode=location,
                                      scanCode=scan_code, numberOfRows=min(int(rows), 50))
            if above_price is not None:
                sub.abovePrice = float(above_price)
            if below_price is not None:
                sub.belowPrice = float(below_price)
            if above_volume is not None:
                sub.aboveVolume = int(above_volume)
            if stock_type:
                try:
                    sub.stockTypeFilter = stock_type
                except Exception:
                    pass
            tvs = [TagValue(str(k), str(v)) for k, v in (tag_filters or {}).items()]
            self.rate.acquire()
            out = self.ib.reqScannerData(sub, [], tvs) or []
        except Exception as e:
            self.log(f"scan {scan_code} error: {e}")
            return []
        syms = []
        for r in out:
            try:
                syms.append(r.contractDetails.contract.symbol)
            except Exception:
                pass
        return syms

    def scanner_universe(self):
        """Resolve the candidate universe from cfg['scanner']; ALWAYS degrade to
        universe_symbols on empty/error so a missing data entitlement never zeroes the
        watchlist. Multiple scan_codes with intersect=true => names present in ALL scans."""
        sc = self.cfg.get("scanner", {})
        fixed = self.cfg.get("universe_symbols", [])
        if not sc.get("use_scanner"):
            return fixed
        codes = sc.get("scan_codes", [])
        sets = [self.scan(code, sc.get("tag_filters"), sc.get("scanner_rows", 50),
                          sc.get("instrument", "STK"), sc.get("location_code", "STK.US.MAJOR"),
                          sc.get("stock_type_filter", "ALL"),
                          sc.get("above_price"), sc.get("below_price"), sc.get("above_volume"))
                for code in codes]
        sets = [s for s in sets if s]
        if not sets:
            self.log("scanner returned nothing (entitlement/empty) -> using universe_symbols")
            return fixed if sc.get("fallback_to_universe", True) else []
        if sc.get("intersect") and len(sets) > 1:
            common = set(sets[0])
            for s in sets[1:]:
                common &= set(s)
            syms = [x for x in sets[0] if x in common]   # preserve first-scan ranking
        else:
            seen, syms = set(), []
            for s in sets:
                for x in s:
                    if x not in seen:
                        seen.add(x)
                        syms.append(x)
        if sc.get("mode") == "augment":
            for x in fixed:
                if x not in syms:
                    syms.append(x)
        if not syms and sc.get("fallback_to_universe", True):
            self.log("scanner intersect empty -> using universe_symbols")
            return fixed
        self.log(f"scanner universe ({len(syms)}): {syms[:25]}")
        return syms

    # ----------------------------------------------------------------- RVOL
    def rvol(self, contract, ref_dt, premarket=False):
        """Relative volume vs a 20-day same-time-of-day baseline. Uses ONLY completed
        bars up to ref_dt (no look-ahead). Cached per symbol per day."""
        sym = contract.symbol
        ckey = f"rvolbase:{'pm' if premarket else 'rth'}:{sym}:{ref_dt.strftime('%H%M')}"
        baseline = self.cache.get(ckey)
        days = int(self.cfg.get("rvol_lookback_days", self.cfg.get("min_baseline_days", 20)))
        use_rth = not premarket
        bars = self.hist(contract, f"{days + 5} D", "5 mins", "TRADES", use_rth)
        if not bars:
            return None
        # group bar volume by date, summing only bars up to ref clock time
        from collections import defaultdict
        by_day = defaultdict(float)
        ref_minute = ref_dt.hour * 60 + ref_dt.minute
        today_key = ref_dt.strftime("%Y%m%d")
        for b in bars:
            t = b.date if hasattr(b.date, "hour") else None
            if t is None:
                continue
            day = t.strftime("%Y%m%d")
            minute = t.hour * 60 + t.minute
            if premarket:
                if minute >= 9 * 60 + 30:   # only pre-market portion
                    continue
            if minute + 5 <= ref_minute:    # only FULLY-CLOSED 5-min buckets (skip forming bar)
                by_day[day] += float(b.volume) * self.vol_scale
        today_vol = by_day.pop(today_key, 0.0)
        prior = [v for d, v in by_day.items() if v > 0]
        baseline = sum(prior) / len(prior) if prior else 0.0
        if baseline <= 0:
            return None       # missing history -> caller decides (distinct from genuine 0.0)
        self.cache.put(ckey, baseline)
        return today_vol / baseline

    # ----------------------------------------------------------------- sizing
    def resolve_stop(self, entry, structural_stop):
        """Floor the stop distance to min_stop_pct so a too-tight structural stop (e.g.
        PDH-0.05%) can't blow up share count. Returns the WIDER (lower) of the two."""
        floor_stop = entry * (1 - self.min_stop_pct)
        return min(structural_stop, floor_stop)

    def size_position(self, entry, stop):
        rps = entry - stop
        if rps <= 0:
            return 0
        if self.fixed_stocks > 0:                 # fixed-share mode: ignore % risk entirely
            return self.fixed_stocks
        if rps < self.min_stop_pct * entry - 1e-9:
            return 0
        capital = self.strategy_capital or self._start_equity or self.get_equity()
        risk_dollars = capital * self.risk_pct    # 1% of the STRATEGY's capital
        shares = math.floor(risk_dollars / rps)
        cap = self.cfg.get("max_position_notional") or self.cfg.get("per_name_notional_cap")
        if cap and shares * entry > cap:
            shares = math.floor(cap / entry)
        return max(shares, 0)

    def get_equity(self):
        try:
            for v in self.ib.accountValues(self.account or ""):
                if v.tag == "NetLiquidation" and (not v.currency or v.currency == "USD"):
                    return float(v.value)
        except Exception as e:
            self.log(f"get_equity error: {e}")
        return 0.0

    # ----------------------------------------------------------------- regime
    def regime_ok(self):
        sr = self.shared.get("shared_risk", {}).get("regime", {})
        if not sr.get("spy_downtrend_gate", True):
            return True
        try:
            spy = self.shared.get("_spy") or self.qualify("SPY")
            self.shared["_spy"] = spy
            bars = self.hist(spy, "1 D", "5 mins", "TRADES", True)
            if bars:
                op = bars[0].open
                last = bars[-1].close
                if op and (last - op) / op < -abs(sr.get("spy_max_intraday_drop_pct", 0.005)):
                    return False
            # optional VIX band (delayed-data tolerant)
            if sr.get("vix_max"):
                vix = self.shared.get("_vix")
                if vix is None:
                    vix = Index("VIX", "CBOE")
                    try:
                        self.ib.qualifyContracts(vix)   # unqualified Index -> hist errors silently
                    except Exception:
                        pass
                    self.shared["_vix"] = vix
                vb = self.hist(vix, "1 D", "5 mins", "TRADES", True)
                if vb and vb[-1].close and vb[-1].close > float(sr["vix_max"]):
                    return False
        except Exception as e:
            self.log(f"regime check error (allowing): {e}")
        return True

    def is_new_bar(self, symbol, bars) -> bool:
        """Gate entries to the new-bar-OPEN boundary. `bars` is the intraday series; the
        signal bar is the last COMPLETED one (bars[-2]). Returns True only during the short
        window right AFTER that bar closes -- so an entry fires at the bar open, never deep
        inside a bar and never on a stale bar after a mid-bar (re)start. The bar length is
        inferred from the spacing to the forming bar (bars[-1]); the accept window is a
        couple of poll cycles. No per-bar dedup is needed: a re-entry after a fill is already
        blocked by the risk book's traded_today gate, and each poll re-checks the same fixed
        completed-bar signal, giving a few chances to clear a transient live-price gate."""
        if len(bars) < 2:
            return False
        bar = bars[-2]
        ts = getattr(bar, "date", None)
        if ts is None:
            return False
        try:
            bar_seconds = (bars[-1].date - ts).total_seconds() or 60.0
            lag = (cal.now_et() - (ts + timedelta(seconds=bar_seconds))).total_seconds()
        except Exception:
            return True   # if the timing math can't be done, don't block the entry
        return -5 <= lag <= max(self.poll * 2, 15)

    # ----------------------------------------------------------------- trade mgmt
    def _enter(self, symbol, contract, sig: Signal):
        stop = self.resolve_stop(sig.entry, sig.stop)
        rr = (sig.target - sig.entry) / (sig.entry - stop) if sig.entry > stop else 0
        if rr < self.min_rr:
            self.log(f"{symbol} skip: R:R {rr:.2f} < min {self.min_rr}")
            return
        qty = self.size_position(sig.entry, stop)
        if qty <= 0:
            self.log(f"{symbol} skip: qty 0 (stop too tight or no equity)")
            return
        sector = self.sector_of(symbol, contract)
        risk_dollars = qty * (sig.entry - stop)
        ok, reason = self.risk.can_open(symbol, sector, risk_dollars,
                                        one_trade_per_symbol=self.cfg.get("one_trade_per_symbol", True))
        if not ok:
            self.log(f"{symbol} blocked by risk mgr: {reason}")
            return
        order_ref = f"{self.strategy_type}.{self.client_id}.{symbol}"
        # stop-LIMIT band tracks the FLOORED trigger (keeps limit <= trigger for a SELL stop)
        stop_lmt = round(stop * (1 - sig.stop_limit_band), 4) if sig.use_stop_limit else None
        market_entry = str(self.cfg.get("entry_order_type", "MKT")).upper() == "MKT"
        pt, tp, st = eo.place_protected_entry(
            self.ib, contract, qty, sig.entry, sig.target, stop,
            stop_limit_price=stop_lmt, order_ref=order_ref,
            account=self.account or "", log=self.log, tick=sig.tick,
            entry_timeout_sec=int(self.cfg.get("entry_timeout_sec", 120)),
            max_chase_pct=float(self.cfg.get("max_chase_pct", 0.0)),
            market=market_entry,
        )
        if not pt:
            return
        fill = float(pt.orderStatus.avgFillPrice or sig.entry)
        filled_qty = int(pt.orderStatus.filled or qty)
        r_unit = fill - stop
        self.risk.register_open(order_ref, symbol, sector, filled_qty * r_unit, filled_qty, fill, stop)
        tk = self.get_ticker(symbol, contract)
        self.positions[order_ref] = Position(order_ref, symbol, sector, contract, filled_qty,
                                              fill, stop, sig.target, r_unit, pt, tp, st,
                                              ticker=tk, high_water=fill)
        self.journal_open(symbol, sector, filled_qty, fill, stop, sig.target, r_unit)
        self.log(f"OPENED {symbol} qty {filled_qty} entry {fill} stop {stop} target {sig.target}")

    def manage_open(self):
        total_unreal = 0.0
        for ref, p in list(self.positions.items()):
            # closed by stop?  (st/tp may be None on an adopted position missing a leg)
            if p.st is not None and p.st.orderStatus.status == "Filled":
                exit_px = float(p.st.orderStatus.avgFillPrice or p.stop)
                self._close(p, exit_px, "STOP")
                continue
            if p.tp is not None and p.tp.orderStatus.status == "Filled":
                exit_px = float(p.tp.orderStatus.avgFillPrice or p.target)
                self._close(p, exit_px, "TARGET")
                continue
            last = self.last_price(p.ticker) if p.ticker else None
            if last is None:
                continue
            total_unreal += (last - p.entry) * p.qty
            p.high_water = max(p.high_water, last)
            be_mult = float(self.cfg.get("breakeven_mult", self.cfg.get("breakeven_at_R", 1.0)))
            trail_start = float(self.cfg.get("trail_start_mult", be_mult + 0.5))
            if (p.st is not None and not p.breakeven_done
                    and last >= p.entry + be_mult * p.r_unit and p.stop < p.entry):
                new_stop = max(p.stop, p.entry)
                eo.modify_stop(self.ib, p.contract, p.st, new_stop, p.qty, tick=self._tick(p), log=self.log)
                p.stop = new_stop
                p.breakeven_done = True
                self.log(f"{p.symbol} stop -> breakeven {new_stop}")
            elif p.st is not None and last >= p.entry + trail_start * p.r_unit:
                trail_dist = float(self.cfg.get("trail_lock_mult", 0.5)) * p.r_unit
                new_stop = round(p.high_water - trail_dist, 4)
                if new_stop > p.stop:
                    eo.modify_stop(self.ib, p.contract, p.st, new_stop, p.qty, tick=self._tick(p), log=self.log)
                    p.stop = new_stop
                    p.trail_active = True
        self.risk.mark_unrealized(self.name, total_unreal)

    def _tick(self, p):
        return self.min_tick(p.symbol, p.contract)

    def _close(self, p: Position, exit_px, reason):
        pnl = (exit_px - p.entry) * p.qty
        rmult = (exit_px - p.entry) / p.r_unit if p.r_unit else 0
        # cancel the surviving sibling
        for sib in (p.tp, p.st):
            if sib is None:
                continue
            try:
                if sib.orderStatus.status not in ("Filled", "Cancelled", "ApiCancelled",
                                                   "PendingCancel", "Inactive"):
                    self.ib.cancelOrder(sib.order)
            except Exception:
                pass
        # Do NOT cancelMktData here: the ticker is the shared watchlist feed reused for
        # signals/re-entry the rest of the session; released together at disconnect().
        self.risk.register_close(p.order_ref, pnl)
        self.positions.pop(p.order_ref, None)
        self.journal_close(p.symbol, exit_px, pnl, rmult, reason)
        if self.reporter:
            self.reporter.record_trade({
                "Date": cal.now_et().strftime("%Y-%m-%d"),
                "Time": cal.now_et().strftime("%H:%M:%S"),
                "Strategy": self.name, "Ticker": p.symbol, "Sector": p.sector,
                "Shares": p.qty, "Entry": round(p.entry, 4), "Stop": round(p.stop, 4),
                "Target": round(p.target, 4), "Exit": round(exit_px, 4),
                "PnL": round(pnl, 2), "R_Multiple": round(rmult, 3),
                "Result": "WIN" if pnl > 0 else ("LOSS" if pnl < 0 else "FLAT"),
                "Reason": reason, "HoldMin": "",
            })
        self.log(f"CLOSED {p.symbol} {reason} exit {exit_px} pnl {pnl:.2f} ({rmult:.2f}R)")

    def flatten_all(self, reason="EOD"):
        for ref, p in list(self.positions.items()):
            # cancel resting protective legs first so the stop can't race the market exit
            for sib in (p.tp, p.st):
                if sib is None:
                    continue
                try:
                    if sib.orderStatus.status not in ("Filled", "Cancelled", "ApiCancelled",
                                                       "PendingCancel", "Inactive"):
                        self.ib.cancelOrder(sib.order)
                except Exception:
                    pass
            tr = eo.flatten_position(self.ib, p.contract, p.qty, order_ref=p.order_ref,
                                     account=self.account or "", log=self.log)
            if tr is not None and tr.orderStatus.status == "Filled":
                exit_px = float(tr.orderStatus.avgFillPrice or self.last_price(p.ticker) or p.entry)
            else:
                exit_px = self.last_price(p.ticker) or p.entry
                self.log(f"WARNING: flatten of {p.symbol} not confirmed Filled "
                         f"(status {tr.orderStatus.status if tr else 'none'}); recorded at {exit_px}")
            self._close(p, exit_px, reason)

    # ----------------------------------------------------------------- journal
    def journal_open(self, symbol, sector, qty, entry, stop, target, r_unit):
        self.shared["journal"](self.name, {
            "Event": "OPEN", "Symbol": symbol, "Sector": sector, "Strategy": self.name,
            "Shares": qty, "Entry": entry, "Stop": stop, "Target": target,
            "RiskAtStop": round(qty * r_unit, 2),
        })

    def journal_close(self, symbol, exit_px, pnl, rmult, reason):
        self.shared["journal"](self.name, {
            "Event": "CLOSE", "Symbol": symbol, "Strategy": self.name,
            "Exit": exit_px, "PnL": round(pnl, 2), "R_Multiple": round(rmult, 2), "Result": reason,
        })

    def in_trade_window(self, now=None):
        """True if `now` (ET) is inside ANY configured trade window (self.windows)."""
        now = now or cal.now_et()
        return any(cal.at_et(s) <= now <= cal.at_et(e) for s, e in self.windows)

    # ----------------------------------------------------------------- template loop
    def run(self):
        if not self.connect():
            return
        try:
            start = self.window_start
            if not cal.is_trading_day():
                self.log("not a trading day; exiting")
                return
            self.before_open()
            # adopt any position this bot already has open (restart / crash recovery) so its
            # live bracket keeps being managed and the entry loop won't duplicate it
            self.adopt_existing_positions()
            self.log(f"trade window(s): {self.windows}")
            # wait until the FIRST window opens (short ticks so we can bail/flatten)
            while cal.now_et() < cal.at_et(start):
                self.ib.sleep(2)
                if cal.now_et() >= cal.effective_flatten_time(self.eod_flatten):
                    break
            watchlist = self.build_watchlist()
            self.log(f"watchlist ({len(watchlist)}): {watchlist[:25]}")
            contracts = {s: self.qualify(s) for s in watchlist}

            flat_time = cal.effective_flatten_time(self.eod_flatten)
            while True:
                # detect/repair a dropped connection before acting this tick
                if not self.ensure_connected():
                    self.log("CRITICAL: cannot reconnect; positions may be unmanaged. Exiting loop.")
                    break
                now = cal.now_et()
                # --- dedicated EOD check on EVERY tick (never buried behind long sleeps)
                if now >= flat_time:
                    if self.positions:
                        self.log("EOD flatten")
                        self.flatten_all("EOD")
                    break
                self.manage_open()
                entries_open = self.in_trade_window(now)
                if entries_open and not self.risk.is_halted() and self.regime_ok():
                    for sym in watchlist:
                        ref = f"{self.strategy_type}.{self.client_id}.{sym}"
                        if ref in self.positions:
                            continue
                        if self.risk.is_open_symbol(sym) or self.risk.traded_today(sym):
                            continue
                        try:
                            sig = self.check_entry_signal(sym, contracts[sym])
                        except Exception as e:
                            self.log(f"signal error {sym}: {e}")
                            sig = None
                        if sig:
                            self._enter(sym, contracts[sym], sig)
                self.ib.sleep(self.poll)
            # after EOD: keep managing until flat
            guard = 0
            while self.positions and guard < 30:
                self.manage_open()
                self.ib.sleep(2)
                guard += 1
        finally:
            self.disconnect()

    # ----------------------------------------------------------------- hooks
    def before_open(self):
        """Optional pre-open setup (e.g. nightly watchlist load). Override if needed."""
        pass

    def build_watchlist(self):
        raise NotImplementedError

    def check_entry_signal(self, symbol, contract) -> Signal | None:
        raise NotImplementedError
