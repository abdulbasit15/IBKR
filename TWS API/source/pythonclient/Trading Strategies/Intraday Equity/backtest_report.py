"""
Backtest report generator for Intraday Equity strategies.
Reads the existing .xlsx trade logs, computes rolling-window stats,
per-ticker breakdowns, and writes a consolidated summary report.

Usage:
    python backtest_report.py [--days N]   (default N=30 for last-30 trading-day window)
"""
from __future__ import annotations

import argparse
import os
from collections import defaultdict
from datetime import datetime, timedelta

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

REPORT_DIR   = os.path.join(os.path.dirname(__file__), "reports")
REPORT_FILES = {
    "ORB SIP - 9.35": "backtest_ORB_SIP___9_35.xlsx",
    "NR7 - 9.35":     "backtest_NR7___9_35.xlsx",
    "PDH - 9.35":     "backtest_PDH___9_35.xlsx",
}
CAPITAL = 100_000
RISK_PER_TRADE = 1_000   # 1% of capital

COLS = ["Date","Time","Strategy","Ticker","Sector","Shares","Entry","Stop",
        "Target","Exit","PnL","R_Multiple","Result","Reason","HoldMin"]


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def load_trades(strategy_name: str, filename: str) -> list[dict]:
    path = os.path.join(REPORT_DIR, filename)
    if not os.path.exists(path):
        return []
    wb = openpyxl.load_workbook(path)
    ws = wb["Trades"]
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []
    hdr = rows[0]
    trades = []
    for r in rows[1:]:
        row = dict(zip(hdr, r))
        if row.get("Date"):
            trades.append(row)
    return trades


def filter_window(trades: list[dict], days: int | None) -> list[dict]:
    if not days or not trades:
        return trades
    dates = sorted({str(t["Date"]) for t in trades if t.get("Date")})
    if len(dates) <= days:
        return trades
    cutoff = dates[-days]
    return [t for t in trades if str(t.get("Date","")) >= cutoff]


def compute_metrics(trades: list[dict]) -> dict:
    if not trades:
        return {}
    n = len(trades)
    pnls = [_f(t.get("PnL")) for t in trades]
    rmults = [_f(t.get("R_Multiple")) for t in trades]
    wins  = [p for p in pnls if p > 0]
    losses= [p for p in pnls if p < 0]
    gross_win  = sum(wins)
    gross_loss = abs(sum(losses))
    pf = round(gross_win / gross_loss, 3) if gross_loss > 0 else ("∞" if gross_win > 0 else 0)
    total_pnl  = sum(pnls)

    # max drawdown (sequential running sum)
    peak = 0.0; dd_max = 0.0; running = 0.0
    for p in pnls:
        running += p
        if running > peak:
            peak = running
        dd = peak - running
        if dd > dd_max:
            dd_max = dd

    # consecutive wins / losses
    best_streak = worst_streak = cur_w = cur_l = 0
    for p in pnls:
        if p > 0:
            cur_w += 1; cur_l = 0
        elif p < 0:
            cur_l += 1; cur_w = 0
        else:
            cur_w = cur_l = 0
        best_streak  = max(best_streak, cur_w)
        worst_streak = max(worst_streak, cur_l)

    days_set = {str(t.get("Date","")) for t in trades if t.get("Date")}

    return {
        "trading_days":      len(days_set),
        "total_trades":      n,
        "wins":              len(wins),
        "losses":            len(losses),
        "win_rate_pct":      round(100 * len(wins) / n, 1) if n else 0,
        "total_pnl":         round(total_pnl, 2),
        "return_on_capital": f"{round(100 * total_pnl / CAPITAL, 2)}%",
        "avg_pnl":           round(total_pnl / n, 2) if n else 0,
        "avg_r":             round(sum(rmults) / n, 3) if n else 0,
        "profit_factor":     pf,
        "gross_win":         round(gross_win, 2),
        "gross_loss":        round(gross_loss, 2),
        "largest_win":       round(max(pnls, default=0), 2),
        "largest_loss":      round(min(pnls, default=0), 2),
        "max_drawdown":      round(dd_max, 2),
        "best_streak":       best_streak,
        "worst_streak":      worst_streak,
        "stops_pct":         round(100 * sum(1 for t in trades if str(t.get("Reason","")).upper() in ("STOP","STOPLIMIT")) / n, 1) if n else 0,
        "targets_pct":       round(100 * sum(1 for t in trades if str(t.get("Reason","")).upper() == "TARGET") / n, 1) if n else 0,
        "eod_pct":           round(100 * sum(1 for t in trades if str(t.get("Reason","")).upper() == "EOD") / n, 1) if n else 0,
    }


