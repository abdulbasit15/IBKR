"""Offline performance + behavior analytics over a list of Trade objects."""
from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import datetime

from . import config


def _pnl(t) -> float | None:
    """Trade P&L, preferring the workbook's cached value, else recomputed."""
    if t.pnl is not None:
        return t.pnl
    mult = config.MULTIPLIERS.get((t.asset or "").upper())
    if None in (t.entry, t.exit, t.size) or mult is None:
        return None
    diff = (t.exit - t.entry) if t.direction == "Long" else (t.entry - t.exit)
    return diff * t.size * mult


def _rr_realized(t) -> float | None:
    """RR realized, matching the workbook formula (exit-entry)/(entry-stop)."""
    if t.rr_realized is not None:
        return t.rr_realized
    if None in (t.entry, t.exit, t.stop) or (t.entry - t.stop) == 0:
        return None
    return (t.exit - t.entry) / (t.entry - t.stop)


def _rr_targeted(t) -> float | None:
    if t.rr_targeted is not None:
        return t.rr_targeted
    if None in (t.entry, t.target, t.stop) or (t.entry - t.stop) == 0:
        return None
    return (t.target - t.entry) / (t.entry - t.stop)


def _ensure_derived(trades) -> None:
    """Fill P&L / RR / Win-Loss from raw inputs for rows Excel hasn't cached yet."""
    for t in trades:
        if t.pnl is None:
            t.pnl = _pnl(t)
        if t.rr_realized is None:
            t.rr_realized = _rr_realized(t)
        if t.rr_targeted is None:
            t.rr_targeted = _rr_targeted(t)
        if not t.winloss and t.pnl is not None:
            t.winloss = "Win" if t.pnl > 0 else ("Loss" if t.pnl < 0 else "BE")


def _bucket(trades, keyfn) -> list[dict]:
    groups = defaultdict(list)
    for t in trades:
        k = keyfn(t)
        if k is None or k == "":
            k = "(blank)"
        groups[k].append(t)
    rows = []
    for name, ts in groups.items():
        pnls = [_pnl(t) for t in ts if _pnl(t) is not None]
        if not pnls:
            continue
        wins = [p for p in pnls if p > 0]
        rows.append({
            "name": str(name), "n": len(pnls),
            "wins": len(wins), "win_rate": len(wins) / len(pnls),
            "total_pnl": sum(pnls),
            "expectancy": sum(pnls) / len(pnls),
        })
    rows.sort(key=lambda r: r["total_pnl"], reverse=True)
    return rows


def _hour_label(t):
    ts = t.timestamp
    return f"{ts.hour:02d}:00" if ts else None


_DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _dow_label(t):
    ts = t.timestamp
    return _DOW[ts.weekday()] if ts else None


def _drawdown(equity: list[float]) -> float:
    peak = float("-inf")
    mdd = 0.0
    for v in equity:
        peak = max(peak, v)
        mdd = min(mdd, v - peak)
    return mdd


def _streaks(seq: list[str]) -> tuple[int, int]:
    max_w = max_l = cur = 0
    last = None
    for s in seq:
        if s == last:
            cur += 1
        else:
            cur = 1
            last = s
        if s == "Win":
            max_w = max(max_w, cur)
        elif s == "Loss":
            max_l = max(max_l, cur)
    return max_w, max_l


