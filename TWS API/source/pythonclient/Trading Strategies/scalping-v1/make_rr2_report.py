"""Build RR2_Strategy_Report.html: the 2:1 RR study (IB Trend Breakout + MNQ Confluence Pullback + all tested families)."""
import glob
import json
import os
import pandas as pd
from make_report import svg_equity, f

HERE = os.path.dirname(os.path.abspath(__file__))
R = os.path.join(HERE, "results")


def family_table():
    frames = [pd.read_csv(p) for p in glob.glob(os.path.join(R, "rr2_*.csv")) if "final_grid" not in p]
    a = pd.concat(frames).drop_duplicates(["cfg", "sym", "part"])
    a = a[a.part == "ALL"].copy()
    a["fam"] = a.cfg.str.split("#").str[0]
    rows = []
    for fam, g in a.groupby("fam"):
        rows.append(dict(fam=fam, cfgs=g.cfg.nunique(), pos=(g.net > 0).mean(), medpf=g.pf.median(),
                         tgt=g.tgt_rate.median(), best=g.groupby("cfg").net.sum().max()))
    return pd.DataFrame(rows).sort_values("medpf", ascending=False)


def main():
    J = json.load(open(os.path.join(R, "rr2_final.json")))
    conf = pd.read_csv(os.path.join(R, "confluence_mnq_trades.csv"))
    meta = J["meta"]["MNQ"]
    h = ["""<!doctype html><html><head><meta charset="utf-8"><title>2:1 RR Strategy Study – MNQ / MES / MGC</title>
<style>body{font-family:Segoe UI,Arial,sans-serif;max-width:1050px;margin:24px auto;color:#1f2937;line-height:1.45;padding:0 16px}
h2{border-bottom:2px solid #e5e7eb;padding-bottom:4px;margin-top:34px}table{border-collapse:collapse;margin:10px 0;font-size:13px}
td,th{border:1px solid #e5e7eb;padding:4px 8px;text-align:right}th{background:#f3f4f6}td:first-child,th:first-child{text-align:left}
.box{background:#f9fafb;border:1px solid #e5e7eb;border-radius:6px;padding:10px 14px}.muted{color:#6b7280;font-size:12px}
.warn{background:#fffbeb;border:1px solid #fcd34d;border-radius:6px;padding:8px 12px}</style></head><body>"""]
    h.append(f"<h1>2:1 Reward-to-Risk Strategy Study</h1><div class='muted'>5-min RTH bars {meta[0]} → {meta[1]} "
             f"({meta[2]} sessions). In-sample before {J['split']}, out-of-sample after. 1 contract, net of commission + 1 tick "
             f"slippage per market/stop fill; stop assumed first when stop &amp; target share a bar.</div>")
    h.append("<div class='warn'><b>Bottom line:</b> no 2:1 setup reached statistical significance on 13 months of data "
             "(best pooled t ≈ 1.3). Tight-stop 2:1 scalps were ≈ breakeven after costs everywhere. The edge that showed up "
             "consistently is <b>trading the Initial Balance breakout only in the daily-trend direction</b>.</div>")
    # IB trend
    h.append("<h2>#1 IB Trend Breakout (2R target) — MNQ · MES · MGC</h2><div class='box'><b>Rules</b><ol>"
             "<li>Daily trend = yesterday's RTH close vs the 20-day EMA of RTH closes (up / down).</li>"
             "<li>Initial Balance = high/low of 09:30–10:30 ET.</li>"
             "<li>At 11:00 ET: if the 10:55 bar closed above IB high <i>and</i> the trend is up → buy the 11:00 open "
             "(mirror for shorts). The first IB break decides the day; no trade if it is against the trend.</li>"
             "<li>Stop = IB midpoint. Target = 2 × risk. Otherwise exit at the 16:00 close. One trade a day.</li></ol></div>")
    h.append(svg_equity(J["sym"]))
    h.append("<table><tr><th>Sym</th><th>Trades</th><th>Win%</th><th>2R hit</th><th>PF</th><th>Net $</th><th>Max DD</th>"
             "<th>IS PF</th><th>OOS PF</th><th>PF @2 tick</th><th>Long $</th><th>Short $</th><th>Avg risk</th></tr>")
    for s, d in J["sym"].items():
        a = d["all"]
        h.append(f"<tr><td>{s}</td><td>{a['n']:.0f}</td><td>{a['win']:.0%}</td><td>{a['tgt']:.0%}</td><td>{a['pf']:.2f}</td>"
                 f"<td>{f(a['net'],'$')}</td><td>{f(a['dd'],'$')}</td><td>{d['IS']['pf']:.2f}</td><td>{d['OOS']['pf']:.2f}</td>"
                 f"<td>{d['slip2']['pf']:.2f}</td><td>{f(d['long']['net'],'$')}</td><td>{f(d['short']['net'],'$')}</td>"
                 f"<td>{d['avg_risk_pts']:.0f} pt (${d['avg_risk_usd']:.0f})</td></tr>")
    h.append("</table><p class='muted'>Wide structural stop → the 2R target fills only 5–13% of the time; most winners are "
             "closed at 16:00. Treat it as a 2R-<i>capped</i> trend day-trade.</p>")
    g = pd.read_csv(os.path.join(R, "rr2_final_grid.csv"))
    g["filter"] = g.trend.map(lambda x: "trend filter" if x.startswith("e") else ("long-only control" if x == "long" else "no filter"))
    s = g.groupby("filter").agg(configs=("pooled_R", "size"), positive=("pooled_R", lambda x: (x > 0).mean()),
                                medR=("pooled_R", "median"), bestR=("pooled_R", "max"))
    h.append("<h3>Robustness: 40 neighbouring variants (trend def × entry timing × stop × IB-width filter)</h3><table>"
             "<tr><th>Group</th><th>Configs</th><th>Pooled R &gt; 0</th><th>Median R/trade</th><th>Best R/trade</th></tr>")
    for k, r in s.iterrows():
        h.append(f"<tr><td>{k}</td><td>{r.configs}</td><td>{r.positive:.0%}</td><td>{r.medR:+.3f}</td><td>{r.bestR:+.3f}</td></tr>")
    h.append("</table>")
    # confluence
    eq = conf.groupby("day").net.sum().cumsum()
    pfc = conf.net[conf.net > 0].sum() / -conf.net[conf.net < 0].sum()
    h.append("<h2>#2 MNQ Trend-Confluence Pullback — the true 2:1 scalp (MNQ only)</h2><div class='box'><b>Rules</b><ol>"
             "<li>From 10:00 ET all five agree: daily trend (close vs 20d EMA), first-30-min return (10:00 vs prior close), "
             "price vs prior close, price vs VWAP, price vs 30 min ago.</li>"
             "<li>Trigger: a 5-min bar dips to the EMA9 and closes back beyond it in the trend direction → enter next open.</li>"
             "<li>Stop = 1 × ATR(14, 5-min) (~42 MNQ pts ≈ $85). Target = 2R. Max 4 trades/day, last entry 15:00.</li></ol></div>")
    h.append(svg_equity({"MNQ": {"equity": [[str(k), float(v)] for k, v in eq.items()]}}))
    h.append(f"<table><tr><th>Trades</th><th>Win%</th><th>2R hit</th><th>Stopped</th><th>PF</th><th>Net $</th></tr>"
             f"<tr><td>{len(conf)}</td><td>{(conf.net > 0).mean():.0%}</td><td>{(conf.why == 'tgt').mean():.0%}</td>"
             f"<td>{(conf.why == 'stop').mean():.0%}</td><td>{pfc:.2f}</td><td>{f(conf.net.sum(), '$')}</td></tr></table>"
             "<p class='muted'>Positive IS (PF 1.03) and OOS (PF 1.29); PF 1.12 at 2-tick slippage. Same rules lose on MES and MGC.</p>")
    # families
    ft = family_table()
    h.append("<h2>Every 2:1 family tested</h2><table><tr><th>Family</th><th>Configs</th><th>% config×symbol runs profitable</th>"
             "<th>Median PF</th><th>Median 2R-hit rate</th></tr>")
    for _, r in ft.iterrows():
        h.append(f"<tr><td>{r.fam}</td><td>{r.cfgs}</td><td>{r.pos:.0%}</td><td>{r.medpf:.2f}</td><td>{r.tgt:.0%}</td></tr>")
    h.append("</table></body></html>")
    open(os.path.join(HERE, "RR2_Strategy_Report.html"), "w", encoding="utf-8").write("\n".join(h))
    print(ft.round(2).to_string(index=False))
    print(s.round(3))


if __name__ == "__main__":
    main()
