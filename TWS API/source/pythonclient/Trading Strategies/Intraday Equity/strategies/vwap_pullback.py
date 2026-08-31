"""VWAP Pullback / Reclaim Continuation - research strategy (long-only).

The "break and retest" of session VWAP: after a first impulse pushes price above a
RISING session VWAP, wait for a controlled pullback that RE-TESTS the VWAP zone and holds
above it on a HIGHER LOW, then go long when the next completed 5-min bar RECLAIMS by
closing back above both VWAP and the pullback high (the continuation trigger), on volume.

Same delayed-data-safe engine conventions as the other bots:
  * session VWAP computed FROM BARS (works when the RTVolume tick ticker.vwap is NaN),
  * entries only at a new-bar-open boundary (is_new_bar) on the last COMPLETED 5-min bar,
  * structural stop below the pullback (higher) low, floored to min_stop_pct so sizing is
    sane and R:R is honest, target = entry + target_r_mult * R.
Default windows 09:45-11:30 and 14:00-15:30 ET (skip the first ~10 min so a VWAP + an
initial impulse leg can form).
"""
from __future__ import annotations

import calendar_util as cal
from equity_base import EquityStrategyBase, Signal


class VWAPPullback(EquityStrategyBase):
    strategy_type = "vwap_pullback"

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.require_vwap = bool(self.cfg.get("require_vwap", True))
        # trade windows are owned by the base (self.windows, parsed from equity.json)

    # -------------------------------------------------- watchlist (stocks in play)
    def build_watchlist(self):
        u = self.cfg.get("universe", {})
        price_min = u.get("min_price", self.cfg.get("min_price", 15))
        price_max = u.get("max_price", self.cfg.get("max_price", 500))
        dadv_min = u.get("min_dollar_adv", self.cfg.get("min_dollar_adv", 25_000_000))
        rvol_min = u.get("min_premarket_rvol", self.cfg.get("premarket_rvol_min", 1.5))
        excl = set(self.cfg.get("exclude_symbols", [])) | set(u.get("exclude_symbols", [])) | {"SPY", "QQQ"}
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
            kept.append(sym)
            if len(kept) >= int(self.cfg.get("max_watchlist", 30)):
                break
        line_cap = int(self.shared.get("shared_risk", {}).get("market_data_line_cap", 90))
        for sym in kept[:line_cap]:
            self.get_ticker(sym, self.qualify(sym))
        return kept

    # -------------------------------------------------- helpers
    def _vwap_series(self, bars, upto):
        """Running session VWAP value at EACH bar index 0..upto (cumulative typical*vol /
        cumulative vol). Computed once from bars so it is delayed-data-safe (ticker.vwap is
        NaN on unentitled feeds). Returns a list aligned to bars; entries are None until any
        volume has accumulated."""
        pv = vv = 0.0
        out = []
        for i in range(0, upto + 1):
            b = bars[i]
            vol = b.volume or 0
            pv += ((b.high + b.low + b.close) / 3.0) * vol
            vv += vol
            out.append((pv / vv) if vv > 0 else None)
        return out

    # -------------------------------------------------- entry
    def check_entry_signal(self, symbol, contract):
        # trade-window gating is handled centrally by the base run loop (self.windows)
        bars5 = self.hist(contract, "1 D", "5 mins", "TRADES", True)
        lb = int(self.cfg.get("pullback_lookback", 8))
        if len(bars5) < max(lb, int(self.cfg.get("vwap_slope_lookback", 3))) + 3:
            return None
        if not self.is_new_bar(symbol, bars5):
            return None  # only act at a new-bar-open boundary, never mid-bar
        n = len(bars5) - 2           # index of the last COMPLETED 5-min bar (the trigger bar)
        bar = bars5[n]

        vw = self._vwap_series(bars5, n)
        vw_now = vw[n]
        if vw_now is None:
            return None              # no VWAP yet (no volume) -> can't evaluate the setup

        # (1) TREND: session VWAP must be RISING over the slope lookback (uptrend context)
        slope_lb = int(self.cfg.get("vwap_slope_lookback", 3))
        base_vw = vw[n - slope_lb]
        if self.require_vwap and (base_vw is None or vw_now <= base_vw):
            return None

        # price above VWAP right now (live tick if available, else the completed-bar close)
        tk = self.get_ticker(symbol, contract)
        price = self.last_price(tk) or bar.close
        if self.require_vwap and price <= vw_now:
            return None

        # (2) IMPULSE: earliest bar in the lookback window whose HIGH pushed clearly above VWAP
        impulse_pct = float(self.cfg.get("impulse_pct", 0.003))
        lo = max(1, n - lb)
        i_imp = None
        for i in range(lo, n - 1):   # leave >=1 bar between the impulse and the trigger bar
            if vw[i] is not None and bars5[i].high >= vw[i] * (1 + impulse_pct):
                i_imp = i
                break
        if i_imp is None:
            return None

        # (3) PULLBACK / RE-TEST: the bars between the impulse and the trigger bar
        seg = range(i_imp + 1, n)    # pullback bars (exclude the trigger bar itself)
        if len(seg) < 1:
            return None
        pullback_low = min(bars5[j].low for j in seg)
        pullback_high = max(bars5[j].high for j in seg)
        pl_idx = min(seg, key=lambda j: bars5[j].low)   # bar that made the pullback low

        touch_band = float(self.cfg.get("pullback_touch_band", 0.003))
        reclaim_depth = float(self.cfg.get("reclaim_depth_pct", 0.002))
        # re-test: at least one pullback bar dipped INTO the VWAP zone (low near/at VWAP)
        retested = any(vw[j] is not None and bars5[j].low <= vw[j] * (1 + touch_band) for j in seg)
        if not retested:
            return None
        # controlled: the pullback held above VWAP (didn't collapse far below it)
        vw_pl = vw[pl_idx]
        if vw_pl is not None and pullback_low < vw_pl * (1 - reclaim_depth):
            return None
        # (4) HIGHER LOW vs the base of the impulse leg
        if pullback_low <= bars5[i_imp].low:
            return None

        # (5) CONTINUATION TRIGGER: the completed bar reclaims by closing above the pullback
        # high AND above VWAP (price > VWAP already checked above)
        if bar.close <= pullback_high or bar.close <= vw_now:
            return None

        # volume confirmation on the trigger bar vs the recent completed 5-min average
        recent = [b.volume for b in bars5[max(0, n - 6):n] if b.volume]
        avg = (sum(recent) / len(recent)) if recent else 0
        vmult = float(self.cfg.get("vol_mult", 1.3))
        if avg and bar.volume < vmult * avg:
            return None

        tick = self.min_tick(symbol, contract)
        atr5 = self.atr(contract, int(self.cfg.get("atr_period", 14)), "5 mins")
        entry = pullback_high + float(self.cfg.get("entry_offset_atr_mult", 0.05)) * atr5
        # structural stop below the higher (pullback) low; floored to min_stop_pct for sane
        # sizing and an honest R:R (matches the other bots' flooring).
        structural = pullback_low - float(self.cfg.get("stop_atr_mult", 0.5)) * atr5
        floored = min(structural, entry * (1 - self.min_stop_pct))
        r_unit = entry - floored
        if r_unit <= 0:
            return None
        target = entry + float(self.cfg.get("target_r_mult", 2.0)) * r_unit
        return Signal(entry=entry, stop=floored, target=target, tick=tick,
                      note=f"VWAP reclaim vw{vw_now:.2f} pbL{pullback_low:.2f} pbH{pullback_high:.2f}")
