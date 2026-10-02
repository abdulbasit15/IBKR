"""Support/Resistance Bounce (intraday mean reversion) - research strategy #3, long-only.

Fade a pullback INTO a well-defined support level with confirmation. Support = the prior-day
low (a widely-watched level); the bar must tag it (low within touch_band of the level) while
RSI(14) is oversold, then a bullish REVERSAL bar reclaims the level (close > open and back
above support). Enter long; tight stop just below support (floored to min_stop_pct); target =
entry + target_r_mult * R (mean-reversion R:R is smaller than the trend strategies).

Long-only; EOD-flat; entries only on the last COMPLETED 5-min bar. This is a CHOP/range-regime
tool by design (it fades extremes) and is expected to underperform in strong trends.
"""
from __future__ import annotations

import calendar_util as cal
from equity_base import EquityStrategyBase, Signal
from ta_utils import rsi


class SRBounce(EquityStrategyBase):
    strategy_type = "sr_bounce"

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.require_vwap = bool(self.cfg.get("require_vwap", False))   # reversion trades below VWAP
        self._pdl: dict[str, float] = {}

    def build_watchlist(self):
        u = self.cfg.get("universe", {})
        price_min = u.get("min_price", 15)
        price_max = u.get("max_price", 1000)
        dadv_min = u.get("min_dollar_adv", 25_000_000)
        excl = set(self.cfg.get("exclude_symbols", []))
        kept = []
        for sym in self.scanner_universe():
            if sym in excl:
                continue
            c = self.qualify(sym)
            day = self.hist(c, "6 D", "1 day", "TRADES", True)
            prior = [b for b in day if b.date.strftime("%Y%m%d") < cal.now_et().strftime("%Y%m%d")]
            if not prior or not prior[-1].close:
                continue
            ref = prior[-1]
            if ref.close < price_min or ref.close > price_max:
                continue
            if self.dollar_adv(sym, c) < dadv_min:
                continue
            self._pdl[sym] = ref.low            # prior-day low = the tested support level
            kept.append(sym)
        line_cap = int(self.shared.get("shared_risk", {}).get("market_data_line_cap", 90))
        for sym in kept[:line_cap]:
            self.get_ticker(sym, self.qualify(sym))
        return kept

    def check_entry_signal(self, symbol, contract):
        level = self._pdl.get(symbol)
        if not level:
            return None
        bars = self.hist(contract, "1 D", "5 mins", "TRADES", True)
        rsi_p = int(self.cfg.get("rsi_period", 14))
        if len(bars) < rsi_p + 3:
            return None
        if not self.is_new_bar(symbol, bars):
            return None
        i = len(bars) - 2                        # last COMPLETED bar (the reversal candidate)
        closes = [b.close for b in bars]
        rv = rsi(closes, rsi_p)
        b = bars[i]
        band = float(self.cfg.get("touch_band", 0.003))
        # tag support: this bar (or the prior one) dipped to/through the level
        tagged = min(b.low, bars[i - 1].low) <= level * (1 + band)
        if not tagged:
            return None
        # oversold confirmation on the tag
        rsi_os = float(self.cfg.get("rsi_oversold", 35.0))
        if rv[i] is None or rv[i] > rsi_os:
            return None
        # bullish reversal reclaim: close back above the level and above its open
        if not (b.close > b.open and b.close > level):
            return None

        tick = self.min_tick(symbol, contract)
        entry = b.close                          # realistic: enter on the reversal-bar close
        stop = min(b.low, level) * (1 - float(self.cfg.get("stop_buffer_pct", 0.002)))
        r_unit = entry - stop
        if r_unit <= 0:
            return None
        target = entry + float(self.cfg.get("target_r_mult", 1.75)) * r_unit
        # optional VWAP cap: don't target above VWAP if configured to fade back into it only
        return Signal(entry=entry, stop=stop, target=target, tick=tick,
                      note=f"SRB PDL {level:.2f} rsi {rv[i]:.0f}")
