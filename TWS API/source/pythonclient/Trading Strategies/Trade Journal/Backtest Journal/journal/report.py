"""Render a self-contained HTML dashboard (inline CSS + hand-drawn SVG charts)."""
from __future__ import annotations

import html
import re
from datetime import datetime
from pathlib import Path

from . import ai, config


def _fmt_money(v) -> str:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "-"
    sign = "-" if v < 0 else ""
    return f"{sign}${abs(v):,.0f}"


def _svg_equity(curve: list[dict], w=920, h=280, pad=40) -> str:
    if not curve:
        return "<p class='muted'>No data.</p>"
    ys = [p["cum"] for p in curve]
    xs = list(range(len(curve)))
    ymin, ymax = min(ys + [0]), max(ys + [0])
    yrange = (ymax - ymin) or 1
    xrange = (len(curve) - 1) or 1

    def px(i): return pad + (i / xrange) * (w - 2 * pad)
    def py(v): return h - pad - ((v - ymin) / yrange) * (h - 2 * pad)

    zero_y = py(0)
    pts = " ".join(f"{px(i):.1f},{py(v):.1f}" for i, v in zip(xs, ys))
    # Area fill down to the zero line
    area = f"{px(0):.1f},{zero_y:.1f} " + pts + f" {px(xs[-1]):.1f},{zero_y:.1f}"
    last_pos = ys[-1] >= 0
    color = "#22c55e" if last_pos else "#ef4444"
    dots = "".join(
        f'<circle cx="{px(i):.1f}" cy="{py(v):.1f}" r="2.5" '
        f'fill="{"#22c55e" if v >= 0 else "#ef4444"}"><title>#{i+1} '
        f'{curve[i]["asset"]} {curve[i]["ts"]}: {_fmt_money(v)}</title></circle>'
        for i, v in zip(xs, ys))
    return f'''<svg viewBox="0 0 {w} {h}" class="chart" preserveAspectRatio="xMidYMid meet">
  <line x1="{pad}" y1="{zero_y:.1f}" x2="{w-pad}" y2="{zero_y:.1f}" stroke="#374151" stroke-dasharray="4 4"/>
  <polygon points="{area}" fill="{color}" opacity="0.10"/>
  <polyline points="{pts}" fill="none" stroke="{color}" stroke-width="2"/>
  {dots}
  <text x="{pad}" y="16" fill="#9ca3af" font-size="12">Cumulative P&amp;L: {_fmt_money(ys[-1])}</text>
  <text x="{pad}" y="{h-8}" fill="#6b7280" font-size="11">trade 1</text>
  <text x="{w-pad-40}" y="{h-8}" fill="#6b7280" font-size="11">trade {len(curve)}</text>
</svg>'''


def _svg_bars(rows: list[dict], title: str, w=440, bar_h=26, pad=8) -> str:
    if not rows:
        return ""
    rows = rows[:12]
    vals = [r["total_pnl"] for r in rows]
    mx = max([abs(v) for v in vals] + [1])
    label_w, val_w = 120, 70
    plot_w = w - label_w - val_w - 2 * pad
    mid = label_w + pad + plot_w / 2
    h = pad * 2 + bar_h * len(rows) + 20
    parts = [f'<text x="{pad}" y="14" fill="#e5e7eb" font-size="13" '
             f'font-weight="600">{html.escape(title)}</text>']
    y = 24
    for r in rows:
        v = r["total_pnl"]
        bw = (abs(v) / mx) * (plot_w / 2)
        color = "#22c55e" if v >= 0 else "#ef4444"
        x = mid if v >= 0 else mid - bw
        name = html.escape(str(r["name"])[:14])
        parts.append(
            f'<text x="{pad}" y="{y+bar_h*0.65:.0f}" fill="#cbd5e1" font-size="12">{name}</text>'
            f'<rect x="{x:.1f}" y="{y}" width="{bw:.1f}" height="{bar_h-8}" rx="2" fill="{color}"/>'
            f'<text x="{w-pad}" y="{y+bar_h*0.65:.0f}" fill="#94a3b8" font-size="11" '
            f'text-anchor="end">{_fmt_money(v)} · {r["n"]}t · {r["win_rate"]*100:.0f}%</text>')
        y += bar_h
    parts.append(f'<line x1="{mid}" y1="20" x2="{mid}" y2="{y}" stroke="#374151"/>')
    return f'<svg viewBox="0 0 {w} {h}" class="bars">{"".join(parts)}</svg>'


