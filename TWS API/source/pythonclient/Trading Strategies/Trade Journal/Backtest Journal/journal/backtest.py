"""Backtest journal: turn each strategy's *_trades.csv into an analytics
dashboard (equity curve, R-distribution, drawdown, breakdowns) + AI coaching,
plus a comparison index across all strategies. Standard library only.

CSV columns expected (backtest round-trip legs):
  symbol, strat, entry_id, side, qty, entry_time, entry, exit_time, exit,
  reason, R, pnl
Each row is a *leg* (a trade may exit in parts); a *trade* = (symbol, entry_id).
"""
from __future__ import annotations

import csv
import glob
import html
import json
import statistics
from datetime import datetime, timedelta
from pathlib import Path

from . import ai, config

_VENDOR = Path(__file__).parent / "vendor" / "chart.min.js"

BT_SYSTEM = (
    "You are a quantitative futures strategy analyst reviewing BACKTEST results "
    "(not live discretionary trades). You get one strategy's aggregate stats "
    "over ~2 years on 5-min RTH data across MNQ/MES/MGC, plus how it compares to "
    "the trader's other strategies. Assess it honestly and specifically using the "
    "numbers: overall edge quality (profit factor, expectancy, R-multiple), which "
    "instrument carries it, long vs short skew, exit-reason mix (stops vs 2R "
    "targets vs flips), time-of-day patterns, and drawdown/robustness. Flag "
    "overfitting or fragility risks (e.g. edge concentrated in one symbol, thin "
    "profit factor, huge drawdown vs net). Be direct and quantitative; cite the "
    "strategy's own numbers. Answer in markdown with these sections:\n"
    "## Verdict\n## What's Working\n## Weaknesses & Risks\n"
    "## Best Conditions (symbol / side / time / exit)\n## vs Other Strategies\n"
    "## Top 3 Improvements\n\n"
    "This is strategy-research analysis, not investment advice."
)


