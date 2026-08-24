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

from . import market

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
    """Return {trade_id(index): label}. Fetches intraday/market data if not given."""
    if intraday is None:
        intraday = market.summarize_intraday(trades)
    if market_days is None:
        market_days = market.summarize_days(trades)
    labels = {}
    for i, t in enumerate(trades):
        if not t.timestamp:
            continue
        d = t.timestamp.date()
        bars = intraday.get(f"{t.asset}|{d}")
        ctx = market_days.get((t.asset, str(d)))
        labels[i] = classify(t, bars, ctx)
    return labels
