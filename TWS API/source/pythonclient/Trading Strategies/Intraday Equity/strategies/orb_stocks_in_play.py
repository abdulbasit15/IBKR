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
        self.require_vwap = bool(self.cfg.get("require_vwap", True))

    # -------------------------------------------------- watchlist (pre-market scan)
    def build_watchlist(self):
        u = self.cfg.get("universe", {})
        price_min = u.get("min_price", self.cfg.get("price_min", 15))
        adv_min = u.get("min_adv", self.cfg.get("adv_min", 1_000_000))
        gap_min = u.get("min_gap_pct", self.cfg.get("gap_min", 0.02))
        rvol_min = u.get("min_premarket_rvol", self.cfg.get("rvol_min", 1.5))
        excl = set(u.get("exclude_symbols", [])) | {"SPY", "QQQ"}
        universe = [s for s in self.scanner_universe() if s not in excl]
        line_cap = int(self.shared.get("shared_risk", {}).get("market_data_line_cap", 90))

        kept = []
        for sym in universe:
            c = self.qualify(sym)
            day = self.hist(c, "3 D", "1 day", "TRADES", True)
            # prior SESSION pinned by DATE (exclude today's forming daily bar during RTH)
            prior = [b for b in day if b.date.strftime("%Y%m%d") < cal.now_et().strftime("%Y%m%d")]
            if not prior or not prior[-1].close:
                continue
            prior_close = prior[-1].close
            if prior_close < price_min:
                continue
            # $-ADV in shares terms
            adv_sh = (self.dollar_adv(sym, c) / prior_close) if prior_close else 0
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
        # VWAP gate — session VWAP from the intraday bars (delayed-safe; the RTVolume tick
        # ticker.vwap is NaN on delayed/unentitled feeds, which otherwise blocks every entry).
        tk = self.get_ticker(symbol, contract)
        vw = self.session_vwap_from_bars(bars1, len(bars1) - 2)
        price = self.last_price(tk) or bar.close
        if self.require_vwap and (vw is None or price <= vw):
            return None  # VWAP filter; set require_vwap False to disable it entirely

        tick = self.min_tick(symbol, contract)
        atr_d = self.atr(contract, 14, "1 day")
        entry = orec["high"] + float(self.cfg.get("atr_entry_buffer_mult", 0.05)) * atr_d
        mid_pct = float(self.cfg.get("stop", {}).get("min_or_height_pct",
                        self.cfg.get("orb_mid_stop_pct", 0.01)))
        structural = orec["mid"] if (orec["height"] / orec["high"] < mid_pct) else orec["low"]
        # floor the stop (matches base) and set the target off the FLOORED stop distance so
        # R:R is honest/consistent with NR7 & PDH. (~equals the old range-based target when
        # stop==OR_low; diverges only once the stop is floored on a narrow range.)
        floored = min(structural, entry * (1 - self.min_stop_pct))
        r_unit = entry - floored
        if r_unit <= 0:
            return None
        mult = float(self.cfg.get("target", {}).get("mult", self.cfg.get("target_mult", 2.0)))
        target = entry + mult * r_unit
        return Signal(entry=entry, stop=floored, target=target, tick=tick,
                      note=f"ORB H{orec['high']:.2f} L{orec['low']:.2f}")