def compute_metrics(trades) -> dict:
    trades = [t for t in trades if t.timestamp is not None]
    trades.sort(key=lambda t: t.timestamp)
    _ensure_derived(trades)
    pnls = [(_pnl(t) or 0.0) for t in trades]

    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    n = len(trades)
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))

    equity, run = [], 0.0
    for p in pnls:
        run += p
        equity.append(run)

    wl_seq = ["Win" if p > 0 else ("Loss" if p < 0 else "BE") for p in pnls]
    max_w, max_l = _streaks(wl_seq)

    rr_t = [t.rr_targeted for t in trades if t.rr_targeted is not None]
    rr_r = [t.rr_realized for t in trades if t.rr_realized is not None]

    summary = {
        "n_trades": n,
        "wins": len(wins), "losses": len(losses),
        "win_rate": (len(wins) / n) if n else 0.0,
        "total_pnl": sum(pnls),
        "avg_win": statistics.mean(wins) if wins else 0.0,
        "avg_loss": statistics.mean(losses) if losses else 0.0,
        "largest_win": max(wins) if wins else 0.0,
        "largest_loss": min(losses) if losses else 0.0,
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss else (
            float("inf") if gross_win else 0.0),
        "expectancy": (sum(pnls) / n) if n else 0.0,
        "avg_rr_targeted": round(statistics.mean(rr_t), 2) if rr_t else None,
        "avg_rr_realized": round(statistics.mean(rr_r), 2) if rr_r else None,
        "max_drawdown": _drawdown(equity),
        "max_win_streak": max_w, "max_loss_streak": max_l,
    }

    metrics = {
        "summary": summary,
        "equity_curve": [
            {"i": i + 1, "ts": t.timestamp.strftime("%m/%d %H:%M"),
             "cum": round(equity[i], 2), "pnl": round(pnls[i], 2),
             "asset": t.asset}
            for i, t in enumerate(trades)],
        "by_setup": _bucket(trades, lambda t: t.setup),
        "by_instrument": _bucket(trades, lambda t: t.asset),
        "by_direction": _bucket(trades, lambda t: t.direction),
        "by_hour": sorted(_bucket(trades, _hour_label), key=lambda r: r["name"]),
        "by_dayofweek": _bucket(trades, _dow_label),
        "behavior_flags": _behavior_flags(trades, pnls),
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "date_range": (f"{trades[0].timestamp.date()} → "
                       f"{trades[-1].timestamp.date()}") if trades else "",
    }
    return metrics


def _behavior_flags(trades, pnls) -> list[dict]:
    flags: list[dict] = []

    # 1. Overtrading days
    per_day = defaultdict(int)
    for t in trades:
        per_day[t.timestamp.date()] += 1
    over = {d: c for d, c in per_day.items() if c > config.OVERTRADING_PER_DAY}
    for d, c in sorted(over.items()):
        flags.append({"type": "Overtrading",
                      "detail": f"{c} trades on {d} (> {config.OVERTRADING_PER_DAY})"})

    # 2. Revenge trading: entered soon after a loss, same/larger size
    for i in range(1, len(trades)):
        prev, cur = trades[i - 1], trades[i]
        if (pnls[i - 1] < 0 and prev.size and cur.size):
            gap = (cur.timestamp - prev.timestamp).total_seconds() / 60.0
            if 0 <= gap <= config.REVENGE_WINDOW_MIN and \
               cur.size >= prev.size * config.REVENGE_SIZE_FACTOR:
                flags.append({
                    "type": "Possible revenge trade",
                    "detail": (f"{cur.asset} {cur.direction} at "
                               f"{cur.timestamp.strftime('%m/%d %H:%M')} — "
                               f"{gap:.0f} min after a loss, size {int(cur.size)}")})

    # 3. Stop overruns (loss worse than the stop implied)
    for t, p in zip(trades, pnls):
        if p < 0 and t.rr_realized is not None and \
           t.rr_realized < config.STOP_SLIPPAGE_RR:
            flags.append({
                "type": "Stop overrun",
                "detail": (f"{t.asset} {t.timestamp.strftime('%m/%d %H:%M')} "
                           f"realized RR {t.rr_realized:.2f} (worse than -1R)")})

    # 4. Cutting winners short
    for t, p in zip(trades, pnls):
        if (p > 0 and t.rr_realized is not None and t.rr_targeted
                and t.rr_realized < t.rr_targeted * config.CUT_WINNER_FRACTION):
            flags.append({
                "type": "Winner cut short",
                "detail": (f"{t.asset} {t.timestamp.strftime('%m/%d %H:%M')} "
                           f"took {t.rr_realized:.2f}R of {t.rr_targeted:.2f}R target")})

    # 5. Position-size inconsistency
    sizes = [t.size for t in trades if t.size]
    if len(sizes) >= config.MIN_SAMPLE_FOR_EDGE and statistics.mean(sizes):
        cv = statistics.pstdev(sizes) / statistics.mean(sizes)
        if cv > 0.5:
            flags.append({"type": "Inconsistent sizing",
                          "detail": f"Position size varies a lot (CV {cv:.2f})"})

    # 6. Negative-edge buckets
    for label, rows in (("setup", _bucket(trades, lambda t: t.setup)),
                        ("instrument", _bucket(trades, lambda t: t.asset)),
                        ("hour", _bucket(trades, _hour_label))):
        for r in rows:
            if r["n"] >= config.MIN_SAMPLE_FOR_EDGE and r["expectancy"] < 0:
                flags.append({
                    "type": f"Negative-edge {label}",
                    "detail": (f"{r['name']}: {r['n']} trades, "
                               f"{r['win_rate']*100:.0f}% win, "
                               f"${r['total_pnl']:.0f} total")})
    return flags
