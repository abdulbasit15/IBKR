"""Trend-following Pullback (intraday) - research strategy #1, intraday variant.

In an established INTRADAY uptrend (EMA9 > EMA20, EMA20 rising, price above session VWAP),
wait for a controlled PULLBACK that tags the rising EMA20 zone on a higher low, then go long
when the next completed 5-min bar RECLAIMS (closes back above the pullback high and EMA9) on
volume. Stop below the pullback swing low (floored to min_stop_pct); target = entry + R*mult.

Long-only; same delayed-data-safe conventions as the other bots (session VWAP from bars,
entries only at a new-bar-open boundary on the last COMPLETED 5-min bar). EOD-flat.
"""
from __future__ import annotations

import calendar_util as cal
from equity_base import EquityStrategyBase, Signal
from ta_utils import ema


class TrendPullback(EquityStrategyBase):
    strategy_type = "trend_pullback"

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.require_vwap = bool(self.cfg.get("require_vwap", True))

    def build_watchlist(self):
        u = self.cfg.get("universe", {})
        price_min = u.get("min_price", 15)
        price_max = u.get("max_price", 1000)
        dadv_min = u.get("min_dollar_adv", 25_000_000)
        rvol_min = u.get("min_premarket_rvol", 1.2)
        sma_n = int(self.cfg.get("daily_trend_sma", 20))
        excl = set(self.cfg.get("exclude_symbols", []))
        kept = []
        for sym in self.scanner_universe():
            if sym in excl:
                continue
            c = self.qualify(sym)
            day = self.hist(c, "40 D", "1 day", "TRADES", True)
            prior = [b for b in day if b.date.strftime("%Y%m%d") < cal.now_et().strftime("%Y%m%d")]
            if len(prior) < sma_n + 1 or not prior[-1].close:
                continue
            ref = prior[-1]
            if ref.close < price_min or ref.close > price_max:
                continue
            # daily uptrend filter: last close above a rising daily SMA
            closes = [b.close for b in prior]
            sma_now = sum(closes[-sma_n:]) / sma_n
            sma_prev = sum(closes[-sma_n - 1:-1]) / sma_n
            if ref.close <= sma_now or sma_now <= sma_prev:
                continue
            if self.dollar_adv(sym, c) < dadv_min:
                continue
            pmr = self.rvol(c, cal.session_open(), premarket=True)
            if pmr is not None and pmr < rvol_min:
                continue
            kept.append(sym)
        line_cap = int(self.shared.get("shared_risk", {}).get("market_data_line_cap", 90))
        for sym in kept[:line_cap]:
            self.get_ticker(sym, self.qualify(sym))
        return kept

    def check_entry_signal(self, symbol, contract):
        bars = self.hist(contract, "1 D", "5 mins", "TRADES", True)
        need = int(self.cfg.get("ema_slow", 20)) + int(self.cfg.get("pullback_lookback", 6)) + 3
        if len(bars) < need:
            return None
        if not self.is_new_bar(symbol, bars):
            return None
        i = len(bars) - 2                      # last COMPLETED bar
        closes = [b.close for b in bars]
        fast = ema(closes, int(self.cfg.get("ema_fast", 9)))
        slow = ema(closes, int(self.cfg.get("ema_slow", 20)))
        if fast[i] is None or slow[i] is None:
            return None
        slope_lb = int(self.cfg.get("ema_slope_lookback", 3))
        # 1) established intraday uptrend
        if not (fast[i] > slow[i] and slow[i] > slow[i - slope_lb]):
            return None
        vw = self.session_vwap_from_bars(bars, i)
        self.get_ticker(symbol, contract)   # keep the market-data feed warm for position mgmt
        # Gate on the completed bar's close, not a live tick (last_price degrades to the prior-day
        # close on an unentitled feed -> below a rising VWAP -> rejects every setup).
        if self.require_vwap and (vw is None or bars[i].close <= vw):
            self.log_reject(symbol, f"close {bars[i].close:.2f} <= VWAP {vw:.2f}" if vw else "no VWAP yet")
            return None
        # 2) a recent pullback that TAGGED the rising EMA20 zone (bar low near/below EMA20)
        lb = int(self.cfg.get("pullback_lookback", 6))
        seg = range(i - lb, i)                  # bars before the (potential) reclaim bar
        touch_band = float(self.cfg.get("ema_touch_band", 0.002))
        tagged = any(slow[j] is not None and bars[j].low <= slow[j] * (1 + touch_band) for j in seg)
        if not tagged:
            return None
        pull_low = min(bars[j].low for j in seg)
        pull_high = max(bars[j].high for j in seg)
        b = bars[i]
        # 3) reclaim/continuation trigger: bullish bar closing back above the pullback high & EMA9
        if not (b.close > b.open and b.close > pull_high and b.close > fast[i]):
            return None
        recent = [x.volume for x in bars[i - 6:i] if x.volume]
        vmult = float(self.cfg.get("vol_mult", 1.2))
        if recent and b.volume < vmult * (sum(recent) / len(recent)):
            return None

        tick = self.min_tick(symbol, contract)
        a5 = self.atr(contract, int(self.cfg.get("atr_period", 14)), "5 mins") or 0.0
        entry = b.close                        # realistic: enter on the completed reclaim bar
        stop = pull_low - float(self.cfg.get("stop_atr_mult", 0.2)) * a5
        r_unit = entry - stop
        if r_unit <= 0:
            return None
        target = entry + float(self.cfg.get("target_r_mult", 2.0)) * r_unit
        return Signal(entry=entry, stop=stop, target=target, tick=tick,
                      note=f"TP ema20 {slow[i]:.2f} pull_low {pull_low:.2f}")
