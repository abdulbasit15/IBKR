"""Build a self-contained TradeZella-style web app from the workbook.

Produces one standalone HTML file with the trade data and Chart.js inlined, so
it opens with a double-click and works offline. Screens: Dashboard, Trades,
Daily Journal, Reports, Playbooks, Progress, Notebook.
"""
from __future__ import annotations

import json
import statistics
from datetime import datetime
from pathlib import Path

from . import analytics, autotag, config, excel_io, market, news as news_mod

_TEMPLATE = Path(__file__).parent / "templates" / "app.html"
_CHARTJS = Path(__file__).parent / "vendor" / "chart.min.js"


def _daily(trades) -> list[dict]:
    from collections import defaultdict
    agg = defaultdict(lambda: {"pnl": 0.0, "n": 0, "wins": 0})
    for t in trades:
        p = t.pnl or 0.0
        d = str(t.timestamp.date())
        a = agg[d]
        a["pnl"] += p
        a["n"] += 1
        a["wins"] += 1 if p > 0 else 0
    out = []
    for d in sorted(agg):
        a = agg[d]
        out.append({"date": d, "pnl": round(a["pnl"], 2), "n": a["n"],
                    "win_rate": (a["wins"] / a["n"]) if a["n"] else 0})
    return out


def _clamp(x, lo=0.0, hi=100.0):
    return max(lo, min(hi, x))


def _zella(summary, daily) -> dict:
    """A 0-100 composite score (approximation of TradeZella's Zella Score)."""
    win = _clamp(summary["win_rate"] * 100)
    pf = summary["profit_factor"]
    pf_s = 100.0 if pf == float("inf") else _clamp(pf / 3 * 100)
    awl = (summary["avg_win"] / abs(summary["avg_loss"])) if summary["avg_loss"] else 0
    awl_s = _clamp(awl / 2 * 100)
    net = summary["total_pnl"]
    dd = abs(summary["max_drawdown"]) or 1
    recovery = net / dd
    rec_s = _clamp(recovery / 3 * 100)
    # Consistency: how steady daily P&L is (lower relative volatility = higher).
    pnls = [d["pnl"] for d in daily] or [0]
    mean = statistics.mean(pnls)
    sd = statistics.pstdev(pnls) if len(pnls) > 1 else 0
    cv = (sd / abs(mean)) if mean else (1 if sd else 0)
    cons_s = _clamp(100 - cv * 30)
    max_dd_s = _clamp(100 - (dd / (abs(net) + dd)) * 100)
    comps = {"Win %": round(win), "Profit factor": round(pf_s),
             "Avg win/loss": round(awl_s), "Max drawdown": round(max_dd_s),
             "Recovery factor": round(rec_s), "Consistency": round(cons_s)}
    weights = {"Win %": .2, "Profit factor": .2, "Avg win/loss": .15,
               "Max drawdown": .15, "Recovery factor": .15, "Consistency": .15}
    score = sum(comps[k] * weights[k] for k in comps)
    return {"score": round(score, 1), "components": comps,
            "avg_win_loss": round(awl, 2), "recovery_factor": round(recovery, 2)}


def _trade_dict(t) -> dict:
    ts = t.timestamp
    return {
        "date": str(ts.date()), "time": ts.strftime("%H:%M"),
        "mins": ts.hour * 60 + ts.minute,
        "dow": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][ts.weekday()],
        "asset": t.asset, "direction": t.direction,
        "entry": t.entry, "exit": t.exit, "size": int(t.size) if t.size else None,
        "stop": t.stop, "target": t.target,
        "rr_targeted": round(t.rr_targeted, 2) if t.rr_targeted is not None else None,
        "rr_realized": round(t.rr_realized, 2) if t.rr_realized is not None else None,
        "pnl": round(t.pnl, 2) if t.pnl is not None else None,
        "winloss": t.winloss, "setup": t.setup or "", "notes": t.notes or "",
        "chart": t.trade_screenshot or "", "level": t.instrument_level or "",
    }


