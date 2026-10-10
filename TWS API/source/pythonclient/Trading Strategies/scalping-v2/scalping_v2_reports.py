"""Scalping v2 bot reporting — same layout/logic as the supertrend bot's reports.py.

Reads the per-strategy trade CSVs the bot writes (scalping_v2_trades_<account>_<symbol>_<strategy>.csv,
supertrend column format) and produces TWO HTML reports in <dir>/reports/:

  1) eod_report_<YYYYMMDD>.html   — End-of-day: trades + P/L closed that day, per instrument and per strategy.
  2) performance_report.html      — Cumulative to date: net, PF, win%, drawdown, expectancy, avg R + equity curves.

Pure standard library. The bot calls build() automatically after each session (16:05 ET); run it manually any
time with  scalping_v2_bot.exe --reports [--date YYYY-MM-DD]  or  .\\scalping.ps1 -Reports.

Usage:  python scalping_v2_reports.py [--dir <trade_csv_dir>] [--date YYYY-MM-DD] [--capital 150000]
"""
import argparse
import csv
import glob
import os
from datetime import date, datetime

PREFIX = "scalping_v2_trades_"
CSV_GLOB = PREFIX + "*.csv"


def find_dir(arg):
    here = os.path.dirname(os.path.abspath(__file__))
    for d in ([arg] if arg else []) + [os.path.join(here, "dist"), here]:
        if d and glob.glob(os.path.join(d, CSV_GLOB)):
            return d
    return arg or os.path.join(here, "dist")


def split_name(name):
    """'DU672616_NQ_ib_trend' -> ('DU672616', 'NQ', 'ib_trend')."""
    parts = name.split("_", 2)
    return (parts[0], parts[1], parts[2]) if len(parts) == 3 else ("", name, name)


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