def _card(label, value, sub="", tone="") -> str:
    cls = f"card {tone}".strip()
    sub = f'<div class="sub">{html.escape(str(sub))}</div>' if sub else ""
    return (f'<div class="{cls}"><div class="lbl">{html.escape(label)}</div>'
            f'<div class="val">{value}</div>{sub}</div>')


def _md_to_html(text: str) -> str:
    """Very small markdown subset -> HTML for the AI narrative."""
    out, in_list = [], False
    for raw in (text or "").split("\n"):
        line = raw.rstrip()
        if line.startswith("## "):
            if in_list:
                out.append("</ul>"); in_list = False
            out.append(f"<h3>{html.escape(line[3:])}</h3>")
        elif line.startswith("# "):
            if in_list:
                out.append("</ul>"); in_list = False
            out.append(f"<h2>{html.escape(line[2:])}</h2>")
        elif re.match(r"^\s*[-*]\s+", line):
            if not in_list:
                out.append("<ul>"); in_list = True
            item = re.sub(r"^\s*[-*]\s+", "", line)
            out.append(f"<li>{_inline(item)}</li>")
        elif line.strip() == "":
            if in_list:
                out.append("</ul>"); in_list = False
        else:
            if in_list:
                out.append("</ul>"); in_list = False
            out.append(f"<p>{_inline(line)}</p>")
    if in_list:
        out.append("</ul>")
    return "\n".join(out)


def _inline(s: str) -> str:
    s = html.escape(s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"`(.+?)`", r"<code>\1</code>", s)
    return s


def _flags_html(flags: list[dict]) -> str:
    if not flags:
        return '<p class="muted">No behavior flags detected. 🎉</p>'
    icon = {"Overtrading": "🔁", "Possible revenge trade": "😤",
            "Stop overrun": "🛑", "Winner cut short": "✂️",
            "Inconsistent sizing": "📏"}
    rows = []
    for f in flags:
        ic = next((v for k, v in icon.items() if f["type"].startswith(k)), "⚠️")
        rows.append(f'<li><span class="ftype">{ic} {html.escape(f["type"])}</span>'
                    f'<span class="fdet">{html.escape(f["detail"])}</span></li>')
    return f'<ul class="flags">{"".join(rows)}</ul>'


def _recent_table(recent: list[dict]) -> str:
    if not recent:
        return ""
    head = ("<tr><th>Date/Time</th><th>Asset</th><th>Dir</th><th>Entry</th>"
            "<th>Exit</th><th>Size</th><th>RR</th><th>P&L</th><th>Setup</th></tr>")
    body = []
    for t in recent:
        pnl = t.get("pnl")
        tone = "pos" if (pnl or 0) > 0 else ("neg" if (pnl or 0) < 0 else "")
        body.append(
            f'<tr><td>{html.escape(str(t.get("when","")))}</td>'
            f'<td>{html.escape(str(t.get("asset","")))}</td>'
            f'<td>{html.escape(str(t.get("direction","")))}</td>'
            f'<td>{t.get("entry","")}</td><td>{t.get("exit","")}</td>'
            f'<td>{t.get("size","")}</td><td>{t.get("rr_realized","")}</td>'
            f'<td class="{tone}">{_fmt_money(pnl)}</td>'
            f'<td>{html.escape(str(t.get("setup","")))}</td></tr>')
    return f'<table class="trades"><thead>{head}</thead><tbody>{"".join(body)}</tbody></table>'


