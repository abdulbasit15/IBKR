"""Build the Intraday-Equity documentation set (dependency-free except openpyxl).

Does two things:
  1. Generates the per-strategy PERFORMANCE pages (.md + .html) from the faithful backtest
     Excel reports in ../reports/ -- summary tiles, equity curve, daily P&L, exit mix.
  2. Renders EVERY *.md in this folder (logic, README, AI_HANDOVER, the generated
     performance .md) to a matching self-contained *.html using one shared theme.

No pandas / matplotlib / markdown dependency: a tiny Markdown->HTML renderer and hand-built
inline SVG charts keep the output offline-openable (just double-click the .html).

Run:  python docs/build_docs.py
"""
from __future__ import annotations
import html
import os
import re

import openpyxl

DOCS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(DOCS)
REPORTS = os.path.join(ROOT, "reports")

# Backtest window covered by the current faithful reports (see the daily tables for exact dates).
BT_WINDOW = "last ~1 month (2026-08-07 → 2026-09-04)"

# strategy_key -> (title, report filename, one-line verdict banner)
STRATS = {
    "pdh_breakout": (
        "PDH Breakout", "bt_faithful_PDH___9_35.xlsx",
        "Strongly positive IN THIS 1-MONTH SAMPLE (win rate ~82%, PF ~9) — consistent with the "
        "earlier 6-week run, but it leans on high-beta momentum names in a trending tape and "
        "assumes clean limit fills. Not a live promise.",
    ),
    "orb_stocks_in_play": (
        "ORB Stocks-in-Play", "bt_faithful_ORB_SIP___9_35.xlsx",
        "Only a couple of trades fired in this 1-month window — too few to judge. Over the "
        "longer 6-week sample it was net NEGATIVE (classic breakout whipsaw: stops dwarf targets).",
    ),
    "nr7_compression": (
        "NR7 Compression", "bt_faithful_NR7___9_35.xlsx",
        "ZERO trades in the 1-month window — the stacked daily filters (NR7 ∧ ADR>5 ∧ close>SMA20) "
        "rarely fire on the small fixed universe. No sample = no edge claim. Broaden the universe.",
    ),
    "vwap_pullback": (
        "VWAP Pullback / Reclaim", "bt_faithful_VWAP_PB___9_45.xlsx",
        "Net NEGATIVE in the sample (~31% win, PF ~0.4): failed reclaims in chop tag the stop. "
        "Parameter-sensitive; needs a chop filter before it is tradable.",
    ),
}

# ---------------------------------------------------------------- theme
CSS = """
:root{
  --ink:#1f2933; --muted:#67727e; --line:#e3e8ef; --bg:#ffffff; --soft:#f7f9fc;
  --pos:#1f9d63; --neg:#d64545; --accent:#2f6feb; --accent-soft:#eaf1ff;
}
*{box-sizing:border-box}
body{margin:0;background:var(--soft);color:var(--ink);
  font:16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;}
.wrap{max-width:900px;margin:0 auto;padding:40px 24px 80px;}
.card{background:var(--bg);border:1px solid var(--line);border-radius:14px;
  padding:28px 34px;box-shadow:0 1px 3px rgba(16,24,40,.04);}
h1{font-size:30px;line-height:1.25;margin:.2em 0 .4em;letter-spacing:-.01em}
h2{font-size:22px;margin:1.6em 0 .5em;padding-top:.3em;border-top:1px solid var(--line)}
h2:first-of-type{border-top:none;padding-top:0}
h3{font-size:17px;margin:1.3em 0 .4em}
h1+p,h2+p{margin-top:.2em}
p{margin:.7em 0}
a{color:var(--accent);text-decoration:none}
a:hover{text-decoration:underline}
code{background:var(--soft);border:1px solid var(--line);border-radius:5px;
  padding:.08em .35em;font:13.5px/1.4 "SFMono-Regular",Consolas,"Liberation Mono",monospace}
pre{background:#0f172a;color:#e2e8f0;border-radius:12px;padding:16px 18px;overflow:auto}
pre code{background:none;border:none;color:inherit;padding:0;font-size:13px}
blockquote{margin:1em 0;padding:.6em 1em;background:var(--accent-soft);
  border-left:4px solid var(--accent);border-radius:0 8px 8px 0;color:#243b53}
blockquote.warn{background:#fff4f0;border-left-color:var(--neg);color:#7a271a}
table{border-collapse:collapse;width:100%;margin:1em 0;font-size:14.5px}
th,td{border:1px solid var(--line);padding:8px 11px;text-align:left;vertical-align:top}
th{background:var(--soft);font-weight:600}
tr:nth-child(even) td{background:#fbfcfe}
hr{border:none;border-top:1px solid var(--line);margin:2em 0}
ul,ol{margin:.6em 0 .6em 1.3em;padding:0}
li{margin:.25em 0}
.tiles{display:flex;flex-wrap:wrap;gap:14px;margin:1.2em 0}
.tile{flex:1 1 140px;background:var(--soft);border:1px solid var(--line);
  border-radius:12px;padding:14px 16px}
.tile .k{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}
.tile .v{font-size:24px;font-weight:700;margin-top:4px;letter-spacing:-.01em}
.v.pos{color:var(--pos)} .v.neg{color:var(--neg)}
.chart{margin:1.4em 0}
.chart .cap{font-size:13px;color:var(--muted);margin:.2em 0 .6em}
.footer{color:var(--muted);font-size:13px;margin-top:40px;text-align:center}
svg{max-width:100%;height:auto;display:block}
"""

