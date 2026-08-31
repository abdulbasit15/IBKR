"""Previous Day High (PDH) Breakout - research strategy #5 (simplest / most mechanical).

Long on a 5-min close above the prior session high (with a small buffer), on volume,
above VWAP. Uses a stop-LIMIT child (caps slippage). The raw "0.05% below PDH" stop is
internally floored to min_stop_pct here (the adversarial-review must-fix) so position
sizing stays sane, and the target is set off that floored stop so R:R is honest.
Windows 09:35-11:30 and 14:00-15:30 ET.
"""
from __future__ import annotations

import calendar_util as cal
from equity_base import EquityStrategyBase, Signal


class PDHBreakout(EquityStrategyBase):
    strategy_type = "pdh_breakout"

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._pdh: dict[str, float] = {}
        self.require_vwap = bool(self.cfg.get("require_vwap", True))
        # trade windows are owned by the base (self.windows, parsed from equity.json)

    def build_watchlist(self):
        u = self.cfg.get("universe", {})
        price_min = u.get("min_price", self.cfg.get("min_price", 20))
        price_max = u.get("max_price", self.cfg.get("max_price", 200))
        dadv_min = u.get("min_dollar_adv", self.cfg.get("min_dollar_adv", 25_000_000))
        rvol_min = u.get("min_premarket_rvol", self.cfg.get("premarket_rvol_min", 1.5))
        excl = set(self.cfg.get("exclude_symbols", []))
        kept = []
        for sym in self.scanner_universe():
            if sym in excl:
                continue
            c = self.qualify(sym)
            day = self.hist(c, "6 D", "1 day", "TRADES", True)
            # prior SESSION pinned by DATE (exclude today's forming daily bar during RTH)
            prior = [b for b in day if b.date.strftime("%Y%m%d") < cal.now_et().strftime("%Y%m%d")]
            if not prior or not prior[-1].close:
                continue
            ref = prior[-1]
            if ref.close < price_min or ref.close > price_max:
                continue
            if self.dollar_adv(sym, c) < dadv_min:
                continue
            pmr = self.rvol(c, cal.session_open(), premarket=True)
            if pmr is not None and pmr < rvol_min:   # None = no premarket history -> keep
                continue
            self._pdh[sym] = ref.high   # prior session high
            kept.append(sym)
        line_cap = int(self.shared.get("shared_risk", {}).get("market_data_line_cap", 90))
        for sym in kept[:line_cap]:
            self.get_ticker(sym, self.qualify(sym))
        return kept

    def check_entry_signal(self, symbol, contract):
        # trade-window gating is handled centrally by the base run loop (self.windows)
        pdh = self._pdh.get(symbol)
        if not pdh:
            return None
        bars5 = self.hist(contract, "1 D", "5 mins", "TRADES", True)
        if len(bars5) < 3:
            return None
        bar = bars5[-2]              # last COMPLETED 5-min bar (avoid the forming bar)
        if not self.is_new_bar(symbol, bars5):
            return None  # only act at a new-bar-open boundary, never mid-bar
        buf = float(self.cfg.get("breakout_buffer_pct", self.cfg.get("breakout_mult_minus_1", 0.001)))
        trigger = pdh * (1 + buf)
        if bar.close <= trigger:
            return None
        recent = [b.volume for b in bars5[-8:-2] if b.volume]   # completed bars only
        avg = (sum(recent) / len(recent)) if recent else 0
        vmult = float(self.cfg.get("vol_mult", 1.5))
        if avg and bar.volume < vmult * avg:
            return None
        tk = self.get_ticker(symbol, contract)
        vw = self.session_vwap_from_bars(bars5, len(bars5) - 2)  # session VWAP from bars (delayed-safe)
        price = self.last_price(tk) or bar.close
        if self.require_vwap and (vw is None or price <= vw):
            return None  # VWAP filter; set require_vwap False to disable it entirely

        tick = self.min_tick(symbol, contract)
        entry = trigger + float(self.cfg.get("entry_offset_pct", 0.0005)) * pdh
        # raw structural stop (0.05% below PDH) floored to min_stop_pct so sizing is sane
        raw_stop = pdh * (1 - float(self.cfg.get("stop_pct", 0.0005)))
        floored = min(raw_stop, entry * (1 - self.min_stop_pct))
        r_unit = entry - floored
        if r_unit <= 0:
            return None
        target = entry + float(self.cfg.get("target1_R", 2.0)) * r_unit
        band = max(float(self.cfg.get("stop_limit_pct", 0.0025)) - float(self.cfg.get("stop_pct", 0.0005)),
                   0.0015)
        return Signal(entry=entry, stop=floored, target=target, tick=tick,
                      use_stop_limit=True, stop_limit_band=band,
                      note=f"PDH {pdh:.2f}")
