"""Supertrend bot reporting — reads the per-strategy trade-log CSVs the bot writes
(supertrend_trades_<name>.csv) and produces TWO HTML reports:

  1) eod_report_<YYYYMMDD>.html   — End-of-day: each instrument's trades + P/L for that day.
  2) performance_report.html      — Cumulative to-date: each instrument's all-time metrics
                                     (net, PF, win%, drawdown, expectancy) + equity curve.

Pure standard library (no deps) so it runs anywhere the bot runs. Schedule it daily after the
session close; it always regenerates BOTH reports. CSVs are read from --dir (default: ./dist next
to this script, i.e. where the frozen bot runs), reports written to <dir>/reports/.

Usage:  python reports.py [--dir <trade_csv_dir>] [--date YYYY-MM-DD] [--capital 100000]
"""
import csv, os, sys, glob, argparse
from datetime import datetime, date

CSV_GLOB = "supertrend_trades_*.csv"


def find_dir(arg):
    here = os.path.dirname(os.path.abspath(__file__))
    for d in ([arg] if arg else []) + [os.path.join(here, "dist"), here]:
        if d and glob.glob(os.path.join(d, CSV_GLOB)):
            return d
    return arg or os.path.join(here, "dist")


def instrument_of(name):
    # "DU672616_MNQ_15m" -> "MNQ"; fall back to the whole name
    parts = name.split("_")
    return parts[1] if len(parts) >= 3 else name


def parse_dt(s):
    s = (s or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:19], fmt)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None


def load_all(csv_dir):
    """Return {instrument: [rows...]} sorted by time. Each row: dict with dt, side, qty, entry,
    exit, pnl, reason, strategy."""
    out = {}
    for path in sorted(glob.glob(os.path.join(csv_dir, CSV_GLOB))):
        strat = os.path.basename(path)[len("supertrend_trades_"):-4]
        inst = instrument_of(strat)
        rows = []
        try:
            with open(path, newline="") as f:
                for r in csv.DictReader(f):
                    dt = parse_dt(r.get("time"))
                    try:
                        pnl = float(r.get("pnl") or 0)
                    except ValueError:
                        pnl = 0.0
                    rows.append({"dt": dt, "side": r.get("side", ""), "qty": r.get("qty", ""),
                                 "entry": r.get("entry", ""), "exit": r.get("exit", ""),
                                 "pnl": pnl, "reason": r.get("reason", ""), "strategy": strat})
        except OSError:
            continue
        rows.sort(key=lambda x: x["dt"] or datetime.min)
        out.setdefault(inst, []).extend(rows)
    return out


def metrics(rows, capital):
    n = len(rows)
    if n == 0:
        return dict(trades=0, net=0.0, pf=0.0, win=0.0, avg_win=0.0, avg_loss=0.0,
                    exp=0.0, mdd=0.0, best=0.0, worst=0.0, eq=[capital])
    wins = [r["pnl"] for r in rows if r["pnl"] > 0]
    loss = [r["pnl"] for r in rows if r["pnl"] <= 0]
    gw = sum(wins); gl = abs(sum(loss))
    pf = (gw / gl) if gl > 0 else float("inf")
    net = sum(r["pnl"] for r in rows)
    eq = [capital]; acc = capital
    for r in rows:
        acc += r["pnl"]; eq.append(acc)
    peak = eq[0]; mdd = 0.0
    for e in eq:
        peak = max(peak, e); mdd = min(mdd, e - peak)
    return dict(trades=n, net=net, pf=pf, win=len(wins) / n * 100,
                avg_win=(gw / len(wins) if wins else 0), avg_loss=(sum(loss) / len(loss) if loss else 0),
                exp=net / n, mdd=mdd, best=max(r["pnl"] for r in rows), worst=min(r["pnl"] for r in rows), eq=eq)


