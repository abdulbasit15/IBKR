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
        self._tickers: dict[str, object] = {}
        self.require_vwap = bool(self.cfg.get("require_vwap", True))
        self.windows = self.cfg.get("windows", [["09:35", "11:30"], ["14:00", "15:30"]])

    def build_watchlist(self):
        u = self.cfg.get("universe", {})
        price_min = u.get("min_price", self.cfg.get("min_price", 20))
        price_max = u.get("max_price", self.cfg.get("max_price", 200))
        dadv_min = u.get("min_dollar_adv", self.cfg.get("min_dollar_adv", 25_000_000))
        rvol_min = u.get("min_premarket_rvol", self.cfg.get("premarket_rvol_min", 1.5))
        excl = set(self.cfg.get("exclude_symbols", []))
        kept = []
        for sym in self.cfg.get("universe_symbols", []):
            if sym in excl:
                continue
            c = self.qualify(sym)
            day = self.hist(c, "6 D", "1 day", "TRADES", True)
            if len(day) < 2 or not day[-1].close:
                continue
            last_close = day[-1].close
            if last_close < price_min or last_close > price_max:
                continue
            if self.dollar_adv(sym, c) < dadv_min:
                continue
            pmr = self.rvol(c, cal.session_open(), premarket=True)
            if pmr is not None and pmr < rvol_min:   # None = no premarket history -> keep
                continue
            # prior session high = high of the most recent COMPLETED daily bar
            self._pdh[sym] = day[-1].high
            kept.append(sym)
        line_cap = int(self.shared.get("shared_risk", {}).get("market_data_line_cap", 90))
        for sym in kept[:line_cap]:
            self.get_ticker(sym, self.qualify(sym))
        return kept

    def _in_any_window(self):
        now = cal.now_et()
        for start, end in self.windows:
            if cal.at_et(start) <= now <= cal.at_et(end):
                return True
        return False

    def check_entry_signal(self, symbol, contract):
        if not self._in_any_window():
            return None
        pdh = self._pdh.get(symbol)
        if not pdh:
            return None
        bars5 = self.hist(contract, "1 D", "5 mins", "TRADES", True)
        if len(bars5) < 3:
            return None
        bar = bars5[-2]              # last COMPLETED 5-min bar (avoid the forming bar)
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
        vw = self.vwap(tk)
        price = self.last_price(tk) or bar.close
        if vw is not None and price <= vw:
            return None
        if vw is None and self.require_vwap:
            return None

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