def daily_breakdown(trades: list[dict]) -> list[dict]:
    g = defaultdict(list)
    for t in trades:
        g[str(t.get("Date",""))].append(t)
    rows = []
    for d in sorted(g):
        ts = g[d]; n = len(ts)
        pnls = [_f(t.get("PnL")) for t in ts]
        wins = sum(1 for p in pnls if p > 0)
        rows.append({
            "Date":      d,
            "Trades":    n,
            "Wins":      wins,
            "Losses":    n - wins,
            "WinRate%":  round(100 * wins / n, 1) if n else 0,
            "GrossPnL":  round(sum(pnls), 2),
            "AvgR":      round(sum(_f(t.get("R_Multiple")) for t in ts) / n, 3) if n else 0,
        })
    return rows


def ticker_breakdown(trades: list[dict]) -> list[dict]:
    g = defaultdict(list)
    for t in trades:
        g[str(t.get("Ticker",""))].append(t)
    rows = []
    for tk in sorted(g):
        ts = g[tk]; n = len(ts)
        pnls = [_f(t.get("PnL")) for t in ts]
        wins = sum(1 for p in pnls if p > 0)
        rows.append({
            "Ticker":   tk,
            "Trades":   n,
            "Wins":     wins,
            "Losses":   n - wins,
            "WinRate%": round(100 * wins / n, 1) if n else 0,
            "GrossPnL": round(sum(pnls), 2),
            "AvgR":     round(sum(_f(t.get("R_Multiple")) for t in ts) / n, 3) if n else 0,
        })
    return sorted(rows, key=lambda r: r["GrossPnL"], reverse=True)


# ── Excel helpers ──────────────────────────────────────────────────────────────

HDR_FILL   = PatternFill("solid", fgColor="1F4E79")
HDR_FONT   = Font(bold=True, color="FFFFFF", size=10)
SECT_FILL  = PatternFill("solid", fgColor="2E75B6")
SECT_FONT  = Font(bold=True, color="FFFFFF", size=11)
WIN_FILL   = PatternFill("solid", fgColor="E2EFDA")
LOSS_FILL  = PatternFill("solid", fgColor="FCE4D6")
ALT_FILL   = PatternFill("solid", fgColor="EBF3FB")
THIN       = Side(style="thin", color="BFBFBF")
BORDER     = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
CENTER     = Alignment(horizontal="center")


def _hdr(ws, row, cols):
    for c, val in enumerate(cols, 1):
        cell = ws.cell(row=row, column=c, value=val)
        cell.fill = HDR_FILL; cell.font = HDR_FONT
        cell.alignment = CENTER; cell.border = BORDER


def _row(ws, r, vals, fill=None, bold=False):
    for c, v in enumerate(vals, 1):
        cell = ws.cell(row=r, column=c, value=v)
        cell.border = BORDER
        if fill:
            cell.fill = fill
        if bold:
            cell.font = Font(bold=True, size=10)
        if c > 1:
            cell.alignment = CENTER


def _section(ws, row, label, ncols):
    cell = ws.cell(row=row, column=1, value=label)
    cell.fill = SECT_FILL; cell.font = SECT_FONT
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=ncols)


def autofit(ws, min_w=8, max_w=30):
    for col in ws.columns:
        width = max(len(str(c.value or "")) for c in col)
        ws.column_dimensions[get_column_letter(col[0].column)].width = max(min_w, min(width + 3, max_w))


# ── Main report writer ─────────────────────────────────────────────────────────