def svg_eq(eq, capital, w=560, h=150):
    if len(eq) < 2:
        return "<span style='color:#888'>no closed trades yet</span>"
    lo, hi = min(eq), max(eq); rng = (hi - lo) or 1; pad = 26
    X = lambda i: pad + i * (w - 2 * pad) / (len(eq) - 1)
    Y = lambda v: h - pad - (v - lo) / rng * (h - 2 * pad)
    pts = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(eq))
    col = "#137333" if eq[-1] >= capital else "#c5221f"
    base = Y(capital)
    return (f"<svg viewBox='0 0 {w} {h}' width='100%' style='max-width:580px'>"
            f"<line x1='{pad}' y1='{base:.1f}' x2='{w-pad}' y2='{base:.1f}' stroke='#ccc' stroke-dasharray='4 3'/>"
            f"<polyline fill='none' stroke='{col}' stroke-width='1.8' points='{pts}'/></svg>")


CSS = """<style>body{font-family:Segoe UI,Arial,sans-serif;margin:24px;color:#202124}
h1{font-size:20px}h2{font-size:15px;margin-top:26px;border-bottom:2px solid #eee;padding-bottom:4px}
table{border-collapse:collapse;font-size:13px;margin:6px 0}th,td{border:1px solid #e0e0e0;padding:5px 9px;text-align:right}
th{background:#f1f3f4}td:first-child,th:first-child{text-align:left}
.pos{color:#137333;font-weight:600}.neg{color:#c5221f;font-weight:600}.muted{color:#777;font-size:12px}
.kpi{display:inline-block;min-width:120px;margin:4px 14px 4px 0}.kpi b{display:block;font-size:17px}</style>"""


def color(v):
    return "pos" if v >= 0 else "neg"


