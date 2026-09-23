"""Heuristic setup auto-tagging from intraday price action.

For each trade we look at the 5-minute bars in the ~45 minutes before entry and
classify the setup relative to that context:

  Long:  Breakout (entry at/above prior highs) · Reversal (bought into a
         down-move) · Pullback (entered with an up-trend, not at highs)
  Short: Breakdown (entry at/below prior lows) · Reversal (sold into an
         up-move) · Pullback (entered with a down-trend, not at lows)

Falls back to daily-trend alignment ("With-trend"/"Counter-trend") when not
enough intraday bars are available.
"""
from __future__ import annotations

import statistics

from . import config, market

LOOKBACK_SEC = 45 * 60
MIN_BARS = 3


def classify(trade, bars: list[list] | None, day_ctx: dict | None = None) -> str:
    if trade.entry is None or trade.direction not in ("Long", "Short"):
        return ""
    ep = market.et_epoch(trade.timestamp) if trade.timestamp else None
    window = []
    if ep and bars:
        window = [b for b in bars if ep - LOOKBACK_SEC <= b[0] < ep]

    if len(window) >= MIN_BARS:
        highs = [b[2] for b in window]
        lows = [b[3] for b in window]
        prior_hi, prior_lo = max(highs), min(lows)
        rng = (prior_hi - prior_lo) or 1
        tol = rng * 0.10
        trend_up = window[-1][4] > window[0][1]     # last close vs first open
        e = trade.entry
        if trade.direction == "Long":
            if e >= prior_hi - tol:
                return "Breakout"
            if not trend_up:
                return "Reversal"
            return "Pullback"
        else:
            if e <= prior_lo + tol:
                return "Breakdown"
            if trend_up:
                return "Reversal"
            return "Pullback"

    # Fallback: align with the daily candle direction.
    if day_ctx and day_ctx.get("available"):
        dd = day_ctx.get("day_direction")
        if dd in ("up", "down"):
            aligned = (trade.direction == "Long" and dd == "up") or \
                      (trade.direction == "Short" and dd == "down")
            return "With-trend" if aligned else "Counter-trend"
    return ""


def autotag(trades, intraday: dict | None = None, market_days: dict | None = None) -> dict:
    """Default setup for each trade.

    The trader runs a single 'Break and Retest' strategy, so every trade defaults
    to that setup (editable per-trade in the tag popup). The price-action
    classifier `classify()` is kept for reference but no longer applied.
    """
    from . import tags as _t
    return {i: _t.DEFAULT_SETUP for i, t in enumerate(trades) if t.timestamp}


def detect_mistakes(trades) -> dict:
    """Return {trade_index: [mistake tags]} derived from the trade data itself.

    Mirrors the behavior-flag logic so each flagged trade gets a concrete tag:
    Revenge trade, Blew stop, Cut winner early, Oversized, Overtraded.
    Assumes pnl/rr are already populated (call analytics.compute_metrics first).
    """
    from collections import defaultdict
    ts = [t for t in trades if t.timestamp is not None]
    order = sorted(range(len(trades)), key=lambda i: trades[i].timestamp
                   if trades[i].timestamp else 0)
    out = defaultdict(list)

    sizes = [t.size for t in ts if t.size]
    med = statistics.median(sizes) if sizes else 0

    per_day = defaultdict(list)
    for i in order:
        t = trades[i]
        if t.timestamp:
            per_day[t.timestamp.date()].append(i)

    prev_i = None
    for i in order:
        t = trades[i]
        pnl = t.pnl or 0
        tags = out[i]
        # Oversized
        if med and t.size and t.size >= 3 * med:
            tags.append("Oversized")
        # Blew stop (loss worse than -1R)
        if pnl < 0 and t.rr_realized is not None and t.rr_realized < config.STOP_SLIPPAGE_RR:
            tags.append("Blew stop")
        # Cut winner early
        if (pnl > 0 and t.rr_realized is not None and t.rr_targeted
                and t.rr_realized < t.rr_targeted * config.CUT_WINNER_FRACTION):
            tags.append("Cut winner early")
        # Revenge trade (soon after a loss, same/larger size)
        if prev_i is not None:
            p = trades[prev_i]
            if (p.pnl or 0) < 0 and p.size and t.size and t.timestamp and p.timestamp:
                gap = (t.timestamp - p.timestamp).total_seconds() / 60
                if 0 <= gap <= config.REVENGE_WINDOW_MIN and t.size >= p.size:
                    tags.append("Revenge trade")
        prev_i = i

    # Overtraded: every trade on a day exceeding the daily-count threshold
    for d, idxs in per_day.items():
        if len(idxs) > config.OVERTRADING_PER_DAY:
            for i in idxs:
                out[i].append("Overtraded")

    return {i: v for i, v in out.items() if v}