def build_report(days: int | None) -> str:
    all_strategies: dict[str, dict] = {}

    for strat, fname in REPORT_FILES.items():
        trades_raw = load_trades(strat, fname)
        trades = filter_window(trades_raw, days)
        if trades:
            all_strategies[strat] = {
                "trades":   trades,
                "metrics":  compute_metrics(trades),
                "daily":    daily_breakdown(trades),
                "by_ticker": ticker_breakdown(trades),
                "date_range": (min(str(t["Date"]) for t in trades),
                               max(str(t["Date"]) for t in trades)),
            }

    out_path = os.path.join(REPORT_DIR, "consolidated_backtest.xlsx")
    wb = openpyxl.Workbook()

    # ── Sheet 1: Executive Summary ────────────────────────────────────────────
    ws = wb.active
    ws.title = "Summary"

    # title
    ws.merge_cells("A1:J1")
    title = ws["A1"]
    title.value = "Intraday Equity Strategy - Backtest Performance Summary"
    title.font = Font(bold=True, size=14, color="1F4E79")
    title.alignment = CENTER

    ws.merge_cells("A2:J2")
    sub = ws["A2"]
    period_parts = []
    for d in all_strategies.values():
        period_parts.extend(d["date_range"])
    if period_parts:
        sub.value = f"Period: {min(period_parts)}  to  {max(period_parts)}    |    Window: last {days or 'all'} trading days    |    Capital: ${CAPITAL:,} per strategy"
    sub.font = Font(italic=True, size=10, color="595959")
    sub.alignment = CENTER

    row = 4
    strat_cols = ["Strategy", "Days", "Trades", "Wins", "Losses",
                  "Win%", "Total P/L", "Return%", "Avg R", "Prof. Factor",
                  "Largest Win", "Largest Loss", "Max DD", "Stop%", "Target%"]
    _hdr(ws, row, strat_cols)
    row += 1

    for i, (sname, sd) in enumerate(all_strategies.items()):
        m = sd["metrics"]
        dr = sd["date_range"]
        pnl = m["total_pnl"]
        vals = [
            sname,
            f'{dr[0]} → {dr[1]}',
            m["total_trades"],
            m["wins"],
            m["losses"],
            f'{m["win_rate_pct"]}%',
            f'${pnl:,.2f}',
            m["return_on_capital"],
            m["avg_r"],
            m["profit_factor"],
            f'${m["largest_win"]:,.2f}',
            f'${m["largest_loss"]:,.2f}',
            f'${m["max_drawdown"]:,.2f}',
            f'{m["stops_pct"]}%',
            f'{m["targets_pct"]}%',
        ]
        fill = WIN_FILL if pnl > 0 else (LOSS_FILL if pnl < 0 else None)
        _row(ws, row, vals, fill=fill)
        row += 1

    # Combined stats
    row += 1
    all_trades = [t for sd in all_strategies.values() for t in sd["trades"]]
    if all_trades:
        cm = compute_metrics(all_trades)
        _section(ws, row, "COMBINED (all strategies)", len(strat_cols))
        row += 1
        _hdr(ws, row, ["Metric", "Value"])
        row += 1
        combined_rows = [
            ("Total trades",     cm["total_trades"]),
            ("Wins",             cm["wins"]),
            ("Losses",           cm["losses"]),
            ("Win rate",         f'{cm["win_rate_pct"]}%'),
            ("Total P/L",        f'${cm["total_pnl"]:,.2f}'),
            ("Avg P/L / trade",  f'${cm["avg_pnl"]:,.2f}'),
            ("Avg R multiple",   cm["avg_r"]),
            ("Profit factor",    cm["profit_factor"]),
            ("Max drawdown",     f'${cm["max_drawdown"]:,.2f}'),
            ("Best win streak",  cm["best_streak"]),
            ("Worst loss streak",cm["worst_streak"]),
        ]
        for i, (k, v) in enumerate(combined_rows):
            fill = ALT_FILL if i % 2 == 0 else None
            _row(ws, row, [k, v], fill=fill)
            row += 1

    autofit(ws)

    # ── Sheets per strategy ───────────────────────────────────────────────────
    for sname, sd in all_strategies.items():
        safe_name = sname.replace(" ","_").replace("/","_")[:28]

        # --- Trades tab ---
        ws_t = wb.create_sheet(f"{safe_name[:20]}_Trades")
        _hdr(ws_t, 1, COLS)
        for i, t in enumerate(sd["trades"], 2):
            vals = [t.get(c, "") for c in COLS]
            pnl = _f(t.get("PnL"))
            fill = WIN_FILL if pnl > 0 else (LOSS_FILL if pnl < 0 else None)
            _row(ws_t, i, vals, fill=fill)
        autofit(ws_t)

        # --- Daily tab ---
        ws_d = wb.create_sheet(f"{safe_name[:20]}_Daily")
        daily_hdr = ["Date","Trades","Wins","Losses","WinRate%","GrossPnL","AvgR"]
        _hdr(ws_d, 1, daily_hdr)
        for i, d in enumerate(sd["daily"], 2):
            vals = [d[c] for c in daily_hdr]
            fill = WIN_FILL if d["GrossPnL"] > 0 else (LOSS_FILL if d["GrossPnL"] < 0 else None)
            _row(ws_d, i, vals, fill=fill)
        autofit(ws_d)

        # --- ByTicker tab ---
        ws_bt = wb.create_sheet(f"{safe_name[:18]}_Tickers")
        tk_hdr = ["Ticker","Trades","Wins","Losses","WinRate%","GrossPnL","AvgR"]
        _hdr(ws_bt, 1, tk_hdr)
        for i, tk in enumerate(sd["by_ticker"], 2):
            vals = [tk[c] for c in tk_hdr]
            fill = WIN_FILL if tk["GrossPnL"] > 0 else (LOSS_FILL if tk["GrossPnL"] < 0 else None)
            _row(ws_bt, i, vals, fill=fill)
        autofit(ws_bt)

    wb.save(out_path)
    return out_path


