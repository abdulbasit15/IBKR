"""Render the Nasdaq-100 daily backtests into a single tabbed HTML report, with an inline
equity-curve sparkline (growth of $10k) per ticker for each strategy:
  * Supertrend + 200-DEMA (long-only)
  * RSI(14) mean-reversion  (buy <30, sell >70, long-only)
"""
import csv, json, os

OUT = r"C:\Users\abdbasit\Downloads\Personal\Trade\IBKR\TWS API\source\pythonclient\Trading Strategies\Indicator Strategies\supertrend\backtest\nasdaq100_daily_5y"
W, H, PAD, START = 180, 46, 4, 10000.0

def load(sfx=""):
    rows = list(csv.DictReader(open(os.path.join(OUT, f"summary{sfx}.csv"))))
    agg = json.load(open(os.path.join(OUT, f"aggregate{sfx}.json")))
    curves = json.load(open(os.path.join(OUT, f"equity_curves{sfx}.json")))
    return rows, agg, curves

def spark(sym, curves, positive):
    c = curves.get(sym)
    if not c or len(c["strat"]) < 2:
        return '<span style="color:#555">n/a</span>'
    strat, bh = c["strat"], c["bh"]
    lo = min(min(strat), min(bh), START); hi = max(max(strat), max(bh), START)
    rng = (hi - lo) or 1.0
    def pts(a):
        n = len(a)
        return " ".join(f"{PAD+i/(n-1)*(W-2*PAD):.1f},{H-PAD-(v-lo)/rng*(H-2*PAD):.1f}"
                        for i, v in enumerate(a))
    y0 = H-PAD-(START-lo)/rng*(H-2*PAD)
    col = "#3fbf7f" if positive else "#ff6b6b"
    return (f'<svg viewBox="0 0 {W} {H}" width="{W}" height="{H}" preserveAspectRatio="none" style="display:block">'
            f'<line x1="{PAD}" y1="{y0:.1f}" x2="{W-PAD}" y2="{y0:.1f}" stroke="#3a4150" stroke-width="1" stroke-dasharray="2,2"/>'
            f'<polyline points="{pts(bh)}" fill="none" stroke="#5a6675" stroke-width="1" opacity="0.7"/>'
            f'<polyline points="{pts(strat)}" fill="none" stroke="{col}" stroke-width="1.6"/>'
            f'<title>{sym}: $10,000 -> ${strat[-1]:,.0f} (strategy) vs ${bh[-1]:,.0f} (buy&hold)</title></svg>')

def cls(v):
    try: return "pos" if float(v) > 0 else ("neg" if float(v) < 0 else "")
    except: return ""

def cards(agg):
    return f"""<div class="cards">
  <div class="card"><div class="k">Symbols tested</div><div class="v">{agg['symbols']}</div></div>
  <div class="card"><div class="k">Avg net return</div><div class="v {cls(agg['avg_net_ret'])}">{agg['avg_net_ret']:.1f}%</div></div>
  <div class="card"><div class="k">Median net return</div><div class="v {cls(agg['median_net_ret'])}">{agg['median_net_ret']:.1f}%</div></div>
  <div class="card"><div class="k">Avg buy &amp; hold</div><div class="v">{agg['avg_buyhold']:.1f}%</div></div>
  <div class="card"><div class="k">Beat buy &amp; hold</div><div class="v">{agg['beat_buyhold']}/{agg['symbols']}</div></div>
  <div class="card"><div class="k">Profitable</div><div class="v">{agg['profitable']}/{agg['symbols']}</div></div>
  <div class="card"><div class="k">Total trades</div><div class="v">{agg['total_trades']}</div></div>
  <div class="card"><div class="k">Agg win rate</div><div class="v">{agg['agg_win_rate']:.1f}%</div></div>
</div>"""

def table(rows, curves, tid):
    trs = []
    for r in rows:
        beat = float(r["net_ret"]) > float(r["buyhold"])
        trs.append(
            f'<tr><td class="sym">{r["symbol"]}</td>'
            f'<td class="spark">{spark(r["symbol"], curves, float(r["net_ret"])>0)}</td>'
            f'<td class="{cls(r["net_ret"])}">{r["net_ret"]}%</td>'
            f'<td class="{cls(r["cagr"])}">{r["cagr"]}%</td>'
            f'<td class="{cls(r["buyhold"])}">{r["buyhold"]}%</td>'
            f'<td class="{"pos" if beat else "neg"}">{"Y" if beat else "-"}</td>'
            f'<td>{r["trades"]}</td><td>{r["win_rate"]}%</td><td>{r["pf"]}</td>'
            f'<td class="neg">{r["max_dd"]}%</td><td>{r["avg_win"]}%</td><td>{r["avg_loss"]}%</td>'
            f'<td>${float(r["end_equity"]):,.0f}</td>'
            f'<td class="win">{r["start"]} → {r["end"]}</td></tr>')
    return f"""<table class="t" id="{tid}"><thead><tr>
<th>Symbol</th><th>Equity curve</th><th>Net %</th><th>CAGR %</th><th>Buy&amp;Hold %</th><th>Beat?</th><th>Trades</th>
<th>Win %</th><th>PF</th><th>Max DD %</th><th>Avg Win %</th><th>Avg Loss %</th><th>End $</th><th>Window</th>
</tr></thead><tbody>
{''.join(trs)}
</tbody></table>"""