# --- parsing ---------------------------------------------------------------
def _num(x):
    try:
        return float(str(x).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _nth_sunday(y, m, n):
    d = datetime(y, m, 1)
    first = 1 + (6 - d.weekday()) % 7
    return datetime(y, m, first + 7 * (n - 1))


def _et_offset(utc):
    """US Eastern UTC offset (-4 EDT / -5 EST) for a UTC instant."""
    start = _nth_sunday(utc.year, 3, 2).replace(hour=7)    # 2nd Sun Mar 02:00 EST
    end = _nth_sunday(utc.year, 11, 1).replace(hour=6)     # 1st Sun Nov 02:00 EDT
    return -4 if start <= utc < end else -5


def _dt_et(s):
    """Parse an offset-aware '...-05:00' timestamp and return a naive ET datetime.

    The feed mixes timezones per instrument (index futures in Central, gold in
    Eastern), so we convert each timestamp via its own offset to UTC, then to
    true US Eastern (applying DST) — never a blanket +1h.
    """
    if not s:
        return None
    s = str(s).strip()
    base, off = s[:19], s[19:].strip()
    try:
        loc = datetime.strptime(base, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        try:
            loc = datetime.strptime(base[:16], "%Y-%m-%d %H:%M")
        except ValueError:
            return None
    if not off:                       # already naive ET (new engine format)
        return loc
    oh = int(off[:3]) if len(off) >= 3 else -5
    om = int(off[4:6]) if len(off) >= 6 else 0
    utc = loc - timedelta(hours=oh, minutes=om)
    return utc + timedelta(hours=_et_offset(utc))


def _pick(r, *names):
    """First non-empty value among alternative column names (old/new formats)."""
    for n in names:
        v = r.get(n)
        if v not in (None, ""):
            return v
    return None


def load_legs(csv_path: Path) -> list[dict]:
    legs = []
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            sym = (r.get("symbol") or "").strip().upper()
            pnl = _num(r.get("pnl"))
            if not sym or pnl is None:
                continue
            qty = _num(r.get("qty")) or 0
            Rpts = _num(_pick(r, "R_points", "R"))
            mult = config.MULTIPLIERS.get(sym, 1)
            risk = (Rpts * mult * qty) if (Rpts and qty) else None
            legs.append({
                "symbol": sym, "entry_id": (r.get("entry_id") or "").strip(),
                "side": (r.get("side") or "").strip().upper(),
                "qty": qty,
                "entry": _num(_pick(r, "entry_price", "entry")),
                "exit": _num(_pick(r, "exit_price", "exit")),
                "entry_dt": _dt_et(_pick(r, "entry_time_et", "entry_time")),
                "exit_dt": _dt_et(_pick(r, "exit_time_et", "exit_time")),
                "reason": (r.get("reason") or "").strip().upper(),
                "pnl": pnl, "risk": risk,
                "r_mult": (pnl / risk) if risk else None,
            })
    legs.sort(key=lambda x: x["exit_dt"] or x["entry_dt"] or datetime.min)
    return legs


# --- analytics -------------------------------------------------------------
def _pf(pnls):
    g = sum(p for p in pnls if p > 0)
    l = -sum(p for p in pnls if p < 0)
    return (g / l) if l else float("inf")


def _stats(pnls):
    n = len(pnls)
    if not n:
        return {"n": 0, "net": 0, "win": 0, "pf": 0, "avg_win": 0, "avg_loss": 0, "exp": 0}
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    return {
        "n": n, "net": round(sum(pnls)),
        "win": round(len(wins) / n * 100, 1),
        "pf": round(_pf(pnls), 2) if _pf(pnls) != float("inf") else 999,
        "avg_win": round(statistics.mean(wins)) if wins else 0,
        "avg_loss": round(statistics.mean(losses)) if losses else 0,
        "exp": round(sum(pnls) / n),
    }


def _trade_pnls(legs):
    """Aggregate legs into trades by (symbol, entry_id)."""
    agg = {}
    for lg in legs:
        agg[(lg["symbol"], lg["entry_id"])] = agg.get((lg["symbol"], lg["entry_id"]), 0) + lg["pnl"]
    return list(agg.values())


def _group(legs, keyfn, order=None):
    buckets = {}
    for lg in legs:
        k = keyfn(lg)
        if k is None:
            continue
        buckets.setdefault(k, []).append(lg["pnl"])
    rows = [{"name": str(k), **_stats(v)} for k, v in buckets.items()]
    if order == "net":
        rows.sort(key=lambda r: r["net"], reverse=True)
    else:
        rows.sort(key=lambda r: str(r["name"]))
    return rows


def compute(legs: list[dict]) -> dict:
    pnls = [lg["pnl"] for lg in legs]
    tp = _trade_pnls(legs)
    s = _stats(tp)                                  # win%/pf/exp over TRADES
    # equity + drawdown over legs (chronological)
    cum, eq, peak, maxdd = 0.0, [], 0.0, 0.0
    for lg in legs:
        cum += lg["pnl"]
        eq.append(round(cum))
        peak = max(peak, cum)
        maxdd = min(maxdd, cum - peak)
    rmults = [lg["r_mult"] for lg in legs if lg["r_mult"] is not None]
    # R histogram buckets
    rbins = {"<-1R": 0, "-1..0R": 0, "0..1R": 0, "1..2R": 0, ">=2R": 0}
    for r in rmults:
        if r < -1:
            rbins["<-1R"] += 1
        elif r < 0:
            rbins["-1..0R"] += 1
        elif r < 1:
            rbins["0..1R"] += 1
        elif r < 2:
            rbins["1..2R"] += 1
        else:
            rbins[">=2R"] += 1
    dates = [lg["exit_dt"] for lg in legs if lg["exit_dt"]]
    dow = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    best = max(legs, key=lambda x: x["pnl"], default=None)
    worst = min(legs, key=lambda x: x["pnl"], default=None)
    return {
        "legs": len(legs), "trades": s["n"], "net": round(sum(pnls)),
        "win": s["win"], "pf": s["pf"], "exp_trade": s["exp"],
        "avg_win": s["avg_win"], "avg_loss": s["avg_loss"],
        "max_dd": round(maxdd),
        "two_r_hits": sum(1 for r in rmults if r >= 2),
        "avg_r": round(statistics.mean(rmults), 2) if rmults else 0,
        "period": (f"{min(dates).date()} → {max(dates).date()}" if dates else ""),
        "symbols": sorted({lg["symbol"] for lg in legs}),
        "equity": eq,
        "rbins": rbins,
        "by_symbol": _group(legs, lambda l: l["symbol"], "net"),
        "by_side": _group(legs, lambda l: l["side"], "net"),
        "by_reason": _group(legs, lambda l: l["reason"], "net"),
        "by_hour": _group(legs, lambda l: f"{l['entry_dt'].hour:02d}:00" if l["entry_dt"] else None),
        "by_dow": _group(legs, lambda l: dow[l["entry_dt"].weekday()] if l["entry_dt"] else None),
        "best": best, "worst": worst,
    }


# --- discovery -------------------------------------------------------------
_SKIP_DIRS = {"backups_orig", "backups", "_orig_backup", "_backup", "reports"}


def discover(root: Path) -> list[tuple[str, Path]]:
    """Find every *_trades.csv under root; strategy name = parent folder name.
    Skips backup/report folders so they aren't treated as strategies."""
    out = []
    for p in sorted(glob.glob(str(root / "**" / "*_trades.csv"), recursive=True)):
        path = Path(p)
        if _SKIP_DIRS & {part.lower() for part in path.parts}:
            continue
        out.append((path.parent.name, path))
    return out


# --- HTML ------------------------------------------------------------------
def _e(x):
    return html.escape(str(x))


def _money(v):
    v = round(v or 0)
    cls = "pos" if v > 0 else "neg" if v < 0 else "mut"
    return f'<span class="{cls}">{"-$" if v < 0 else "$"}{abs(v):,}</span>'


def _tile(label, val, sub=""):
    return (f'<div class="tile"><div class="tl">{_e(label)}</div>'
            f'<div class="tv">{val}</div>'
            f'<div class="ts">{_e(sub)}</div></div>')


def _table(title, rows, cols):
    head = "".join(f"<th>{_e(h)}</th>" for h, _ in cols)
    body = ""
    for r in rows:
        tds = ""
        for _, key in cols:
            v = r.get(key)
            if key == "net":
                tds += f"<td>{_money(v)}</td>"
            elif key in ("win",):
                tds += f"<td>{v}%</td>"
            else:
                tds += f"<td>{_e(v)}</td>"
        body += f"<tr>{tds}</tr>"
    return (f'<div class="card"><h3>{_e(title)}</h3><table><thead><tr>{head}</tr>'
            f'</thead><tbody>{body}</tbody></table></div>')


def _md(t):
    """Minimal markdown -> HTML for the AI section."""
    out, in_ul = [], False
    for ln in (t or "").split("\n"):
        esc = _e(ln)
        import re
        esc = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", esc)
        if ln.lstrip().startswith("#"):
            if in_ul:
                out.append("</ul>"); in_ul = False
            out.append(f"<h4>{esc.lstrip('#').strip()}</h4>")
        elif ln.strip().startswith(("- ", "* ")):
            if not in_ul:
                out.append("<ul>"); in_ul = True
            out.append(f"<li>{esc.strip()[2:]}</li>")
        elif ln.strip() == "":
            if in_ul:
                out.append("</ul>"); in_ul = False
        else:
            if in_ul:
                out.append("</ul>"); in_ul = False
            out.append(f"<p>{esc}</p>")
    if in_ul:
        out.append("</ul>")
    return "\n".join(out)


_CSS = """
*{box-sizing:border-box} body{margin:0;background:#0b0e14;color:#e6edf3;
font:14px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;padding:22px}
a{color:#7c9cff} h1{margin:0 0 2px} h3{margin:0 0 10px;font-size:14px}
.sub{color:#8b98a9;margin-bottom:18px}
.tiles{display:flex;flex-wrap:wrap;gap:10px;margin-bottom:18px}
.tile{background:#151a23;border:1px solid #232a36;border-radius:10px;padding:10px 14px;min-width:120px}
.tl{color:#8b98a9;font-size:11px;text-transform:uppercase;letter-spacing:.04em}
.tv{font-size:20px;font-weight:700;margin:3px 0} .ts{color:#8b98a9;font-size:11px}
.pos{color:#3fb950} .neg{color:#f85149} .mut{color:#8b98a9}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.card{background:#151a23;border:1px solid #232a36;border-radius:10px;padding:14px;margin-bottom:14px}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{text-align:left;padding:5px 8px;border-bottom:1px solid #232a36}
th{color:#8b98a9;font-weight:600} .ai h4{color:#b9a7ff;margin:14px 0 4px}
.ai p,.ai li{color:#cdd6e0} canvas{max-height:280px}
.symbar{margin-bottom:14px;color:#8b98a9;font-size:13px}
.symbtn{background:#151a23;color:#cdd6e0;border:1px solid #232a36;border-radius:7px;
padding:5px 14px;margin-left:6px;cursor:pointer;font-size:13px;font-weight:600}
.symbtn:hover{border-color:#3a475a}
.symbtn.on{background:#7c9cff;color:#0b0e14;border-color:#7c9cff}
.bar{height:10px;background:#232a36;border-radius:5px;overflow:hidden;display:inline-block;width:120px;vertical-align:middle}
@media(max-width:800px){.grid{grid-template-columns:1fr}}
"""


def _view(m2) -> dict:
    """Slim a computed-metrics dict into the JSON a client-side view needs."""
    eq = m2["equity"]
    step = max(1, len(eq) // 1500)
    return {
        "net": m2["net"], "trades": m2["trades"], "legs": m2["legs"],
        "win": m2["win"], "pf": m2["pf"], "exp": m2["exp_trade"],
        "avg_win": m2["avg_win"], "avg_loss": m2["avg_loss"],
        "max_dd": m2["max_dd"], "two_r": m2["two_r_hits"], "avg_r": m2["avg_r"],
        "equity": eq[::step], "rbins": m2["rbins"],
        "side": m2["by_side"], "reason": m2["by_reason"],
        "hour": m2["by_hour"], "dow": m2["by_dow"],
    }


def render_strategy(name, legs, m, ai_text, chartjs, back_link=True) -> str:
    # Build a filterable view per instrument (+ "All").
    views = {"All": _view(m)}
    for sym in m["symbols"]:
        views[sym] = _view(compute([l for l in legs if l["symbol"] == sym]))
    sym_cols = [("Symbol", "name"), ("Legs", "n"), ("Win%", "win"), ("PF", "pf"),
                ("Exp", "exp"), ("Net", "net")]
    ai_html = (f'<div class="card ai"><h3>🤖 AI strategy analysis</h3>{_md(ai_text)}</div>'
               if ai_text and not ai_text.startswith("[AI") else
               (f'<div class="card ai"><h3>🤖 AI strategy analysis</h3>'
                f'<p class="mut">{_e(ai_text)}</p></div>' if ai_text else ""))
    back = '<a href="index.html">← all strategies</a>' if back_link else ""
    buttons = "".join(
        f'<button class="symbtn" data-sym="{_e(k)}">{_e(k)}</button>'
        for k in views)
    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>{_e(name)} — Backtest Journal</title><style>{_CSS}</style>
<script>{chartjs}</script></head><body>
{back}
<h1>{_e(name)}</h1>
<div class="sub">{_e(m['period'])} · {_e(', '.join(m['symbols']))} · 5-min RTH backtest</div>
<div class="symbar">Instrument: {buttons}</div>
<div class="tiles" id="tiles"></div>
<div class="card"><h3>Equity curve (cumulative $) — <span id="eqsym"></span></h3><canvas id="eq"></canvas></div>
<div class="grid">
  {_table("By symbol (all)", m["by_symbol"], sym_cols)}
  <div class="card"><h3>By side</h3><div id="t_side"></div></div>
  <div class="card"><h3>By exit reason</h3><div id="t_reason"></div></div>
  <div class="card"><h3>R-multiple distribution</h3><div id="t_r"></div></div>
  <div class="card"><h3>By entry hour (ET)</h3><div id="t_hour"></div></div>
  <div class="card"><h3>By day of week</h3><div id="t_dow"></div></div>
</div>
{ai_html}
<script>
const V = {json.dumps(views)};
let chart;
function money(v){{v=Math.round(v||0);var c=v>0?'pos':v<0?'neg':'mut';
  return '<span class="'+c+'">'+(v<0?'-$':'$')+Math.abs(v).toLocaleString()+'</span>';}}
function tbl(rows, cols){{
  var h=cols.map(c=>'<th>'+c[0]+'</th>').join('');
  var b=rows.map(function(r){{return '<tr>'+cols.map(function(c){{
    var k=c[1],v=r[k];
    if(k==='net')return '<td>'+money(v)+'</td>';
    if(k==='win')return '<td>'+v+'%</td>';
    return '<td>'+(v==null?'':v)+'</td>';}}).join('')+'</tr>';}}).join('');
  return '<table><thead><tr>'+h+'</tr></thead><tbody>'+b+'</tbody></table>';}}
function tile(l,val,s){{return '<div class="tile"><div class="tl">'+l+'</div>'+
  '<div class="tv">'+val+'</div><div class="ts">'+(s||'')+'</div></div>';}}
function rHtml(rb){{var keys=['<-1R','-1..0R','0..1R','1..2R','>=2R'];
  var mx=Math.max.apply(null,keys.map(k=>rb[k]||0))||1;
  return '<table><tbody>'+keys.map(function(k){{
    var v=rb[k]||0,bad=(k.indexOf('-')>=0||k==='0..1R');
    return '<tr><td>'+k+'</td><td>'+v.toLocaleString()+'</td><td><span class="bar">'+
      '<span style="display:block;height:100%;width:'+Math.round(v/mx*100)+'%;background:'+
      (bad?'#f85149':'#3fb950')+'"></span></span></td></tr>';}}).join('')+'</tbody></table>';}}
function show(sym){{
  var v=V[sym];
  document.getElementById('tiles').innerHTML=[
    tile('Net P&L',money(v.net)), tile('Trades',v.trades.toLocaleString(),v.legs.toLocaleString()+' legs'),
    tile('Win %',v.win+'%'), tile('Profit factor',v.pf),
    tile('Expectancy',money(v.exp),'per trade'),
    tile('Avg win / loss',money(v.avg_win)+' / '+money(v.avg_loss)),
    tile('Max drawdown',money(v.max_dd)), tile('2R+ hits',v.two_r.toLocaleString(),'avg '+v.avg_r+'R')
  ].join('');
  document.getElementById('eqsym').textContent=sym;
  document.getElementById('t_side').innerHTML=tbl(v.side,[['Side','name'],['Legs','n'],['Win%','win'],['Net','net']]);
  document.getElementById('t_reason').innerHTML=tbl(v.reason,[['Exit reason','name'],['Legs','n'],['Win%','win'],['Net','net']]);
  document.getElementById('t_hour').innerHTML=tbl(v.hour,[['Hour (ET)','name'],['Legs','n'],['Win%','win'],['Net','net']]);
  document.getElementById('t_dow').innerHTML=tbl(v.dow,[['Day','name'],['Legs','n'],['Win%','win'],['Net','net']]);
  document.getElementById('t_r').innerHTML=rHtml(v.rbins);
  chart.data.labels=v.equity.map((_,i)=>i);
  chart.data.datasets[0].data=v.equity; chart.update();
  document.querySelectorAll('.symbtn').forEach(function(b){{b.classList.toggle('on',b.dataset.sym===sym);}});
}}
chart=new Chart(document.getElementById('eq'),{{type:'line',
 data:{{labels:[],datasets:[{{data:[],borderColor:'#7c9cff',borderWidth:1.5,
 pointRadius:0,fill:true,backgroundColor:'rgba(124,156,255,.08)'}}]}},
 options:{{animation:false,plugins:{{legend:{{display:false}}}},scales:{{x:{{display:false}},
 y:{{ticks:{{color:'#8b98a9'}},grid:{{color:'#1c222c'}}}}}}}}}});
document.querySelectorAll('.symbtn').forEach(function(b){{b.onclick=function(){{show(b.dataset.sym);}};}});
show('All');
</script></body></html>"""


def render_index(strategies) -> str:
    rows = ""
    for s in sorted(strategies, key=lambda x: x["m"]["net"], reverse=True):
        m = s["m"]
        rows += (f'<tr><td><a href="{_e(s["file"])}">{_e(s["name"])}</a></td>'
                 f'<td>{_money(m["net"])}</td><td>{m["trades"]:,}</td>'
                 f'<td>{m["win"]}%</td><td>{m["pf"]}</td>'
                 f'<td>{_money(m["exp_trade"])}</td><td>{_money(m["max_dd"])}</td>'
                 f'<td>{m["two_r_hits"]:,}</td></tr>')
    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>Backtest Journal — all strategies</title><style>{_CSS}</style></head><body>
<h1>Backtest Journal — strategy comparison</h1>
<div class="sub">Ranked by net P&L · 5-min RTH · MNQ / MES / MGC · click a strategy for its dashboard</div>
<div class="card"><table><thead><tr><th>Strategy</th><th>Net P&L</th><th>Trades</th>
<th>Win%</th><th>PF</th><th>Expectancy</th><th>Max DD</th><th>2R+ hits</th></tr></thead>
<tbody>{rows}</tbody></table></div>
<div class="sub">Generated by the ZTH Backtest Journal.</div>
</body></html>"""


# --- AI --------------------------------------------------------------------
def coach(name, m, context) -> str:
    slim = {k: m[k] for k in ("legs", "trades", "net", "win", "pf", "exp_trade",
            "avg_win", "avg_loss", "max_dd", "two_r_hits", "avg_r", "period",
            "symbols", "by_symbol", "by_side", "by_reason", "by_hour", "by_dow")}
    payload = {"strategy": name, "this_strategy": slim, "all_strategies_net": context}
    prompt = ("Analyze this backtest strategy. Data as JSON:\n\n```json\n"
              + json.dumps(payload, indent=1, default=str) + "\n```")
    return ai.ask(prompt, BT_SYSTEM)


# --- driver ----------------------------------------------------------------
def run(data_dir: Path, out_dir: Path, use_ai: bool = True,
        refresh_ai: bool = False) -> dict:
    found = discover(data_dir)
    if not found:
        return {"strategies": 0, "note": f"No *_trades.csv under {data_dir}"}
    out_dir.mkdir(parents=True, exist_ok=True)
    chartjs = _VENDOR.read_text(encoding="utf-8") if _VENDOR.exists() else ""

    parsed = []
    for name, path in found:
        legs = load_legs(path)
        if not legs:
            continue
        parsed.append({"name": name, "legs": legs, "m": compute(legs)})
        print(f"  {name:28s} {parsed[-1]['m']['legs']:>6,} legs  "
              f"net ${parsed[-1]['m']['net']:,}")

    context = {p["name"]: p["m"]["net"] for p in parsed}
    ai_ready = use_ai and ai.available()
    if use_ai and not ai_ready:
        print("  AI analysis skipped — no Claude backend "
              "(run 'claude' to log in, or set ANTHROPIC_API_KEY).")

    for p in parsed:
        cache = out_dir / f"{p['name']}.ai.md"        # cached AI so re-runs are cheap
        ai_text = ""
        if cache.exists() and not refresh_ai:
            ai_text = cache.read_text(encoding="utf-8")
            print(f"  {p['name']}: using cached AI analysis (--refresh-ai to redo)")
        elif ai_ready:
            print(f"  calling Claude ({ai.backend_label()}) for {p['name']}...")
            ai_text = coach(p["name"], p["m"], context)
            if ai_text.startswith("[AI"):
                print(f"    {ai_text.splitlines()[0]}")
            else:
                cache.write_text(ai_text, encoding="utf-8")
        fname = f"{p['name']}.html"
        (out_dir / fname).write_text(
            render_strategy(p["name"], p["legs"], p["m"], ai_text, chartjs),
            encoding="utf-8")
        p["file"] = fname

    (out_dir / "index.html").write_text(render_index(parsed), encoding="utf-8")
    return {"strategies": len(parsed), "out": out_dir / "index.html",
            "files": [p["file"] for p in parsed]}
