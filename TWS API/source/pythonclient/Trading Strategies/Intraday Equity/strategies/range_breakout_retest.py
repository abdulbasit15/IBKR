"""Breakout with Retest (intraday) - research strategy #2.

Detect a tight intraday CONSOLIDATION (a box of `range_lookback` 5-min bars whose height is
<= range_max_pct). After price BREAKS above the box high, do NOT chase: wait for the RETEST
that pulls back to the broken level and HOLDS, then go long when a completed 5-min bar closes
back above the box high on volume (above session VWAP). Stop just inside the range (box mid by
default); target = entry + target_mult * box height (measured move), with a min-R:R check via
the base. The retest entry makes the fill realistic (no chasing the breakout bar).

Long-only; EOD-flat; entries only on the last COMPLETED 5-min bar.
"""
from __future__ import annotations

from equity_base import EquityStrategyBase, Signal


class RangeBreakoutRetest(EquityStrategyBase):
    strategy_type = "range_breakout_retest"

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.require_vwap = bool(self.cfg.get("require_vwap", True))

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
            if self.dollar_adv(sym, c) < dadv_min:
                continue
            tk = self.get_ticker(sym, c)
            px = self.last_price(tk)
            if px is not None and (px < price_min or px > price_max):
                continue
            kept.append(sym)
        line_cap = int(self.shared.get("shared_risk", {}).get("market_data_line_cap", 90))
        return kept[:line_cap]

    def check_entry_signal(self, symbol, contract):
        bars = self.hist(contract, "1 D", "5 mins", "TRADES", True)
        rlb = int(self.cfg.get("range_lookback", 6))
        retest_win = int(self.cfg.get("retest_window", 4))
        if len(bars) < rlb + retest_win + 2:
            return None
        if not self.is_new_bar(symbol, bars):
            return None
        i = len(bars) - 2                       # last COMPLETED bar (the retest-hold candidate)

        # box = the `rlb` bars ending just before the breakout/retest window
        box = bars[i - retest_win - rlb: i - retest_win]
        if len(box) < rlb:
            return None
        rh = max(b.high for b in box)
        rl = min(b.low for b in box)
        if rh <= 0:
            return None
        height = rh - rl
        if height <= 0:
            return None
        if height / rh > float(self.cfg.get("range_max_pct", 0.03)):
            return None                          # box must be a genuine (tight) consolidation
        if height / rh < float(self.cfg.get("range_min_pct", 0.004)):
            return None

        # a breakout must have occurred in the window between the box and now
        window = bars[i - retest_win: i]         # bars after the box, before the current bar
        if not any(b.close > rh for b in window):
            return None

        b = bars[i]
        band = float(self.cfg.get("retest_band", 0.002))
        # retest HOLD: this completed bar dipped back to the broken level then closed above it
        tagged = b.low <= rh * (1 + band) and b.low >= rl
        if not (tagged and b.close > rh and b.close > b.open):
            return None
        recent = [x.volume for x in bars[i - 6:i] if x.volume]
        vmult = float(self.cfg.get("vol_mult", 1.2))
        if recent and b.volume < vmult * (sum(recent) / len(recent)):
            return None
        vw = self.session_vwap_from_bars(bars, i)
        self.get_ticker(symbol, contract)   # keep the market-data feed warm for position mgmt
        # Gate on the completed bar's close, not a live tick (last_price degrades to the prior-day
        # close on an unentitled feed -> below a rising VWAP -> rejects every breakout).
        if self.require_vwap and (vw is None or b.close <= vw):
            self.log_reject(symbol, f"close {b.close:.2f} <= VWAP {vw:.2f}" if vw else "no VWAP yet")
            return None

        tick = self.min_tick(symbol, contract)
        entry = b.close                          # realistic: enter on the retest-hold close
        stop_frac = float(self.cfg.get("stop_inside_frac", 0.5))   # 0.5 = box mid; 1.0 = box low
        stop = rh - stop_frac * height           # "just inside the range"
        r_unit = entry - stop
        if r_unit <= 0:
            return None
        target = entry + float(self.cfg.get("target_mult", 2.0)) * height   # measured move
        return Signal(entry=entry, stop=stop, target=target, tick=tick,
                      note=f"RBR box[{rl:.2f},{rh:.2f}]")