LEGEND = ('<div class="legend"><span><i style="border-color:#3fbf7f"></i>strategy equity ($10k start)</span>'
          '<span><i style="border-color:#5a6675"></i>buy &amp; hold</span>'
          '<span><i style="border-color:#3a4150;border-top-style:dashed"></i>$10k break-even</span>'
          '<span>(hover a curve for end values)</span></div>')

st_rows, st_agg, st_curves = load("")
rsi_rows, rsi_agg, rsi_curves = load("_rsi")

panel_st = f"""<div class="panel" id="p_st">
<div class="sub">Enter: Supertrend bull (ATR 10, mult 3) <b>AND</b> close &gt; 200-DEMA · Exit: Supertrend bear <b>OR</b> close &lt; 200-DEMA · long-only, fills at next open, $10k all-in compounding, frictionless</div>
{cards(st_agg)}{LEGEND}{table(st_rows, st_curves, 't_st')}</div>"""

panel_rsi = f"""<div class="panel" id="p_rsi">
<div class="sub">Enter: RSI(14) &lt; 30 (oversold) · Exit: RSI(14) &gt; 70 (overbought) · long-only, fills at next open, $10k all-in compounding, frictionless</div>
{cards(rsi_agg)}{LEGEND}{table(rsi_rows, rsi_curves, 't_rsi')}</div>"""

html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>Nasdaq-100 Daily Backtests</title>
<style>
body{{font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:#0f1115;color:#e6e6e6;margin:0;padding:24px}}
h1{{font-size:20px;margin:0 0 6px}} .sub{{color:#8a93a2;font-size:13px;margin:8px 0 16px}}
h2{{font-size:17px;margin:28px 0 10px;padding-top:10px;border-top:1px solid #252a34}}
.jump{{color:#8a93a2;font-size:13px;margin-bottom:8px}} .jump a{{color:#7fb2ff;text-decoration:none}}
.cards{{display:flex;flex-wrap:wrap;gap:12px;margin-bottom:18px}}
.card{{background:#171a21;border:1px solid #252a34;border-radius:10px;padding:12px 16px;min-width:150px}}
.card .k{{color:#8a93a2;font-size:12px}} .card .v{{font-size:20px;font-weight:600;margin-top:2px}}
table{{border-collapse:collapse;width:100%;font-size:13px}}
th,td{{padding:6px 9px;text-align:right;border-bottom:1px solid #20242d}}
th{{position:sticky;top:0;background:#12151b;color:#9aa4b2;text-align:right;cursor:pointer}}
td.sym{{text-align:left;font-weight:600;color:#fff}} td.win{{text-align:left;color:#8a93a2}}
td.spark{{padding:2px 6px;width:{W}px}}
.pos{{color:#3fbf7f}} .neg{{color:#ff6b6b}}
tr:hover td{{background:#161a22}}
.legend{{display:inline-flex;gap:16px;align-items:center;font-size:12px;color:#8a93a2;margin:2px 0 14px;flex-wrap:wrap}}
.legend i{{display:inline-block;width:16px;height:0;border-top:2px solid;margin-right:6px;vertical-align:middle}}
.note{{color:#8a93a2;font-size:12px;margin-top:18px;line-height:1.6}}
</style></head><body>
<h1>Nasdaq-100 — Daily Strategy Backtests (~5 years)</h1>
<div class="jump">Jump to: <a href="#p_st">① Supertrend + 200-DEMA</a> &nbsp;·&nbsp; <a href="#p_rsi">② RSI(14) 30/70</a></div>
<h2 id="h_st">① Supertrend + 200-DEMA — long-only</h2>
{panel_st}
<h2 id="h_rsi">② RSI(14) 30/70 — long-only mean reversion</h2>
{panel_rsi}
<div class="note">
Each <b>equity curve</b> is the growth of $10,000 traded by that strategy (green if net-positive, red if
net-negative) with the passive buy&amp;hold curve behind it; both share the same per-ticker y-scale and the
dashed line marks the $10k break-even. <b>Net %</b> = strategy total return over the stock's window.
<b>PF</b> = gross profit / gross loss. <b>Max DD %</b> = deepest peak-to-trough on the strategy equity curve.
Sorted by net return; click any header (except the curve) to re-sort.<br>
Data: Yahoo Finance split/dividend-adjusted daily bars (~5y, or since listing for recent IPOs). The
Supertrend section's DEMA(200) needs ~400 bars of warmup, so CRWV/SNDK produced too few post-warmup bars to trade.
</div>
<script>
document.querySelectorAll('table.t').forEach(t=>{{
  t.querySelectorAll('th').forEach((h,i)=>{{
    if(i===1) return;
    h.onclick=()=>{{
      const rows=[...t.tBodies[0].rows];
      const num=i>0&&i!==5&&i!==13;
      const asc=h.dataset.a!=='1'; h.dataset.a=asc?'1':'0';
      rows.sort((a,b)=>{{let x=a.cells[i].innerText.replace(/[%$,]/g,''),y=b.cells[i].innerText.replace(/[%$,]/g,'');
        return (num?(parseFloat(x)-parseFloat(y)):x.localeCompare(y))*(asc?1:-1);}});
      rows.forEach(r=>t.tBodies[0].appendChild(r));
    }};
  }});
}});
</script>
</body></html>"""
open(os.path.join(OUT, "report.html"), "w", encoding="utf-8").write(html)
print("wrote", os.path.join(OUT, "report.html"))