# ---------------------------------------------------------------- tiny markdown -> html
def _inline(t: str) -> str:
    t = html.escape(t, quote=False)
    t = re.sub(r"`([^`]+)`", lambda m: f"<code>{m.group(1)}</code>", t)
    t = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', t)
    t = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", t)
    return t


def md_to_html(md: str) -> str:
    lines = md.split("\n")
    out, i, n = [], 0, len(lines)
    while i < n:
        ln = lines[i]
        # fenced code
        if ln.startswith("```"):
            code = []
            i += 1
            while i < n and not lines[i].startswith("```"):
                code.append(html.escape(lines[i])); i += 1
            i += 1
            out.append("<pre><code>" + "\n".join(code) + "</code></pre>")
            continue
        if not ln.strip():
            i += 1; continue
        if re.match(r"^#{1,6}\s", ln):
            lvl = len(ln) - len(ln.lstrip("#"))
            out.append(f"<h{lvl}>{_inline(ln[lvl:].strip())}</h{lvl}>")
            i += 1; continue
        if re.match(r"^(---+|\*\*\*+)\s*$", ln):
            out.append("<hr>"); i += 1; continue
        # blockquote (one or more > lines, tolerant of leading indent)
        if ln.lstrip().startswith(">"):
            buf = []
            while i < n and lines[i].lstrip().startswith(">"):
                buf.append(lines[i].lstrip().lstrip(">").strip()); i += 1
            cls = ' class="warn"' if buf and buf[0].startswith(("⚠", "WARNING", "!")) else ""
            out.append(f"<blockquote{cls}>{_inline(' '.join(buf))}</blockquote>")
            continue
        # table
        if "|" in ln and i + 1 < n and re.match(r"^\s*\|?[\s:|-]+\|?\s*$", lines[i + 1]) and "-" in lines[i + 1]:
            def cells(row):
                return [c.strip() for c in row.strip().strip("|").split("|")]
            head = cells(ln); i += 2
            rows = []
            while i < n and "|" in lines[i] and lines[i].strip():
                rows.append(cells(lines[i])); i += 1
            th = "".join(f"<th>{_inline(c)}</th>" for c in head)
            body = ""
            for r in rows:
                body += "<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in r) + "</tr>"
            out.append(f"<table><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table>")
            continue
        # lists
        if re.match(r"^\s*[-*]\s+", ln):
            items = []
            while i < n and re.match(r"^\s*[-*]\s+", lines[i]):
                items.append(_inline(re.sub(r"^\s*[-*]\s+", "", lines[i]))); i += 1
            out.append("<ul>" + "".join(f"<li>{x}</li>" for x in items) + "</ul>")
            continue
        if re.match(r"^\s*\d+\.\s+", ln):
            items = []
            while i < n and re.match(r"^\s*\d+\.\s+", lines[i]):
                items.append(_inline(re.sub(r"^\s*\d+\.\s+", "", lines[i]))); i += 1
            out.append("<ol>" + "".join(f"<li>{x}</li>" for x in items) + "</ol>")
            continue
        # passthrough for chart markers
        if ln.strip().startswith("@@CHART:"):
            out.append(ln.strip()); i += 1; continue
        # paragraph (gather until blank)
        buf = [ln]; i += 1
        while i < n and lines[i].strip() and not re.match(
                r"^(#{1,6}\s|```|>|\s*[-*]\s+|\s*\d+\.\s+|---+\s*$)", lines[i]) and "|" not in lines[i]:
            buf.append(lines[i]); i += 1
        out.append(f"<p>{_inline(' '.join(buf))}</p>")
    return "\n".join(out)