def print_console_report(days: int | None):
    """Print a concise text summary to stdout."""
    DIVIDER = "=" * 65

    all_strategies: dict[str, dict] = {}
    for strat, fname in REPORT_FILES.items():
        trades_raw = load_trades(strat, fname)
        trades = filter_window(trades_raw, days)
        if trades:
            all_strategies[strat] = {
                "trades":    trades,
                "metrics":   compute_metrics(trades),
                "daily":     daily_breakdown(trades),
                "by_ticker": ticker_breakdown(trades),
                "date_range":(min(str(t["Date"]) for t in trades),
                              max(str(t["Date"]) for t in trades)),
            }

    all_trades = [t for sd in all_strategies.values() for t in sd["trades"]]
    period_parts = []
    for d in all_strategies.values():
        period_parts.extend(d["date_range"])

    print(f"\n{DIVIDER}")
    print("  INTRADAY EQUITY STRATEGIES - BACKTEST PERFORMANCE")
    if period_parts:
        print(f"  Period: {min(period_parts)}  to  {max(period_parts)}")
    print(f"  Capital per strategy: ${CAPITAL:,}  |  Risk/trade: ${RISK_PER_TRADE:,} (1%)")
    print(DIVIDER)

    for sname, sd in all_strategies.items():
        m = sd["metrics"]
        dr = sd["date_range"]
        pnl = m["total_pnl"]
        avg_pnl = m["avg_pnl"]
        lw = m["largest_win"]
        ll = m["largest_loss"]
        print(f"\n  >> {sname}")
        print(f"     Data range  : {dr[0]} to {dr[1]}")
        print(f"     Trades      : {m['total_trades']}  ({m['wins']}W / {m['losses']}L)  Win rate: {m['win_rate_pct']}%")
        print(f"     Total P/L   : {pnl:+,.2f}  ({m['return_on_capital']} on ${CAPITAL:,})")
        print(f"     Avg R/trade : {m['avg_r']:+.3f}   Avg P/L: {avg_pnl:+,.2f}")
        print(f"     Prof.Factor : {m['profit_factor']}  Max DD: ${m['max_drawdown']:,.2f}")
        print(f"     Exit mix    : Stop {m['stops_pct']}%  /  Target {m['targets_pct']}%  /  EOD {m['eod_pct']}%")
        print(f"     Best streak : {m['best_streak']}W   Worst streak: {m['worst_streak']}L")
        print(f"     Largest win : {lw:+,.2f}   Largest loss: {ll:+,.2f}")

        # top/bottom 3 tickers
        bt = sd["by_ticker"]
        if bt:
            top3  = bt[:3]
            bot3  = bt[-3:][::-1]
            print(f"     Top tickers : " +
                  "  ".join(f"{r['Ticker']} {'+' if r['GrossPnL']>=0 else ''}${r['GrossPnL']:,.0f}" for r in top3))
            print(f"     Bot tickers : " +
                  "  ".join(f"{r['Ticker']} ${r['GrossPnL']:,.0f}" for r in bot3))

        # daily summary
        print(f"     Daily P/L   :", end="")
        for dd in sd["daily"]:
            mark = "+" if dd["GrossPnL"] > 0 else ""
            print(f"  {dd['Date'][5:]}:{mark}${dd['GrossPnL']:,.0f}", end="")
        print()

    # Combined
    if all_trades:
        cm = compute_metrics(all_trades)
        combined_pnl = cm["total_pnl"]
        print(f"\n{DIVIDER}")
        print(f"  COMBINED ALL STRATEGIES")
        print(f"  Total trades : {cm['total_trades']}  ({cm['wins']}W / {cm['losses']}L)  Win rate: {cm['win_rate_pct']}%")
        print(f"  Total P/L    : {combined_pnl:+,.2f}  across ${CAPITAL*3:,} deployed")
        print(f"  Avg R/trade  : {cm['avg_r']:+.3f}   Profit factor: {cm['profit_factor']}")
        print(f"  Max drawdown : ${cm['max_drawdown']:,.2f}")
        print(DIVIDER)

    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Intraday Equity backtest reporter")
    parser.add_argument("--days", type=int, default=None,
                        help="Restrict to last N trading days (default: all available)")
    args = parser.parse_args()

    print_console_report(args.days)
    out = build_report(args.days)
    print(f"  Excel report saved: {out}\n")
