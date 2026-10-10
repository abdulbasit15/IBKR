"""Windows_Report.html: 2:1 strategies by RTH time window (heatmaps of PF, per symbol, IS/OOS)."""
import os
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
R = os.path.join(HERE, "results")
MAIN = ["09:30-11:30", "11:30-13:30", "13:30-16:00"]
HOURS = ["09:30-10:30", "10:30-11:30", "11:30-12:30", "12:30-13:30", "13:30-14:30", "14:30-15:30", "15:30-16:00"]


def color(pf, n):
    if n is None or n < 20 or pd.isna(pf):
        return "#f3f4f6"
    if pf >= 1.25:
        return "#86efac"
    if pf >= 1.10:
        return "#bbf7d0"
    if pf >= 1.0:
        return "#ecfccb"
    if pf >= 0.9:
        return "#fee2e2"
    return "#fca5a5"


def heat(P, mode, cols, extra=None):
    q = P[P["mode"] == mode]
    strategies = list(dict.fromkeys(P.strategy))
    h = ["<table><tr><th>Strategy</th>" + "".join(f"<th>{c}</th>" for c in cols) + "</tr>"]
    for s in strategies:
        cells = []
        for c in cols:
            r = q[(q.strategy == s) & (q.window == c)]
            if not len(r) or r.n.iloc[0] == 0:
                cells.append("<td style='background:#f9fafb;color:#9ca3af'>–</td>")
                continue
            r = r.iloc[0]
            txt = f"<b>{r.pf:.2f}</b><br><span class='muted'>n={r.n} · ${r.net:,.0f}</span>"
            if extra:
                txt += f"<br><span class='muted'>IS {r.isPF:.2f} / OOS {r.oosPF:.2f}</span>"
            cells.append(f"<td style='background:{color(r.pf, r.n)}'>{txt}</td>")
        h.append(f"<tr><td>{s}</td>{''.join(cells)}</tr>")
    h.append("</table>")
    return "".join(h)


def per_symbol(P, mode, window):
    q = P[(P["mode"] == mode) & (P.window == window) & (P.n > 0)].sort_values("pf", ascending=False)
    h = [f"<table><tr><th>Strategy</th><th>Pooled PF</th><th>IS PF</th><th>OOS PF</th><th>2R hit</th>"
         "<th>MNQ PF (n)</th><th>MES PF (n)</th><th>MGC PF (n)</th><th>Pooled net $</th></tr>"]
    for _, r in q.iterrows():
        sy = "".join(f"<td style='background:{color(r[f'{s}_pf'], r[f'{s}_n'])}'>{r[f'{s}_pf']:.2f} ({r[f'{s}_n']})</td>" for s in ("MNQ", "MES", "MGC"))
        h.append(f"<tr><td>{r.strategy}</td><td style='background:{color(r.pf, r.n)}'><b>{r.pf:.2f}</b></td>"
                 f"<td>{r.isPF:.2f}</td><td>{r.oosPF:.2f}</td><td>{r.tgt:.0%}</td>{sy}<td>${r.net:,.0f}</td></tr>")
    h.append("</table>")
    return "".join(h)


def main():
    P = pd.read_csv(os.path.join(R, "windows_pooled.csv"))
    B = pd.read_csv(os.path.join(R, "windows_baseline.csv"))
    h = ["""<!doctype html><html><head><meta charset="utf-8"><title>2:1 Strategies by RTH Time Window</title>
<style>body{font-family:Segoe UI,Arial,sans-serif;max-width:1150px;margin:24px auto;color:#1f2937;line-height:1.4;padding:0 16px}
h2{border-bottom:2px solid #e5e7eb;padding-bottom:4px;margin-top:34px}table{border-collapse:collapse;margin:10px 0;font-size:12.5px}
td,th{border:1px solid #e5e7eb;padding:4px 7px;text-align:center}th{background:#f3f4f6}td:first-child{text-align:left;white-space:nowrap}
.muted{color:#4b5563;font-size:11px}.box{background:#f9fafb;border:1px solid #e5e7eb;border-radius:6px;padding:10px 14px}</style></head><body>"""]
    h.append("<h1>2:1 RR Strategies by RTH Time Window — MNQ · MES · MGC</h1>"
             "<div class='muted'>RTH only: 5-min bars 09:30–16:00 ET, 2025-09-02 → 2026-10-07; no overnight data; daily trend from RTH "
             "closes. Pooled = MNQ+MES+MGC trades, 1 contract each, net of commission + 1 tick slippage per market/stop fill. "
             "In-sample before 2026-05-01. Cell = profit factor, n trades, net $. Grey = fewer than 20 trades.</div>")
    h.append("<div class='box'><b>Modes</b> — <b>Window-only</b>: entries inside the window and flat at the window end "
             "(you trade only that session). <b>Hold</b>: entries inside the window, then held to 2R / stop / 16:00 "
             "(entries ≤15:30). Colour: <span style='background:#86efac'>&nbsp;PF≥1.25&nbsp;</span> "
             "<span style='background:#bbf7d0'>&nbsp;1.10–1.25&nbsp;</span> <span style='background:#ecfccb'>&nbsp;1.00–1.10&nbsp;</span> "
             "<span style='background:#fee2e2'>&nbsp;0.90–1.00&nbsp;</span> <span style='background:#fca5a5'>&nbsp;&lt;0.90&nbsp;</span></div>")
    h.append("<h2>Random-entry baseline (every bar, both directions, 1×ATR stop, 2R target, held to 16:00)</h2><table><tr><th>Sym</th>"
             + "".join(f"<th>{w}<br>2R hit · avg R</th>" for w in MAIN) + "</tr>")
    for s, g in B.groupby("sym"):
        h.append(f"<tr><td>{s}</td>" + "".join(f"<td>{r.hit:.1%} · {r.R:+.3f}</td>" for _, r in g.iterrows()) + "</tr>")
    h.append("</table><p class='muted'>Break-even needs ≈36% 2R hits after costs. 2R is easiest in the morning and hardest late in the day.</p>")
    h.append("<h2>Window-only (flat at window end) — 3 sessions</h2>" + heat(P, "flat", MAIN, extra=True))
    h.append("<h2>Hold (enter in window, manage to 2R / stop / 16:00) — 3 sessions + full day</h2>" + heat(P, "hold", MAIN + ["Full RTH"], extra=True))
    h.append("<h2>Hourly entry buckets — window-only</h2>" + heat(P, "flat", HOURS))
    h.append("<h2>Hourly entry buckets — hold</h2>" + heat(P, "hold", HOURS[:-1]))
    for w in MAIN:
        h.append(f"<h2>{w} detail per instrument — hold mode</h2>" + per_symbol(P, "hold", w))
        h.append(f"<h3>{w} detail per instrument — window-only</h3>" + per_symbol(P, "flat", w))
    h.append("</body></html>")
    open(os.path.join(HERE, "Windows_Report.html"), "w", encoding="utf-8").write("\n".join(h))
    print("wrote Windows_Report.html")


if __name__ == "__main__":
    main()
