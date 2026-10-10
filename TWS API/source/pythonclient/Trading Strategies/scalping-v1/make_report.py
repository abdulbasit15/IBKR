"""Build Scalping_Strategies_Report.html (inline-SVG equity curves, no external deps) from results/."""
import json
import os
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
R = os.path.join(HERE, "results")
COL = {"MNQ": "#2563eb", "MES": "#d97706", "MGC": "#059669"}
VERDICT = {
    "IB Breakout": {"MNQ": "Trade", "MES": "Trade (best fit)", "MGC": "Trade (small edge)"},
    "Opening-Candle Momentum": {"MNQ": "Trade", "MES": "Avoid", "MGC": "Avoid (OOS negative)"},
    "Last-Half-Hour Momentum": {"MNQ": "Trade", "MES": "Avoid", "MGC": "Trade (best fit)"},
}


def svg_equity(sdata, w=640, h=220, pad=36):
    series = {s: [v for _, v in d["equity"]] for s, d in sdata.items()}
    allv = [v for s in series.values() for v in s] + [0]
    lo, hi = min(allv), max(allv)
    span = (hi - lo) or 1
    n = max(len(s) for s in series.values())
    X = lambda i: pad + i * (w - 2 * pad) / max(n - 1, 1)
    Y = lambda v: h - pad + (lo - v) * (h - 2 * pad) / span
    out = [f'<svg viewBox="0 0 {w} {h}" width="100%" style="max-width:{w}px">',
           f'<line x1="{pad}" x2="{w-pad}" y1="{Y(0):.1f}" y2="{Y(0):.1f}" stroke="#bbb" stroke-dasharray="3 3"/>',
           f'<text x="4" y="{Y(hi)+4:.0f}" font-size="10" fill="#666">${hi:,.0f}</text>',
           f'<text x="4" y="{Y(lo)+4:.0f}" font-size="10" fill="#666">${lo:,.0f}</text>']
    first = list(sdata.values())[0]["equity"]
    for k in (0, n // 2, n - 1):
        out.append(f'<text x="{X(k):.0f}" y="{h-8}" font-size="10" fill="#666" text-anchor="middle">{first[k][0]}</text>')
    for s, v in series.items():
        pts = " ".join(f"{X(i):.1f},{Y(x):.1f}" for i, x in enumerate(v))
        out.append(f'<polyline fill="none" stroke="{COL[s]}" stroke-width="1.8" points="{pts}"/>')
        out.append(f'<text x="{X(len(v)-1)-4:.0f}" y="{Y(v[-1])-5:.0f}" font-size="11" fill="{COL[s]}" text-anchor="end">{s} ${v[-1]:,.0f}</text>')
    out.append("</svg>")
    return "".join(out)


def f(x, kind):
    if x is None:
        return "–"
    return {"pf": f"{x:.2f}", "$": f"${x:,.0f}", "%": f"{x:.0%}", "r": f"{x:+.2f}", "n": f"{x:,.0f}", "s": f"{x:.2f}"}[kind]


def main():
    J = json.load(open(os.path.join(R, "finalists.json")))
    allc = pd.read_csv(os.path.join(R, "all_configs.csv"))
    html = ["""<!doctype html><html><head><meta charset="utf-8"><title>Scalping Strategies – MNQ / MES / MGC</title>
<style>body{font-family:Segoe UI,Arial,sans-serif;max-width:1050px;margin:24px auto;color:#1f2937;line-height:1.45;padding:0 16px}
h1{margin-bottom:4px}h2{border-bottom:2px solid #e5e7eb;padding-bottom:4px;margin-top:36px}
table{border-collapse:collapse;margin:10px 0;font-size:13px}td,th{border:1px solid #e5e7eb;padding:4px 8px;text-align:right}
th{background:#f3f4f6}td:first-child,th:first-child{text-align:left}.box{background:#f9fafb;border:1px solid #e5e7eb;border-radius:6px;padding:10px 14px}
.good{color:#047857;font-weight:600}.bad{color:#b91c1c;font-weight:600}.muted{color:#6b7280;font-size:12px}</style></head><body>"""]
    meta = J["meta"]
    html.append(f"<h1>Top 3 Scalping Strategies – MNQ / MES / MGC</h1><div class='muted'>5-min RTH bars "
                f"{meta['MNQ']['first']} → {meta['MNQ']['last']} (~{meta['MNQ']['n']} sessions). In-sample before {J['split']}, "
                f"out-of-sample after. 1 contract, costs included: commission (MNQ/MES $0.62, MGC $0.80 per side) + 1 tick slippage "
                f"on every market/stop fill; limit targets need a 1-tick trade-through; stop assumed first when stop & target share a bar.</div>")
    # summary
    html.append("<h2>Scorecard</h2><table><tr><th>Strategy</th><th>Sym</th><th>Verdict</th><th>Trades</th><th>Win%</th><th>PF</th>"
                "<th>Net $</th><th>Max DD $</th><th>Sharpe</th><th>IS PF</th><th>OOS PF</th><th>PF @2-tick slip</th>"
                "<th>Neighbour params profitable</th><th>Avg hold</th></tr>")
    for name, st in J["strategies"].items():
        for s, d in st["sym"].items():
            a = d["all"]
            v = VERDICT[name][s]
            cls = "bad" if v.startswith("Avoid") else "good"
            html.append(f"<tr><td>{name}</td><td>{s}</td><td class='{cls}'>{v}</td><td>{f(a['n'],'n')}</td><td>{f(a['win'],'%')}</td>"
                        f"<td>{f(a['pf'],'pf')}</td><td>{f(a['net'],'$')}</td><td>{f(a['dd'],'$')}</td><td>{f(a['sharpe'],'s')}</td>"
                        f"<td>{f(d['IS']['pf'],'pf')}</td><td>{f(d['OOS']['pf'],'pf')}</td><td>{f(d['slip2']['pf'],'pf')}</td>"
                        f"<td>{d['neigh_pos']:.0%}</td><td>{d['avg_hold_min']:.0f} min</td></tr>")
    html.append("</table>")
    # per strategy
    for name, st in J["strategies"].items():
        html.append(f"<h2>{name}</h2><div class='box'><pre style='white-space:pre-wrap;margin:0'>{st['doc']}</pre>"
                    f"<div class='muted'>params: {st['params']}</div></div>")
        html.append(svg_equity(st["sym"]))
        html.append("<table><tr><th>Sym</th><th>Long net $</th><th>Short net $</th><th>Avg pts/trade</th><th>Exits</th></tr>")
        for s, d in st["sym"].items():
            html.append(f"<tr><td>{s}</td><td>{f(d['long']['net'],'$')}</td><td>{f(d['short']['net'],'$')}</td>"
                        f"<td>{d['avg_pts']:+.2f}</td><td>{', '.join(f'{k}:{v}' for k, v in d['exits'].items())}</td></tr>")
        html.append("</table>")
        months = sorted({m for d in st["sym"].values() for m in d["monthly"]})
        html.append("<table><tr><th>Month</th>" + "".join(f"<th>{m[2:]}</th>" for m in months) + "</tr>")
        for s, d in st["sym"].items():
            cells = "".join(
                f"<td style='color:{'#047857' if d['monthly'].get(m, 0) > 0 else '#b91c1c'}'>{d['monthly'].get(m, 0):,.0f}</td>" for m in months)
            html.append(f"<tr><td>{s}</td>{cells}</tr>")
        html.append("</table>")
    # what failed
    html.append("<h2>Everything else tested (all net of costs)</h2><table><tr><th>Family</th><th>Configs</th>"
                "<th>% config×symbol runs profitable</th><th>Median PF</th><th>Best symbol</th></tr>")
    a = allc[allc.part == "ALL"].copy()
    a["fam"] = a.cfg.str.split("#").str[0]
    for fam, g in a.groupby("fam"):
        best = g.groupby("sym").net.median().idxmax()
        html.append(f"<tr><td>{fam}</td><td>{g.cfg.nunique()}</td><td>{(g.net > 0).mean():.0%}</td>"
                    f"<td>{g.pf.median():.2f}</td><td>{best}</td></tr>")
    html.append("</table><p class='muted'>ORB family includes the 60-min IB variants (the only robust cluster). "
                "FirstBar = opening-candle momentum, LastHalf = last-half-hour momentum.</p></body></html>")
    open(os.path.join(HERE, "Scalping_Strategies_Report.html"), "w", encoding="utf-8").write("\n".join(html))
    print("wrote Scalping_Strategies_Report.html")
    print(a.groupby("fam").apply(lambda g: pd.Series(dict(cfgs=g.cfg.nunique(), pos=(g.net > 0).mean(), medpf=g.pf.median()))).round(2))


if __name__ == "__main__":
    main()