def _f(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def load_all(csv_dir):
    """Return list of closed-trade rows (dicts) sorted by exit time."""
    rows = []
    for path in sorted(glob.glob(os.path.join(csv_dir, CSV_GLOB))):
        name = os.path.basename(path)[len(PREFIX):-4]
        acct, sym, strat = split_name(name)
        try:
            with open(path, newline="", encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    rows.append({"dt": parse_dt(r.get("time")), "name": name, "account": r.get("account", acct),
                                 "symbol": r.get("symbol", sym), "strategy": strat, "side": r.get("side", ""),
                                 "qty": r.get("qty", ""), "entry": r.get("entry", ""), "exit": r.get("exit", ""),
                                 "stop": r.get("stop", ""), "pnl": _f(r.get("pnl")), "r": _f(r.get("r_mult"), None),
                                 "reason": r.get("reason", ""), "hold": r.get("hold", ""),
                                 "entry_time": r.get("entry_time", "")})
        except OSError:
            continue
    rows.sort(key=lambda x: x["dt"] or datetime.min)
    return rows


def metrics(rows, capital):
    n = len(rows)
    if n == 0:
        return dict(trades=0, net=0.0, pf=0.0, win=0.0, avg_win=0.0, avg_loss=0.0, exp=0.0, mdd=0.0,
                    best=0.0, worst=0.0, avg_r=0.0, eq=[capital])
    wins = [r["pnl"] for r in rows if r["pnl"] > 0]
    loss = [r["pnl"] for r in rows if r["pnl"] <= 0]
    gw, gl = sum(wins), abs(sum(loss))
    net = sum(r["pnl"] for r in rows)
    eq, acc = [capital], capital
    for r in rows:
        acc += r["pnl"]
        eq.append(acc)
    peak, mdd = eq[0], 0.0
    for e in eq:
        peak = max(peak, e)
        mdd = min(mdd, e - peak)
    rs = [r["r"] for r in rows if r["r"] is not None]
    return dict(trades=n, net=net, pf=(gw / gl) if gl > 0 else float("inf"), win=len(wins) / n * 100,
                avg_win=(gw / len(wins) if wins else 0), avg_loss=(sum(loss) / len(loss) if loss else 0),
                exp=net / n, mdd=mdd, best=max(r["pnl"] for r in rows), worst=min(r["pnl"] for r in rows),
                avg_r=(sum(rs) / len(rs) if rs else 0.0), eq=eq)


def svg_eq(eq, capital, w=560, h=150):
    if len(eq) < 2:
        return "<span style='color:#888'>no closed trades yet</span>"
    lo, hi = min(eq), max(eq)
    rng, pad = (hi - lo) or 1, 26
    X = lambda i: pad + i * (w - 2 * pad) / (len(eq) - 1)
    Y = lambda v: h - pad - (v - lo) / rng * (h - 2 * pad)
    pts = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(eq))
    col = "#137333" if eq[-1] >= capital else "#c5221f"
    base = Y(capital)
    return (f"<svg viewBox='0 0 {w} {h}' width='100%' style='max-width:580px'>"
            f"<line x1='{pad}' y1='{base:.1f}' x2='{w - pad}' y2='{base:.1f}' stroke='#ccc' stroke-dasharray='4 3'/>"
            f"<polyline fill='none' stroke='{col}' stroke-width='1.8' points='{pts}'/></svg>")


CSS = """<style>body{font-family:Segoe UI,Arial,sans-serif;margin:24px;color:#202124}
h1{font-size:20px}h2{font-size:15px;margin-top:26px;border-bottom:2px solid #eee;padding-bottom:4px}
table{border-collapse:collapse;font-size:13px;margin:6px 0}th,td{border:1px solid #e0e0e0;padding:5px 9px;text-align:right}
th{background:#f1f3f4}td:first-child,th:first-child{text-align:left}
.pos{color:#137333;font-weight:600}.neg{color:#c5221f;font-weight:600}.muted{color:#777;font-size:12px}
.kpi{display:inline-block;min-width:120px;margin:4px 14px 4px 0}.kpi b{display:block;font-size:17px}</style>"""


def color(v):
    return "pos" if v >= 0 else "neg"


def _group(rows, key):
    out = {}
    for r in rows:
        out.setdefault(r[key], []).append(r)
    return out


def eod_report(rows, day, capital, out_dir):
    day_str = day.strftime("%Y-%m-%d")
    todays = [r for r in rows if r["dt"] and r["dt"].date() == day]
    parts = [f"<!doctype html><meta charset='utf-8'><title>EOD {day_str}</title>{CSS}",
             f"<h1>Scalping v2 Bot &mdash; End-of-Day Report &middot; {day_str}</h1>",
             f"<p class='muted'>Trades closed on {day_str} (ET), per instrument and per strategy. "
             f"P/L in $ net of commission. Generated {datetime.now():%Y-%m-%d %H:%M}.</p>"]
    if not todays:
        parts.append("<p class='neg'>No trades closed on this date across any instrument.</p>")
    grand = sum(r["pnl"] for r in todays)
    for title, key in (("Overview by instrument", "symbol"), ("Overview by strategy", "strategy")):
        g = _group(todays, key)
        keys = sorted(set(g) | {r[key] for r in rows})
        parts.append(f"<h2>{title}</h2><table><tr><th>{key.title()}</th><th>Trades today</th><th>Winners</th><th>P/L today</th></tr>")
        for k in keys:
            t = g.get(k, [])
            net = sum(r["pnl"] for r in t)
            parts.append(f"<tr><td>{k}</td><td>{len(t)}</td><td>{sum(1 for r in t if r['pnl'] > 0)}</td>"
                         f"<td class='{color(net)}'>${net:,.0f}</td></tr>")
        parts.append(f"<tr><td><b>TOTAL</b></td><td><b>{len(todays)}</b></td><td></td>"
                     f"<td class='{color(grand)}'><b>${grand:,.0f}</b></td></tr></table>")
    for name in sorted({r["name"] for r in rows}):
        t = [r for r in todays if r["name"] == name]
        _, sym, strat = split_name(name)
        parts.append(f"<h2>{sym} &middot; {strat} <span class='muted'>({name})</span></h2>")
        if not t:
            parts.append("<p class='muted'>No trades closed today.</p>")
            continue
        net = sum(r["pnl"] for r in t)
        parts.append(f"<div class='kpi'>P/L today<b class='{color(net)}'>${net:,.0f}</b></div>"
                     f"<div class='kpi'>Trades<b>{len(t)}</b></div>"
                     f"<div class='kpi'>Winners<b>{sum(1 for r in t if r['pnl'] > 0)}/{len(t)}</b></div>")
        parts.append("<table><tr><th>Entry</th><th>Exit</th><th>Side</th><th>Qty</th><th>Entry px</th><th>Exit px</th>"
                     "<th>Stop</th><th>Reason</th><th>R</th><th>Hold</th><th>P/L</th></tr>")
        for r in t:
            et = (r["entry_time"] or "")[11:16]
            xt = r["dt"].strftime("%H:%M") if r["dt"] else ""
            rr = f"{r['r']:+.2f}" if r["r"] is not None else ""
            parts.append(f"<tr><td>{et}</td><td>{xt}</td><td>{r['side']}</td><td>{r['qty']}</td><td>{r['entry']}</td>"
                         f"<td>{r['exit']}</td><td>{r['stop']}</td><td>{r['reason']}</td><td>{rr}</td><td>{r['hold']}</td>"
                         f"<td class='{color(r['pnl'])}'>${r['pnl']:,.0f}</td></tr>")
        parts.append("</table>")
    path = os.path.join(out_dir, f"eod_report_{day.strftime('%Y%m%d')}.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(parts))
    return path


def perf_report(rows, capital, out_dir):
    parts = [f"<!doctype html><meta charset='utf-8'><title>Performance to date</title>{CSS}",
             "<h1>Scalping v2 Bot &mdash; Performance To Date</h1>",
             f"<p class='muted'>Cumulative across all closed trades. Start capital ${capital:,.0f} (account_size_usd). "
             f"P/L in $ net of commission. Generated {datetime.now():%Y-%m-%d %H:%M}.</p>"]
    head = ("<tr><th>{k}</th><th>Since</th><th>Trades</th><th>Win%</th><th>PF</th><th>Net P/L</th><th>Net %</th>"
            "<th>Avg win</th><th>Avg loss</th><th>Expectancy</th><th>Avg R</th><th>Max DD</th><th>Max DD %</th>"
            "<th>Best</th><th>Worst</th></tr>")

    def line(label, rs):
        m = metrics(rs, capital)
        d0 = next((r["dt"] for r in rs if r["dt"]), None)
        pf_s = "&infin;" if m["pf"] == float("inf") else f"{m['pf']:.2f}"
        return (f"<tr><td>{label}</td><td>{d0.strftime('%Y-%m-%d') if d0 else ''}</td><td>{m['trades']}</td>"
                f"<td>{m['win']:.1f}%</td><td>{pf_s}</td><td class='{color(m['net'])}'>${m['net']:,.0f}</td>"
                f"<td class='{color(m['net'])}'>{m['net'] / capital:+.2%}</td><td>${m['avg_win']:,.0f}</td>"
                f"<td>${m['avg_loss']:,.0f}</td><td>${m['exp']:,.0f}</td><td>{m['avg_r']:+.2f}</td>"
                f"<td class='neg'>${m['mdd']:,.0f}</td><td class='neg'>{m['mdd'] / capital:.2%}</td>"
                f"<td class='pos'>${m['best']:,.0f}</td><td class='neg'>${m['worst']:,.0f}</td></tr>")
    for title, key in (("By strategy instance", "name"), ("By instrument", "symbol"), ("By strategy", "strategy")):
        g = _group(rows, key)
        parts.append(f"<h2>{title}</h2><table>" + head.format(k=key.title() if key != "name" else "Strategy instance"))
        for k in sorted(g):
            parts.append(line(k, g[k]))
        parts.append(line("<b>TOTAL</b>", rows) + "</table>")
    parts.append("<h2>Equity curves</h2>")
    m = metrics(rows, capital)
    parts.append(f"<div style='margin:10px 0'><b>PORTFOLIO</b> &mdash; net <span class='{color(m['net'])}'>${m['net']:,.0f}</span>, "
                 f"end ${m['eq'][-1]:,.0f}<br>{svg_eq(m['eq'], capital)}</div>")
    for k, rs in sorted(_group(rows, "name").items()):
        m = metrics(rs, capital)
        parts.append(f"<div style='margin:10px 0'><b>{k}</b> &mdash; net <span class='{color(m['net'])}'>${m['net']:,.0f}</span>, "
                     f"end ${m['eq'][-1]:,.0f}<br>{svg_eq(m['eq'], capital)}</div>")
    path = os.path.join(out_dir, "performance_report.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(parts))
    return path


def build(csv_dir, capital=150000.0, day=None):
    """Write both reports into <csv_dir>/reports and return (eod_path, perf_path, rows)."""
    out_dir = os.path.join(csv_dir, "reports")
    os.makedirs(out_dir, exist_ok=True)
    rows = load_all(csv_dir)
    day = day or date.today()
    return eod_report(rows, day, capital, out_dir), perf_report(rows, capital, out_dir), rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="")
    ap.add_argument("--date", default="")
    ap.add_argument("--capital", type=float, default=150000.0)
    a = ap.parse_args()
    csv_dir = find_dir(a.dir)
    day = datetime.strptime(a.date, "%Y-%m-%d").date() if a.date else date.today()
    e, p, rows = build(csv_dir, a.capital, day)
    if not rows:
        print(f"No trade CSVs ({CSV_GLOB}) found in {csv_dir}. (Bot hasn't closed trades yet?)")
    print("Trade CSV dir:", csv_dir)
    print("EOD report   :", e)
    print("Performance  :", p)
    for name, rs in sorted(_group(rows, "name").items()):
        m = metrics(rs, a.capital)
        pf_s = "inf" if m["pf"] == float("inf") else f"{m['pf']:.2f}"
        print(f"  {name:<28} trades={m['trades']:<5} net=${m['net']:,.0f}  PF={pf_s}  win={m['win']:.1f}%")


if __name__ == "__main__":
    main()
