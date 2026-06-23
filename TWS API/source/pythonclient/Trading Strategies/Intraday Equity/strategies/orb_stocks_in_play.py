"""Opening Range Breakout - "Stocks in Play" (research strategy #1).

5-min opening range (09:30-09:35), long on a 1-min close above the range high on a
high-relative-volume / gap "stock in play", above VWAP. Stop at the range low (or mid on
a narrow range), target +2x range height. The RVOL/gap pre-market scan is the key custom
piece IBKR has no native field for.
"""
from __future__ import annotations

import calendar_util as cal
from equity_base import EquityStrategyBase, Signal


class ORBStocksInPlay(EquityStrategyBase):
    strategy_type = "orb_stocks_in_play"

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._or: dict[str, dict | None] = {}
        self._tickers: dict[str, object] = {}
        self.require_vwap = bool(self.cfg.get("require_vwap", True))

    # -------------------------------------------------- watchlist (pre-market scan)
    def build_watchlist(self):
        u = self.cfg.get("universe", {})
        price_min = u.get("min_price", self.cfg.get("price_min", 15))
        adv_min = u.get("min_adv", self.cfg.get("adv_min", 1_000_000))
        gap_min = u.get("min_gap_pct", self.cfg.get("gap_min", 0.02))
        rvol_min = u.get("min_premarket_rvol", self.cfg.get("rvol_min", 1.5))
        excl = set(u.get("exclude_symbols", [])) | {"SPY", "QQQ"}
        universe = [s for s in self.cfg.get("universe_symbols", []) if s not in excl]
        line_cap = int(self.shared.get("shared_risk", {}).get("market_data_line_cap", 90))

        kept = []
        for sym in universe:
            c = self.qualify(sym)
            day = self.hist(c, "2 D", "1 day", "TRADES", True)
            if len(day) < 2 or not day[-1].close:
                continue
            last_close = day[-1].close
            prior_close = day[-2].close
            if last_close < price_min:
                continue
            # $-ADV in shares terms
            adv_sh = (self.dollar_adv(sym, c) / last_close) if last_close else 0
            if adv_sh < adv_min:
                continue
            # opening gap from prior close (uses today's 5-min open)
            bars5 = self.hist(c, "1 D", "5 mins", "TRADES", True)
            if not bars5:
                continue
            gap = (bars5[0].open - prior_close) / prior_close if prior_close else 0
            pmr = self.rvol(c, cal.session_open(), premarket=True)
            rvol_ok = (pmr is None) or (pmr >= rvol_min)   # None = no premarket history -> keep
            if gap >= gap_min and rvol_ok:
                kept.append(sym)
            if len(kept) >= int(self.cfg.get("max_watchlist", 30)):
                break

        for sym in kept[:line_cap]:
            self.get_ticker(sym, self.qualify(sym))
        return kept

    def _opening_range(self, symbol, contract):
        if symbol in self._or:
            return self._or[symbol]
        bars = self.hist(contract, "1 D", "5 mins", "TRADES", True)
        orec = None
        if len(bars) >= 2:           # a 09:35 bar exists -> the 09:30-09:35 OR bar is closed
            b = bars[0]  # 09:30-09:35 with useRTH=True
            high, low = b.high, b.low
            height = high - low
            hp = height / high if high else 0
            hmax = float(self.cfg.get("orb_height_max_pct", 0.05))
            hmin = float(self.cfg.get("orb_height_min_pct", 0.003))
            if hmin <= hp <= hmax:
                orec = {"high": high, "low": low, "mid": (high + low) / 2, "height": height}
        self._or[symbol] = orec
        return orec

    # -------------------------------------------------- entry
    def check_entry_signal(self, symbol, contract):
        now = cal.now_et()
        if now < cal.at_et("09:36"):   # wait one bar past the 09:30-09:35 OR close
            return None
        orec = self._opening_range(symbol, contract)
        if not orec:
            return None
        bars1 = self.hist(contract, "1 D", "1 min", "TRADES", True)
        if len(bars1) < 6:
            return None
        bar = bars1[-2]  # last COMPLETED 1-min bar (avoid the forming bar)
        if bar.close <= orec["high"]:
            return None
        # breakout-bar volume confirmation vs recent same-session 1-min average
        recent = [b.volume for b in bars1[-22:-2] if b.volume]
        avg1 = (sum(recent) / len(recent)) if recent else 0
        vol_mult = float(self.cfg.get("signal", {}).get("vol_mult", self.cfg.get("breakout_vol_mult", 1.5)))
        if avg1 and bar.volume < vol_mult * avg1:
            return None
        # VWAP gate
        tk = self.get_ticker(symbol, contract)
        vw = self.vwap(tk)
        price = self.last_price(tk) or bar.close
        if vw is not None and price <= vw:
            return None
        if vw is None and self.require_vwap:
            return None  # no live VWAP -> do not trade (set require_vwap False for paper/delayed)

        tick = self.min_tick(symbol, contract)
        atr_d = self.atr(contract, 14, "1 day")
        entry = orec["high"] + float(self.cfg.get("atr_entry_buffer_mult", 0.05)) * atr_d
        mid_pct = float(self.cfg.get("stop", {}).get("min_or_height_pct",
                        self.cfg.get("orb_mid_stop_pct", 0.01)))
        stop = orec["mid"] if (orec["height"] / orec["high"] < mid_pct) else orec["low"]
        mult = float(self.cfg.get("target", {}).get("mult", self.cfg.get("target_mult", 2.0)))
        target = entry + mult * orec["height"]
        return Signal(entry=entry, stop=stop, target=target, tick=tick,
                      note=f"ORB H{orec['high']:.2f} L{orec['low']:.2f}")