def eod_report(data, day, capital, out_dir):
    day_str = day.strftime("%Y-%m-%d")
    parts = [f"<!doctype html><meta charset='utf-8'><title>EOD {day_str}</title>{CSS}",
             f"<h1>Supertrend Bot &mdash; End-of-Day Report &middot; {day_str}</h1>",
             f"<p class='muted'>Trades closed on {day_str} (ET), per instrument. Generated {datetime.now():%Y-%m-%d %H:%M}.</p>"]
    grand = 0.0; any_rows = False
    # overview row
    ov = []
    for inst in sorted(data):
        todays = [r for r in data[inst] if r["dt"] and r["dt"].date() == day]
        net = sum(r["pnl"] for r in todays)
        if todays:
            any_rows = True; grand += net
        ov.append((inst, len(todays), net))
    parts.append("<h2>Overview</h2><table><tr><th>Instrument</th><th>Trades today</th><th>P/L today</th></tr>")
    for inst, n, net in ov:
        parts.append(f"<tr><td>{inst}</td><td>{n}</td><td class='{color(net)}'>${net:,.0f}</td></tr>")
    parts.append(f"<tr><td><b>TOTAL</b></td><td><b>{sum(n for _,n,_ in ov)}</b></td>"
                 f"<td class='{color(grand)}'><b>${grand:,.0f}</b></td></tr></table>")
    # per-instrument detail
    for inst in sorted(data):
        todays = [r for r in data[inst] if r["dt"] and r["dt"].date() == day]
        parts.append(f"<h2>{inst}</h2>")
        if not todays:
            parts.append("<p class='muted'>No trades closed today.</p>"); continue
        net = sum(r["pnl"] for r in todays); wins = sum(1 for r in todays if r["pnl"] > 0)
        parts.append(f"<div class='kpi'>P/L today<b class='{color(net)}'>${net:,.0f}</b></div>"
                     f"<div class='kpi'>Trades<b>{len(todays)}</b></div>"
                     f"<div class='kpi'>Winners<b>{wins}/{len(todays)}</b></div>")
        parts.append("<table><tr><th>Time</th><th>Side</th><th>Qty</th><th>Entry</th><th>Exit</th>"
                     "<th>Reason</th><th>P/L</th></tr>")
        for r in todays:
            t = r["dt"].strftime("%H:%M") if r["dt"] else ""
            parts.append(f"<tr><td>{t}</td><td>{r['side']}</td><td>{r['qty']}</td><td>{r['entry']}</td>"
                         f"<td>{r['exit']}</td><td>{r['reason']}</td><td class='{color(r['pnl'])}'>${r['pnl']:,.0f}</td></tr>")
        parts.append("</table>")
    if not any_rows:
        parts.insert(2, "<p class='neg'>No trades closed on this date across any instrument.</p>")
    path = os.path.join(out_dir, f"eod_report_{day.strftime('%Y%m%d')}.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(parts))
    return path


def perf_report(data, capital, out_dir):
    parts = [f"<!doctype html><meta charset='utf-8'><title>Performance to date</title>{CSS}",
             "<h1>Supertrend Bot &mdash; Performance To Date</h1>",
             f"<p class='muted'>Cumulative across all closed trades, per instrument. Start capital "
             f"${capital:,.0f}. Generated {datetime.now():%Y-%m-%d %H:%M}.</p>"]
    # summary table
    parts.append("<h2>Summary</h2><table><tr><th>Instrument</th><th>Since</th><th>Trades</th><th>Win%</th>"
                 "<th>PF</th><th>Net P/L</th><th>Avg win</th><th>Avg loss</th><th>Expectancy</th>"
                 "<th>Max DD</th><th>Best</th><th>Worst</th></tr>")
    total_net = 0.0; total_tr = 0; mets = {}
    for inst in sorted(data):
        rows = data[inst]; m = metrics(rows, capital); mets[inst] = m
        total_net += m["net"]; total_tr += m["trades"]
        since = ""
        d0 = next((r["dt"] for r in rows if r["dt"]), None)
        if d0: since = d0.strftime("%Y-%m-%d")
        pf_s = "&infin;" if m["pf"] == float("inf") else f"{m['pf']:.2f}"
        parts.append(f"<tr><td>{inst}</td><td>{since}</td><td>{m['trades']}</td><td>{m['win']:.1f}%</td>"
                     f"<td>{pf_s}</td><td class='{color(m['net'])}'>${m['net']:,.0f}</td>"
                     f"<td>${m['avg_win']:,.0f}</td><td>${m['avg_loss']:,.0f}</td><td>${m['exp']:,.0f}</td>"
                     f"<td class='neg'>${m['mdd']:,.0f}</td><td class='pos'>${m['best']:,.0f}</td>"
                     f"<td class='neg'>${m['worst']:,.0f}</td></tr>")
    parts.append(f"<tr><td colspan='2'><b>TOTAL</b></td><td><b>{total_tr}</b></td><td colspan='2'></td>"
                 f"<td class='{color(total_net)}'><b>${total_net:,.0f}</b></td><td colspan='6'></td></tr></table>")
    # equity curves
    parts.append("<h2>Equity curves (per instrument)</h2>")
    for inst in sorted(data):
        m = mets[inst]
        parts.append(f"<div style='margin:10px 0'><b>{inst}</b> &mdash; net "
                     f"<span class='{color(m['net'])}'>${m['net']:,.0f}</span>, end "
                     f"${m['eq'][-1]:,.0f}<br>{svg_eq(m['eq'], capital)}</div>")
    path = os.path.join(out_dir, "performance_report.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(parts))
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="")
    ap.add_argument("--date", default="")
    ap.add_argument("--capital", type=float, default=100000.0)
    a = ap.parse_args()
    csv_dir = find_dir(a.dir)
    out_dir = os.path.join(csv_dir, "reports"); os.makedirs(out_dir, exist_ok=True)
    day = datetime.strptime(a.date, "%Y-%m-%d").date() if a.date else date.today()
    data = load_all(csv_dir)
    if not data:
        print(f"No trade CSVs ({CSV_GLOB}) found in {csv_dir}. (Bot hasn't logged trades yet?)")
        # still emit empty-ish reports so the schedule doesn't error
    e = eod_report(data, day, a.capital, out_dir)
    p = perf_report(data, a.capital, out_dir)
    print("Trade CSV dir:", csv_dir)
    print("EOD report   :", e)
    print("Performance  :", p)
    for inst in sorted(data):
        m = metrics(data[inst], a.capital)
        pf_s = "inf" if m["pf"] == float("inf") else f"{m['pf']:.2f}"
        print(f"  {inst:<6} trades={m['trades']:<5} net=${m['net']:,.0f}  PF={pf_s}  win={m['win']:.1f}%")


if __name__ == "__main__":
    main()