CSS = """
:root{--bg:#0b0f19;--panel:#111827;--panel2:#0f1523;--line:#1f2937;--txt:#e5e7eb;
--muted:#9ca3af;--green:#22c55e;--red:#ef4444;--accent:#38bdf8}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--txt);
font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;line-height:1.5}
.wrap{max-width:1200px;margin:0 auto;padding:28px 20px 60px}
h1{font-size:24px;margin:0 0 2px}
.sub-hd{color:var(--muted);font-size:13px;margin-bottom:22px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:24px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.card .lbl{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.04em}
.card .val{font-size:24px;font-weight:700;margin-top:4px}
.card .sub{color:var(--muted);font-size:12px;margin-top:2px}
.card.good .val{color:var(--green)} .card.bad .val{color:var(--red)}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:18px 20px;margin-bottom:22px}
.panel h2{font-size:16px;margin:0 0 14px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:18px}
.chart{width:100%;height:auto;background:var(--panel2);border-radius:10px}
.bars{width:100%;height:auto}
.muted{color:var(--muted)}
ul.flags{list-style:none;padding:0;margin:0;display:flex;flex-direction:column;gap:8px}
ul.flags li{display:flex;gap:12px;background:var(--panel2);border:1px solid var(--line);
border-radius:8px;padding:8px 12px}
ul.flags .ftype{font-weight:600;min-width:190px}
ul.flags .fdet{color:var(--muted)}
.ai h2{font-size:18px;color:var(--accent);margin-top:20px}
.ai h3{font-size:15px;color:var(--accent);margin:18px 0 6px}
.ai p{margin:8px 0} .ai ul{margin:6px 0 6px 20px} .ai li{margin:4px 0}
.ai code{background:#1e293b;padding:1px 5px;border-radius:4px;font-size:13px}
table.trades{width:100%;border-collapse:collapse;font-size:13px}
table.trades th,table.trades td{padding:6px 8px;border-bottom:1px solid var(--line);text-align:left}
table.trades th{color:var(--muted);font-weight:600;text-transform:uppercase;font-size:11px}
td.pos{color:var(--green)} td.neg{color:var(--red)}
.footer{color:var(--muted);font-size:12px;margin-top:30px;text-align:center}
"""


def build_html(metrics: dict, ai_text: str, recent: list[dict],
               news: dict | None = None) -> str:
    s = metrics["summary"]
    pf = s["profit_factor"]
    pf_str = "∞" if pf == float("inf") else f"{pf:.2f}"
    total_tone = "good" if s["total_pnl"] >= 0 else "bad"

    cards = "".join([
        _card("Net P&L", _fmt_money(s["total_pnl"]), tone=total_tone),
        _card("Trades", s["n_trades"]),
        _card("Win rate", f'{s["win_rate"]*100:.0f}%',
              f'{s["wins"]}W / {s["losses"]}L'),
        _card("Profit factor", pf_str),
        _card("Expectancy", _fmt_money(s["expectancy"]), "per trade"),
        _card("Avg win / loss", f'{_fmt_money(s["avg_win"])}',
              f'loss {_fmt_money(s["avg_loss"])}'),
        _card("Max drawdown", _fmt_money(s["max_drawdown"]), tone="bad"),
        _card("Avg RR (real/tgt)",
              f'{s["avg_rr_realized"] or "-"}/{s["avg_rr_targeted"] or "-"}'),
        _card("Streaks W/L",
              f'{s["max_win_streak"]}/{s["max_loss_streak"]}'),
    ])

    bars = (
        '<div class="grid2">'
        f'<div>{_svg_bars(metrics["by_instrument"], "P&L by Instrument")}</div>'
        f'<div>{_svg_bars(metrics["by_setup"], "P&L by Setup")}</div>'
        f'<div>{_svg_bars(metrics["by_hour"], "P&L by Hour")}</div>'
        f'<div>{_svg_bars(metrics["by_dayofweek"], "P&L by Day of Week")}</div>'
        '</div>')

    news_note = ""
    if news:
        missing = [d for d, v in news.items() if v is None]
        if missing:
            news_note = (f'<p class="muted">Note: economic-calendar data is only '
                         f'available for the current week; {len(missing)} traded '
                         f'day(s) predate the free feed.</p>')

    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Trade Journal — {metrics.get('date_range','')}</title>
<style>{CSS}</style></head><body><div class="wrap">
<h1>📓 Trading Journal Dashboard</h1>
<div class="sub-hd">Range: {html.escape(metrics.get('date_range','—'))} ·
Generated {metrics.get('generated_at','')} · AI: {html.escape(ai.backend_label())}</div>

<div class="cards">{cards}</div>

<div class="panel"><h2>Equity Curve</h2>{_svg_equity(metrics["equity_curve"])}</div>

<div class="panel"><h2>Breakdowns</h2>{bars}</div>

<div class="panel"><h2>⚠️ Behavior Flags</h2>{_flags_html(metrics["behavior_flags"])}</div>

<div class="panel ai"><h2>🤖 Claude Coaching</h2>{news_note}{_md_to_html(ai_text)}</div>

<div class="panel"><h2>Recent Trades</h2>{_recent_table(recent)}</div>

<div class="footer">Local trade journal · runs entirely on your machine ·
not investment advice</div>
</div></body></html>"""


def write_report(metrics, ai_text, recent, news=None) -> Path:
    config.REPORTS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = config.REPORTS_DIR / f"report_{stamp}.html"
    path.write_text(build_html(metrics, ai_text, recent, news), encoding="utf-8")
    return path