def page(title: str, body_html: str, up="README.html") -> str:
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title><style>{CSS}</style></head>
<body><div class="wrap"><div class="card">
{body_html}
<div class="footer">Intraday Equity Bots · generated by <code>docs/build_docs.py</code> ·
<a href="{up}">docs index</a></div>
</div></div></body></html>"""


# ---------------------------------------------------------------- charts (inline SVG)
def _fmt(v):
    return f"${v:,.0f}"


def svg_equity(daily):
    """Cumulative gross P&L line over trading days."""
    if not daily:
        return ""
    cum, running = [], 0.0
    for d in daily:
        running += d["pnl"]; cum.append(running)
    W, H, pad = 760, 260, 44
    lo, hi = min(0, min(cum)), max(0, max(cum))
    rng = (hi - lo) or 1
    def x(i): return pad + i * (W - 2 * pad) / max(1, len(cum) - 1)
    def y(v): return H - pad - (v - lo) / rng * (H - 2 * pad)
    pts = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(cum))
    zero = y(0)
    area = f"M{x(0):.1f},{zero:.1f} " + " ".join(f"L{x(i):.1f},{y(v):.1f}" for i, v in enumerate(cum)) + f" L{x(len(cum)-1):.1f},{zero:.1f} Z"
    end_col = "var(--pos)" if cum[-1] >= 0 else "var(--neg)"
    gy = "".join(f'<line x1="{pad}" y1="{y(lo+rng*t):.1f}" x2="{W-pad}" y2="{y(lo+rng*t):.1f}" stroke="var(--line)"/>'
                 f'<text x="{pad-6}" y="{y(lo+rng*t)+4:.1f}" text-anchor="end" font-size="11" fill="var(--muted)">{_fmt(lo+rng*t)}</text>'
                 for t in (0, .5, 1))
    return f'''<svg viewBox="0 0 {W} {H}" role="img" aria-label="Cumulative P&L">
{gy}
<line x1="{pad}" y1="{zero:.1f}" x2="{W-pad}" y2="{zero:.1f}" stroke="#c3cbd6" stroke-dasharray="3 3"/>
<path d="{area}" fill="{end_col}" opacity="0.10"/>
<polyline points="{pts}" fill="none" stroke="{end_col}" stroke-width="2.5"/>
<text x="{x(len(cum)-1):.1f}" y="{y(cum[-1])-8:.1f}" text-anchor="end" font-size="12" font-weight="700" fill="{end_col}">{_fmt(cum[-1])}</text>
</svg>'''


def svg_daily_bars(daily):
    if not daily:
        return ""
    W, H, pad = 760, 220, 34
    vals = [d["pnl"] for d in daily]
    amax = max(abs(min(vals)), abs(max(vals))) or 1
    bw = (W - 2 * pad) / len(vals)
    mid = H / 2
    bars = ""
    for i, v in enumerate(vals):
        h = abs(v) / amax * (H / 2 - pad / 2)
        yy = mid - h if v >= 0 else mid
        col = "var(--pos)" if v >= 0 else "var(--neg)"
        bars += f'<rect x="{pad+i*bw+1:.1f}" y="{yy:.1f}" width="{max(1,bw-2):.1f}" height="{h:.1f}" fill="{col}"/>'
    return f'''<svg viewBox="0 0 {W} {H}" role="img" aria-label="Daily P&L">
<line x1="{pad}" y1="{mid}" x2="{W-pad}" y2="{mid}" stroke="#c3cbd6"/>
{bars}
<text x="{pad}" y="16" font-size="11" fill="var(--muted)">+P&L</text>
<text x="{pad}" y="{H-6}" font-size="11" fill="var(--muted)">-P&L &nbsp; ({len(vals)} trading days)</text>
</svg>'''


def svg_exit_bars(reasons):
    if not reasons:
        return ""
    order = sorted(reasons.items(), key=lambda kv: -kv[1][1])
    W = 760; rowh = 46; pad = 120; H = rowh * len(order) + 20
    amax = max(abs(v[1]) for v in reasons.values()) or 1
    rows = ""
    for i, (k, (cnt, pnl)) in enumerate(order):
        yy = 12 + i * rowh
        w = abs(pnl) / amax * (W - pad - 130)
        col = "var(--pos)" if pnl >= 0 else "var(--neg)"
        x0 = pad
        rows += f'<text x="{pad-10}" y="{yy+rowh/2:.0f}" text-anchor="end" font-size="13" font-weight="600" fill="var(--ink)">{k}</text>'
        rows += f'<rect x="{x0}" y="{yy+8:.0f}" width="{w:.1f}" height="{rowh-22}" rx="3" fill="{col}"/>'
        rows += f'<text x="{x0+w+8:.1f}" y="{yy+rowh/2+4:.0f}" font-size="12" fill="var(--muted)">{cnt} trades · {_fmt(pnl)}</text>'
    return f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Exit reason P&L">{rows}</svg>'


# ---------------------------------------------------------------- read a report
def read_report(path):
    wb = openpyxl.load_workbook(path, data_only=True)
    summ = {}
    for row in wb["Summary"].iter_rows(values_only=True):
        if row and row[0] and row[0] != "Metric":
            summ[str(row[0])] = row[1]
    daily = []
    if "Daily" in wb.sheetnames:
        rows = list(wb["Daily"].iter_rows(values_only=True))[1:]
        for r in rows:
            if r and r[0]:
                daily.append({"date": str(r[0]), "trades": r[1], "wins": r[2], "losses": r[3],
                              "wr": r[4], "pnl": float(r[5] or 0), "avgr": r[6]})
    reasons, tickers = {}, {}
    if "Trades" in wb.sheetnames:
        rows = list(wb["Trades"].iter_rows(values_only=True))
        hdr = {h: i for i, h in enumerate(rows[0])}
        ri, pi, ti = hdr.get("Reason"), hdr.get("PnL"), hdr.get("Ticker")
        for r in rows[1:]:
            if r[pi] is None:
                continue
            pnl = float(r[pi])
            k = r[ri] or "?"
            a = reasons.setdefault(k, [0, 0.0]); a[0] += 1; a[1] += pnl
            b = tickers.setdefault(r[ti] or "?", [0, 0.0]); b[0] += 1; b[1] += pnl
    return summ, daily, reasons, tickers


# ---------------------------------------------------------------- performance markdown
def perf_markdown(key):
    title, fname, verdict = STRATS[key]
    path = os.path.join(REPORTS, fname)
    if not os.path.exists(path):
        # no report file == the faithful backtest produced NO trades in the window
        md = f"""# {title} — Backtest Performance