def build_data(trades, ai_text: str = "", with_intraday: bool = True) -> dict:
    trades = [t for t in trades if t.timestamp is not None]
    trades.sort(key=lambda t: t.timestamp)

    # Market + intraday context, then auto-tag any untagged setups in-memory.
    intraday = market.summarize_intraday(trades) if with_intraday else {}
    market_days = market.summarize_days(trades)
    news_week = news_mod.all_events()          # all currencies/impacts; filtered in-app
    news_window = news_mod.feed_window()
    trade_dates = sorted({str(t.timestamp.date()) for t in trades})
    events_by_day = news_mod.major_events_by_day(trade_dates)  # historical (Nasdaq)
    labels = autotag.autotag(trades, intraday or None, market_days)
    auto_flag = {}
    for i, t in enumerate(trades):
        if not t.setup and labels.get(i):
            t.setup = labels[i]
            auto_flag[i] = True

    metrics = analytics.compute_metrics(trades)   # mutates: fills pnl/rr
    s = metrics["summary"]
    daily = _daily(trades)

    cum = 0.0
    equity = []
    for i, t in enumerate(trades):
        cum += (t.pnl or 0.0)
        equity.append({"i": i + 1, "date": str(t.timestamp.date()),
                       "cum": round(cum, 2), "pnl": round(t.pnl or 0, 2)})

    tdicts = []
    for i, t in enumerate(trades):
        d = _trade_dict(t)
        d["id"] = i
        d["entry_ep"] = market.et_epoch(t.timestamp)
        d["setup_auto"] = auto_flag.get(i, False)
        tdicts.append(d)
    winners = [t["pnl"] for t in tdicts if (t["pnl"] or 0) > 0]
    losers = [t["pnl"] for t in tdicts if (t["pnl"] or 0) < 0]

    return {
        "generated_at": metrics["generated_at"],
        "date_range": metrics["date_range"],
        "currency": "$",
        "summary": {
            **s,
            "avg_win_loss": round((s["avg_win"] / abs(s["avg_loss"]))
                                  if s["avg_loss"] else 0, 2),
            "best_day": max((d["pnl"] for d in daily), default=0),
            "worst_day": min((d["pnl"] for d in daily), default=0),
            "green_days": sum(1 for d in daily if d["pnl"] > 0),
            "red_days": sum(1 for d in daily if d["pnl"] < 0),
            "total_days": len(daily),
            "avg_daily": round(statistics.mean([d["pnl"] for d in daily]), 2) if daily else 0,
            "biggest_win": max(winners, default=0),
            "biggest_loss": min(losers, default=0),
        },
        "zella": _zella(s, daily),
        "equity_curve": equity,
        "daily": daily,
        "trades": tdicts,
        "by_instrument": metrics["by_instrument"],
        "by_setup": metrics["by_setup"],
        "by_direction": metrics["by_direction"],
        "by_hour": metrics["by_hour"],
        "by_dayofweek": metrics["by_dayofweek"],
        "behavior_flags": metrics["behavior_flags"],
        "intraday": intraday,
        "market_days": {f"{a}|{d}": v for (a, d), v in market_days.items() if v},
        "news_week": news_week,
        "news_window": news_window,
        "events_by_day": events_by_day,
        "ai_text": ai_text or "",
    }


def build_app(workbook: Path | None = None, ai_text: str = "",
              out: Path | None = None) -> Path:
    trades = excel_io.read_trades(workbook)
    if not trades:
        raise SystemExit("No trades found in the workbook.")
    data = build_data(trades, ai_text)

    template = _TEMPLATE.read_text(encoding="utf-8")
    chartjs = _CHARTJS.read_text(encoding="utf-8") if _CHARTJS.exists() else ""
    payload = json.dumps(data, default=str)

    html = (template
            .replace("/*__CHARTJS__*/", chartjs)
            .replace("/*__DATA__*/", payload))

    config.REPORTS_DIR.mkdir(exist_ok=True)
    out = out or (config.REPORTS_DIR / "TradeJournal.html")
    out.write_text(html, encoding="utf-8")
    return out
