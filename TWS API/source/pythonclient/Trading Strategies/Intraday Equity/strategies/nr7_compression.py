"""Volume / Compression Breakout (NR7 + RVOL + ORB) - research strategy #2.

Nightly daily-bar scan builds a FIXED next-day watchlist (NR7 = narrowest range of the
last 7 days, ADR% > 5, close > 20-SMA, ADV >= 1M, liquid price band). Intraday: long on a
5-min close above the 09:30-09:35 opening-range high with RVOL >= 1.5 and price > VWAP.
Stop = the more-conservative of (ORB_LOW - 0.5*ATR5) and (VWAP_at_entry - buffer);
target = entry + 2.2 * stop_distance. The nightly fixed watchlist sidesteps IBKR's
RTH-only scanner.
"""
from __future__ import annotations

import calendar_util as cal
from equity_base import EquityStrategyBase, Signal


class NR7Compression(EquityStrategyBase):
    strategy_type = "nr7_compression"

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._or: dict[str, dict | None] = {}
        self._tickers: dict[str, object] = {}
        self._vwap_at_entry: dict[str, float] = {}
        self.require_vwap = bool(self.cfg.get("require_vwap", True))

    # -------------------------------------------------- nightly/at-open scan
    def build_watchlist(self):
        price_min = self.cfg.get("price_min", 15)
        price_max = self.cfg.get("price_max", 150)
        adv_min = self.cfg.get("adv_min_shares", 1_000_000)
        adr_min = self.cfg.get("adr_min_pct", 5.0)
        sma_n = int(self.cfg.get("sma_period", 20))
        nr7_n = int(self.cfg.get("nr7_lookback", 7))
        kept = []
        for sym in self.cfg.get("universe_symbols", []):
            c = self.qualify(sym)
            bars = self.hist(c, f"{max(sma_n, nr7_n, 25) + 5} D", "1 day", "TRADES", True)
            if len(bars) < max(sma_n, nr7_n) + 1:
                continue
            ref = bars[-1]  # most recent completed daily bar (the compression day)
            if not ref.close or ref.close < price_min or ref.close > price_max:
                continue
            ranges = [(b.high - b.low) for b in bars[-nr7_n:]]
            if (ref.high - ref.low) > min(ranges):   # ref must be the narrowest
                continue
            adrp = self.adr_pct(c, int(self.cfg.get("adr_lookback", 20)))
            if adrp < adr_min:
                continue
            sma = sum(b.close for b in bars[-sma_n:]) / sma_n
            if ref.close <= sma:
                continue
            advsh = sum(float(b.volume) * self.vol_scale for b in bars[-20:]) / min(20, len(bars))
            if advsh < adv_min:
                continue
            kept.append(sym)
        line_cap = int(self.shared.get("shared_risk", {}).get("market_data_line_cap", 90))
        for sym in kept[:line_cap]:
            self.get_ticker(sym, self.qualify(sym))
        # persist watchlist for the day
        try:
            self.cache.put(f"nr7_watchlist:{cal.now_et().strftime('%Y%m%d')}", kept)
        except Exception:
            pass
        return kept

    def _opening_range(self, symbol, contract):
        if symbol in self._or:
            return self._or[symbol]
        bars = self.hist(contract, "1 D", "5 mins", "TRADES", True)
        orec = None
        if bars:
            b = bars[0]
            orec = {"high": b.high, "low": b.low, "height": b.high - b.low}
        self._or[symbol] = orec
        return orec

    # -------------------------------------------------- entry
    def check_entry_signal(self, symbol, contract):
        now = cal.now_et()
        if now < cal.at_et("09:35"):
            return None
        if now > cal.at_et(self.cfg.get("entry_cutoff_time", "11:00")):
            return None
        orec = self._opening_range(symbol, contract)
        if not orec:
            return None
        bars5 = self.hist(contract, "1 D", "5 mins", "TRADES", True)
        if len(bars5) < 3:
            return None
        bar = bars5[-2]              # last COMPLETED 5-min bar (avoid the forming bar)
        if bar.close <= orec["high"]:
            return None
        rv = self.rvol(contract, now, premarket=False)
        rvol_min = float(self.cfg.get("rvol_min", 1.5))
        if rv is None:
            if bool(self.cfg.get("require_rvol", True)):
                return None           # genuinely missing history -> skip (don't bypass the gate)
        elif rv < rvol_min:
            return None
        tk = self.get_ticker(symbol, contract)
        vw = self.vwap(tk)
        price = self.last_price(tk) or bar.close
        if vw is not None and price <= vw:
            return None
        if vw is None and self.require_vwap:
            return None

        tick = self.min_tick(symbol, contract)
        atr5 = self.atr(contract, int(self.cfg.get("atr_period", 14)), "5 mins")
        entry = orec["high"] + float(self.cfg.get("entry_offset_atr_mult", 0.05)) * atr5
        stop_atr = orec["low"] - float(self.cfg.get("stop_atr_mult", 0.5)) * atr5
        # fractional VWAP buffer (an absolute $0.01 would sit the stop essentially AT vwap)
        stop_vwap = (vw * (1 - float(self.cfg.get("vwap_stop_buffer_pct", 0.001)))) if vw else stop_atr
        structural = max(stop_atr, stop_vwap)   # higher = tighter/more conservative
        floored = min(structural, entry * (1 - self.min_stop_pct))  # match base flooring -> honest R:R
        stop_dist = entry - floored
        if stop_dist <= 0:
            return None
        target = entry + float(self.cfg.get("target_r_mult", 2.2)) * stop_dist
        return Signal(entry=entry, stop=floored, target=target, tick=tick,
                      note=f"NR7 ORB_H{orec['high']:.2f}")