> {verdict}

## Headline ({BT_WINDOW})
| Metric | Value |
|---|---|
| Total trades | **0** |
| Net P/L | $0 |

**No trades were generated** by this strategy over the backtested window, so there is no
report file ([`reports/{fname}`](../reports/{fname}) is absent). This is an outcome, not an
error: every candidate was filtered out before a signal could form. See the
[strategy logic]({key}.logic.md) for the gate stack, and widen the universe / relax the
filters to obtain a testable sample.

## Assumptions & method
- Faithful replay of the live engine ([`../backtest.py`](../backtest.py)); same windows,
  gates, stop floor, breakeven + trail, and EOD flatten as the live bot.
- Costs: 5 bps/side slippage + $0.005/share commission; sizing 1% risk-at-stop on $100,000.
"""
        return md, {}
    summ, daily, reasons, tickers = read_report(path)
    period = f"{daily[0]['date']} → {daily[-1]['date']}" if daily else "n/a"
    net = float(summ.get("Total P/L", 0) or 0)
    wr = summ.get("Win rate %", "n/a")
    pf = summ.get("Profit factor", "n/a")
    trades = summ.get("Total trades", "n/a")
    days = summ.get("Trading days", "n/a")
    avgr = summ.get("Avg R multiple", "n/a")

    top = sorted(tickers.items(), key=lambda kv: -kv[1][1])
    tick_rows = "\n".join(f"| {k} | {v[0]} | ${v[1]:,.0f} |" for k, v in top[:6])
    bot_rows = "\n".join(f"| {k} | {v[0]} | ${v[1]:,.0f} |" for k, v in top[-4:][::-1]) if len(top) > 6 else ""
    reason_rows = "\n".join(f"| {k} | {v[0]} | ${v[1]:,.0f} |"
                            for k, v in sorted(reasons.items(), key=lambda kv: -kv[1][1]))
    daily_rows = "\n".join(
        f"| {d['date']} | {d['trades']} | {d['wins']} | {d['losses']} | {d['wr']} | ${d['pnl']:,.0f} | {d['avgr']} |"
        for d in daily)

    md = f"""# {title} — Backtest Performance

> {verdict}

**Source report:** [`reports/{fname}`](../reports/{fname}) · generated by the faithful replay in
[`../backtest.py`](../backtest.py). See the [strategy logic]({key}.logic.md) for how signals are formed.

## Headline (backtest sample)
| Metric | Value |
|---|---|
| Period (trading days) | {period} ({days} days) |
| Total trades | {trades} |
| Win rate | {wr}% |
| Profit factor | {pf} |
| Avg R / trade | {avgr} |
| Net P/L (1% risk on $100k) | ${net:,.0f} |
| Largest win / loss | ${float(summ.get('Largest win',0) or 0):,.0f} / ${float(summ.get('Largest loss',0) or 0):,.0f} |

## Equity curve (cumulative gross P&L)
@@CHART:equity@@

## Daily P&L
@@CHART:daily@@

## Exit mix (where the P&L comes from)
@@CHART:exits@@

| Exit reason | Trades | Net P/L |
|---|---|---|
{reason_rows}

## Contribution by ticker
| Top tickers | Trades | Net P/L |
|---|---|---|
{tick_rows}
"""
    if bot_rows:
        md += f"""
| Weakest tickers | Trades | Net P/L |
|---|---|---|
{bot_rows}
"""
    md += f"""
## Assumptions & method
- **Faithful replay** of the live engine ([`../backtest.py`](../backtest.py)): same trade
  windows, VWAP-from-bars gate, volume/gap/RVOL filters, `min_stop_pct` stop floor,
  breakeven + trailing stop, and EOD flatten as the live bot.
- **Costs:** 5 bps/side slippage + $0.005/share commission applied to every fill.
- **Sizing:** 1% risk-at-stop on $100,000 (so dollar P/L is readable; R-multiples are sizing-free).
- **Intrabar rule:** stop is checked before target within a bar (conservative).
- **Universe:** the strategy's fixed `universe_symbols` (top names), *not* the live scanner.

## Read this before trusting the numbers
- **Regime & selection bias.** The window is a short stretch of one market regime, and the
  universe is today's liquid movers replayed historically. A strong tape flatters breakout longs.
- **Backtest fills are idealized.** Entries assume a **limit fill at the computed entry**. The
  real 2026-07-16 paper run used **market orders on delayed data** and filled 5–6% past the
  level (see the [logic doc]({key}.logic.md) and [`../logs/logs/PDH___9_35_20260716.log`](../logs/logs/PDH___9_35_20260716.log)).
  Live results track the backtest only once data is **live** and entries are **bounded** (`LMT`).
- **Sample size.** Fewer trades ⇒ weaker conclusions; treat small-n strategies as unproven.
- Past backtest performance does not predict live results. This is research tooling, not advice.

## Daily detail
| Date | Trades | Wins | Losses | Win% | Gross P/L | Avg R |
|---|---|---|---|---|---|---|
{daily_rows}
"""
    charts = {
        "equity": svg_equity(daily),
        "daily": svg_daily_bars(daily),
        "exits": svg_exit_bars(reasons),
    }
    return md, charts


def tiles_html(md):
    """Build stat tiles from the first markdown table (the headline)."""
    return ""  # headline renders as a styled table; tiles optional


def render_html_from_md(md, charts=None, title="Doc"):
    body = md_to_html(md)
    if charts:
        for name, svg in charts.items():
            wrap = f'<div class="chart">{svg}</div>' if svg else "<p><em>(no data for this chart)</em></p>"
            body = body.replace(f"@@CHART:{name}@@", wrap)
    return page(title, body)


def main():
    made = []
    # 1) performance pages (md + html) from reports
    perf_charts = {}
    for key in STRATS:
        md, charts = perf_markdown(key)
        if md is None:
            print(f"  ! {key}: report missing, skipped")
            continue
        md_disk = re.sub(r"@@CHART:(\w+)@@", r"_(chart — see the HTML version)_", md)
        with open(os.path.join(DOCS, f"{key}.performance.md"), "w", encoding="utf-8") as fh:
            fh.write(md_disk)
        perf_charts[f"{key}.performance"] = (md, charts)
        made.append(f"{key}.performance.md")

    # 2) render every .md in docs/ to .html
    for fn in sorted(os.listdir(DOCS)):
        if not fn.endswith(".md"):
            continue
        stem = fn[:-3]
        with open(os.path.join(DOCS, fn), encoding="utf-8") as fh:
            md = fh.read()
        title = re.search(r"^#\s+(.+)", md, re.M)
        title = title.group(1).strip() if title else stem
        if stem in perf_charts:                 # use in-memory md WITH chart markers
            src_md, charts = perf_charts[stem]
            htmlpage = render_html_from_md(src_md, charts, title)
        else:
            htmlpage = render_html_from_md(md, None, title)
        with open(os.path.join(DOCS, f"{stem}.html"), "w", encoding="utf-8") as fh:
            fh.write(htmlpage)
        made.append(f"{stem}.html")
    print("built:", ", ".join(made))


if __name__ == "__main__":
    main()
