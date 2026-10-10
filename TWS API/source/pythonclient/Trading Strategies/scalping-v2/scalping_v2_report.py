"""Builds backtest_results.html for the Scalping v2 bot (called by `python scalping_v2_backtest.py --html`)."""
import html
import json
import os
import re

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
COLORS = {"ALL": "#0b0b0b", "ib_trend": "#2a78d6", "orb2nd": "#eb6834", "h2l2_trend": "#7a3fb8", "confluence_pb": "#008300"}
LABEL = {"ib_trend": "IB Trend Breakout", "orb2nd": "ORB Second Break", "h2l2_trend": "H2/L2 Trend Pullback",
         "confluence_pb": "Trend-Confluence Pullback", "ALL": "Portfolio (all)"}


def _css():
    src = open(os.path.join(HERE, "configuration.html"), encoding="utf-8").read() if os.path.exists(
        os.path.join(HERE, "configuration.html")) else ""
    m = re.search(r"<style>(.*?)</style>", src, re.S)
    return m.group(1) if m else "body{font-family:Segoe UI,Arial,sans-serif;max-width:1000px;margin:auto}"


def _svg(series: dict, w=900, h=260, pad=46):
    vals = [v for s in series.values() for _, v in s] + [0]
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1
    n = max(len(s) for s in series.values())
    X = lambda i: pad + i * (w - 2 * pad) / max(n - 1, 1)
    Y = lambda v: h - pad + (lo - v) * (h - 2 * pad) / span
    first = next(iter(series.values()))
    out = [f'<svg viewBox="0 0 {w} {h}" width="100%" style="max-width:{w}px">',
           f'<line x1="{pad}" x2="{w - pad}" y1="{Y(0):.1f}" y2="{Y(0):.1f}" stroke="#aaa" stroke-dasharray="3 3"/>',
           f'<text x="4" y="{Y(hi) + 4:.0f}" font-size="11" fill="#888">${hi:,.0f}</text>',
           f'<text x="4" y="{Y(lo) + 4:.0f}" font-size="11" fill="#888">${lo:,.0f}</text>']
    for k in (0, n // 2, n - 1):
        out.append(f'<text x="{X(k):.0f}" y="{h - 12}" font-size="11" fill="#888" text-anchor="middle">{first[k][0]}</text>')
    ly = 16
    for name, s in series.items():
        pts = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, (_, v) in enumerate(s))
        wdt = 2.6 if name == "ALL" else 1.6
        out.append(f'<polyline fill="none" stroke="{COLORS.get(name, "#555")}" stroke-width="{wdt}" points="{pts}"/>')
        out.append(f'<text x="{w - pad + 4}" y="{ly}" font-size="11" fill="{COLORS.get(name, "#555")}">'
                   f'{LABEL.get(name, name)} ${s[-1][1]:,.0f}</text>')
        ly += 15
    out.append("</svg>")
    return "".join(out)


def _row_table(S, acct, years):
    """Scorecard rows with yearly return and max drawdown in $ and % of account_size_usd."""
    rows = []
    v = S[S.part == "ALL"].reset_index(drop=True)
    iS, oS = S[S.part == "IS"].reset_index(drop=True), S[S.part == "OOS"].reset_index(drop=True)
    for k, r in v.iterrows():
        if r.n == 0:
            continue
        good = "good" if r.pf >= 1.1 else ("" if r.pf >= 1 else "bad")
        yr = r.net / years
        rdd = yr / r.dd if r.dd > 0 else float("inf")
        bold = " style='font-weight:700'" if r.sym == "ALL" else ""
        rows.append(f"<tr{bold}><td>{LABEL.get(r.strategy, r.strategy)}</td><td>{r.sym}</td><td>{r.n}</td><td>{r.win:.0%}</td>"
                    f"<td>{r.tgt:.0%}</td><td class='{good}'><b>{r.pf:.2f}</b></td><td>${r.net:,.0f}</td>"
                    f"<td class='{'good' if yr > 0 else 'bad'}'>${yr:,.0f}<br><b>{yr / acct:+.1%}</b></td>"
                    f"<td>${r.dd:,.0f}<br><b>{r.dd / acct:.1%}</b></td><td>{rdd:.1f}</td>"
                    f"<td>{r.avgR:+.2f}</td><td>{r.sharpe:.2f}</td><td>{iS.loc[k, 'pf']:.2f}</td><td>{oS.loc[k, 'pf']:.2f}</td></tr>")
    return ("<table><thead><tr><th>Strategy</th><th>Sym</th><th>Trades</th><th>Win%</th><th>2R hit</th><th>PF</th>"
            "<th>Net $</th><th>Yearly $ / %</th><th>Max DD $ / %</th><th>Yearly / DD</th><th>Avg R</th><th>Sharpe</th>"
            "<th>PF IS</th><th>PF OOS</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>")


def _dow_section(cfg, args, alldays, acct, years):
    return "".join(_other_market(cfg, args, alldays, acct, years, sym, micro, div)
                   for sym, micro, div in (("YM", "MYM", 10), ("CL", "MCL", 10)))


def _other_market(cfg, args, alldays, acct, years, SYM, MICRO, DIV):
    """All four strategies standalone on one extra market (full-size; micro = / DIV)."""
    import copy
    import scalping_v2_backtest as BT
    c = copy.deepcopy(cfg)
    c["symbols"] = {SYM: dict(cfg["symbols"].get(SYM, {"exchange": BT.C.SPECS[SYM]["exchange"], "contracts": 1}), enabled=True)}
    c["symbols"][SYM]["max_risk_usd"] = 1e9
    for st in c["strategies"].values():
        st["symbols"], st["enabled"] = [SYM], True
    TT, dd = BT.run(c, args.data, args.start, args.slip, False, None)
    if TT.empty:
        return f"<p>No {SYM}/{MICRO} data.</p>"
    sp = pd.Timestamp(args.split).date()
    ymdays = sorted(dd.get(SYM, alldays))
    rows = []
    for name, g in TT.groupby("strategy"):
        m = BT.C.metrics(g, ymdays)
        mi = BT.C.metrics(g[g.day < sp], [d for d in ymdays if d < sp])
        mo = BT.C.metrics(g[g.day >= sp], [d for d in ymdays if d >= sp])
        yr = m["net"] / years
        cls = 'good' if m['pf'] >= 1.1 else ('' if m['pf'] >= 1 else 'bad')
        rows.append(f"<tr><td>{LABEL.get(name, name)}</td><td>{m['n']}</td><td>{m['win']:.0%}</td><td>{m['tgt']:.0%}</td>"
                    f"<td class='{cls}'><b>{m['pf']:.2f}</b></td>"
                    f"<td>{m['avgR']:+.2f}</td><td>${yr:,.0f} <b>({yr / acct:+.1%})</b></td><td>${m['dd']:,.0f} <b>({m['dd'] / acct:.1%})</b></td>"
                    f"<td>${yr / DIV:,.0f} / ${m['dd'] / DIV:,.0f}</td><td>{mi['pf']:.2f}</td><td>{mo['pf']:.2f}</td></tr>")
    on = cfg["symbols"].get(SYM, {}).get("enabled", False)
    return (f"<h3>{SYM} ({MICRO} = / {DIV}) · {ymdays[0]} → {ymdays[-1]} · {'ENABLED' if on else 'disabled in config'}</h3>"
            f"<table><thead><tr><th>Strategy (on {SYM})</th><th>Trades</th><th>Win%</th><th>2R hit</th><th>PF</th><th>Avg R</th>"
            f"<th>{SYM} yearly $ (%)</th><th>{SYM} max DD $ (%)</th><th>{MICRO} yearly $ / DD $</th><th>PF IS</th><th>PF OOS</th></tr></thead><tbody>"
            + "".join(rows) + "</tbody></table>")


def futures_window_html(cfg, data_dir, start, slip, acct, split=None, only_syms=None):
    """Time-window breakdown of each strategy on its configured futures (1 contract per trade, $ and % of acct).
    only_syms: run every strategy on these symbols instead (e.g. ["CL"] for a market that is not enabled)."""
    import copy
    import scalping_v2_backtest as BT
    import scalping_v2_windows as W
    frames, lists = {}, {}
    if only_syms:
        cfg = copy.deepcopy(cfg)
        for sym in only_syms:
            cfg["symbols"].setdefault(sym, {"exchange": BT.C.SPECS[sym]["exchange"], "contracts": 1})
            cfg["symbols"][sym]["enabled"] = True
        for st in cfg["strategies"].values():
            st["symbols"] = list(only_syms)
    for name, sc in cfg["strategies"].items():
        if sc.get("enabled", True):
            lists[name] = [x for x in sc.get("symbols", []) if cfg["symbols"].get(x, {}).get("enabled", True)]
    for sym in sorted({x for v in lists.values() for x in v}):
        spec = dict(BT.C.SPECS[sym])
        spec["comm"] = float(cfg.get("commission_per_side", {}).get(sym, spec["comm"]))
        df = BT.C.add_indicators(BT.load_csv_bars(cfg["symbols"][sym].get("data_symbol", spec.get("data", sym)), data_dir, start), spec["tick"])
        frames[sym] = (df, spec)
    T = W.window_trades(frames, cfg, lists, slip)
    T["R"] = T.r
    days = sorted({d for df, _ in frames.values() for d in df.day.unique()})
    years = (max(days) - min(days)).days / 365.25
    S = W.summarize(T, years, "net", split)
    return W.html_tables(S, cfg, lambda v: f"${v:,.0f}<br><b>{v / acct:+.1%}</b>", lambda v: f"${v:,.0f}<br><b>{v / acct:.1%}</b>",
                         f"1 full-size contract per trade, each strategy standalone on its configured symbols, % of account_size_usd "
                         f"(${acct:,.0f}), {years:.2f} years. Same params; only the entry window / mode change. ★ = what the bot runs. "
                         f"Event setups (IB Trend 11:00 confirm, ORB) can only fire in windows that contain their setup time.",
                         show_years=split is not None), S


def build(T, S, days, cfg, args):
    import scalping_v2_backtest as BT
    alldays = sorted({d for v in days.values() for d in v})
    taken = T[T.taken]
    # equity curves (portfolio mode)
    series = {}
    for name, g in [("ALL", taken)] + list(taken.groupby("strategy")):
        eq = g.groupby("day").net.sum().reindex(alldays, fill_value=0).cumsum()
        series[name] = [(str(d), float(x)) for d, x in eq.items()]
    # monthly
    mon = taken.assign(m=pd.to_datetime(taken.day).dt.to_period("M").astype(str)).pivot_table(
        index="strategy", columns="m", values="net", aggfunc="sum", fill_value=0)
    mon.loc["ALL"] = mon.sum()
    acct = float(cfg.get("account_size_usd", 150000))
    years = max((max(alldays) - min(alldays)).days / 365.25, 0.25)
    syms_traded = sorted({x for st in cfg["strategies"].values() if st.get("enabled", True) for x in st.get("symbols", [])
                          if cfg["symbols"].get(x, {}).get("enabled", True)})
    data_note = ", ".join(f"{x} from {BT.C.SPECS[x].get('data', x)}" for x in syms_traded)
    win_html, _ = futures_window_html(cfg, args.data, args.start, args.slip, acct, args.split)
    # variants
    var_rows = []
    for label, kw in (("As configured (portfolio rules on)", dict(slip=args.slip, portfolio=True)),
                      ("Strategies independent (no one-position-per-symbol)", dict(slip=args.slip, portfolio=False)),
                      ("Slippage 2 ticks per fill (stress)", dict(slip=2, portfolio=True))):
        TT, dd = BT.run(cfg, args.data, args.start, kw["slip"], kw["portfolio"], args.strategies)
        tk = TT[TT.taken]
        m = BT.C.metrics(tk, alldays)
        var_rows.append(f"<tr><td>{label}</td><td>{m['n']}</td><td>{m['win']:.0%}</td><td><b>{m['pf']:.2f}</b></td>"
                        f"<td>${m['net']:,.0f}</td><td>${m['net'] / years:,.0f} <b>({m['net'] / years / acct:+.1%})</b></td>"
                        f"<td>${m['dd']:,.0f} <b>({m['dd'] / acct:.1%})</b></td><td>{m['sharpe']:.2f}</td></tr>")
    skipped = T[~T.taken].groupby(["strategy", "skip"]).size().reset_index(name="n")
    # validation files
    def tail(f, k=2):
        p = os.path.join(HERE, f)
        if not os.path.exists(p):
            return "(not run yet)"
        lines = [x.strip() for x in open(p, encoding="utf-8", errors="replace").read().splitlines() if x.strip()]
        return "<br>".join(html.escape(x) for x in lines[-k:])
    scfg = cfg["strategies"]
    strat_rows = "".join(
        f"<tr><td>{LABEL.get(n, n)}</td><td><code>{n}</code></td><td>{', '.join(s.get('symbols', []))}</td>"
        f"<td>{s.get('window', ['', ''])[0]}–{s.get('window', ['', ''])[1]}</td><td>{s.get('mode')}</td>"
        f"<td><code>{html.escape(json.dumps(s.get('params', {})))}</code></td></tr>" for n, s in scfg.items() if s.get("enabled", True))
    first, last = min(alldays), max(alldays)
    tot = S[(S.strategy == "ALL") & (S.sym == "ALL") & (S.part == "ALL")].iloc[0]
    doc = f"""<!DOCTYPE html><html lang="en" data-theme="light"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Scalping v2 Bot — Backtest Results</title>
<style>{_css()} td.good{{color:var(--good)}} td.bad{{color:#c0392b}} .big{{font-size:28px;font-weight:700}}</style></head>
<body><div class="wrap">
<header><div><h1>Scalping v2 Bot — Backtest Results</h1>
<p class="sub">{' · '.join(syms_traded)} · RTH 5-min bars {first} → {last} ({len(alldays)} sessions, {years:.2f} yrs) · config <code>{os.path.basename(args.config)}</code>
· % figures on account_size_usd = ${acct:,.0f} (simple, non-compounded)
· generated by <code>python scalping_v2_backtest.py --html</code></p></div>
<button class="toggle" onclick="var r=document.documentElement;r.dataset.theme=r.dataset.theme==='dark'?'light':'dark'">◐ Theme</button></header>

<div class="callout warn"><strong>Read this first.</strong> ~13 months of clean 5-min data, {int(tot.n)} trades. Fills are modelled
conservatively (1 tick slippage per market/stop fill, target needs a 1-tick trade-through, stop wins a stop/target tie) but this is
still a backtest — none of these results is statistically significant on its own (best pooled t ≈ 1.3 in the research). The four
strategies + windows were <em>selected</em> from a 260-cell study, so expect live results to be weaker. Paper-trade for weeks first.</div>

<div class="grid2"><div class="card"><div class="sub">Portfolio — yearly return / max drawdown on ${acct:,.0f}</div>
<div class="big">{tot.net / years / acct:+.1%} / {tot.dd / acct:.1%}</div>
<div class="sub">${tot.net / years:,.0f}/yr · max DD ${tot.dd:,.0f} · PF {tot.pf:.2f} · win {tot.win:.0%} · 2R hit {tot.tgt:.0%} · Sharpe {tot.sharpe:.2f}
· net ${tot.net:,.0f} over {years:.2f} yrs (1 contract per signal)</div></div>
<div class="card"><div class="sub">In-sample (&lt; {args.split}) vs out-of-sample</div>
<div class="big">{S[(S.strategy == 'ALL') & (S.sym == 'ALL') & (S.part == 'IS')].pf.iloc[0]:.2f} → {S[(S.strategy == 'ALL') & (S.sym == 'ALL') & (S.part == 'OOS')].pf.iloc[0]:.2f}</div>
<div class="sub">profit factor, IS → OOS (OOS = May–Oct 2026, never used to pick rules)</div></div></div>

<div class="toc"><a href="#strats">Strategies</a><a href="#score">Scorecard</a><a href="#windows">Time windows</a><a href="#equity">Equity</a><a href="#monthly">Monthly</a>
<a href="#variants">Variants &amp; stress</a><a href="#dow">YM &amp; CL</a><a href="#valid">Validation</a><a href="#method">Method</a></div>

<h2 id="strats">Strategies traded (from <code>{os.path.basename(args.config)}</code>)</h2>
<table><thead><tr><th>Strategy</th><th>Key</th><th>Symbols</th><th>Entry window ET</th><th>Mode</th><th>Params</th></tr></thead>
<tbody>{strat_rows}</tbody></table>
<p>Mode <b>hold</b> = after entry, hold to 2R target / stop / 16:00. Mode <b>flat</b> = also forced out at the window end.
Every trade: structural stop, target = 2 × risk from the actual fill.</p>

<h2 id="score">Scorecard (portfolio rules on — exactly how the bot trades)</h2>
{_row_table(S, acct, years)}
<p class="sub">2R hit = share of trades that reached the 2:1 target; the rest exit on the stop or at the window/session end.
IB Trend rarely reaches 2R (wide IB-midpoint stop) — most of its winners are closed at 16:00.</p>

<p class="sub">Yearly $ = net / {years:.2f} years; % = / account_size_usd (${acct:,.0f}). Max DD = largest peak-to-trough drop of the
daily equity curve. Full-size contracts are priced from the micro bar history (same underlying): {data_note}. Micro equivalent = $ / 10.</p>

<h2 id="windows">Time windows — return per entry window</h2>
<p>Each strategy re-run with entries allowed only in the window shown (Y1 R = before {args.split}, Y2 R = after).</p>
{win_html}

<h2 id="equity">Equity curves</h2>{_svg(series)}

<h2 id="monthly">Monthly P&amp;L ($, 1 contract)</h2>
<table><thead><tr><th>Strategy</th>{''.join(f'<th>{c[2:]}</th>' for c in mon.columns)}</tr></thead><tbody>
{''.join('<tr><td>' + LABEL.get(i, i) + '</td>' + ''.join(f'<td class="{"good" if v > 0 else "bad"}">{v:,.0f}</td>' for v in r.values) + '</tr>' for i, r in mon.iterrows())}
</tbody></table>

<h2 id="variants">Variants &amp; stress</h2>
<table><thead><tr><th>Variant</th><th>Trades</th><th>Win%</th><th>PF</th><th>Net $</th><th>Yearly $ (%)</th><th>Max DD $ (%)</th><th>Sharpe</th></tr></thead>
<tbody>{''.join(var_rows)}</tbody></table>
<p>Signals skipped by the portfolio rules: {', '.join(f"{LABEL.get(r.strategy, r.strategy)} – {r.skip}: {r.n}" for r in skipped.itertuples()) or 'none'}.
<code>one_position_per_symbol=false</code> trades every signal (more P&amp;L, similar drawdown) but lets strategies hold opposite
positions in the same contract; the default <code>true</code> is simpler and safer to reconcile.</p>

<h2 id="dow">Other markets — Dow (YM/MYM) and Crude oil (CL/MCL), all four strategies standalone</h2>
{_dow_section(cfg, args, alldays, acct, years)}
<p class="sub">YM and CL are in the config with <code>enabled:false</code> unless shown ENABLED. YM priced from the MYM 5-min RTH history; CL from
full-session CL bars cut to 09:30–16:00 ET (IB's CL "RTH" is the 09:00–14:30 pit). Enable a market per strategy only where it is clearly
positive in-sample <em>and</em> out-of-sample.</p>

<h2 id="valid">Validation (live code == backtest)</h2>
<table><tbody>
<tr><td><b>Parity test</b> <code>scalping_v2_parity_test.py</code></td><td>Live decision function fed only completed bars, bar by bar, over the full
history, must reproduce every backtest trade.<br><span class="sub">{tail('parity_full.txt', 1)}</span></td></tr>
<tr><td><b>Broker simulation</b> <code>scalping_v2_sim_test.py</code></td><td>The real bot code (signals → bracket orders → fills → target re-anchor →
cancel/expire → window/EOD flatten → trade CSV) against a fake IB filling from historical bars, vs the backtest.<br>
<span class="sub">{tail('sim_full.txt', 3)}</span></td></tr>
<tr><td><b>IB Gateway (paper)</b></td><td><code>--status</code>: front-month contracts resolved (MNQZ6/MESZ6/MGCZ6), 80+ sessions of RTH history,
today's decisions replayed. <code>--test-orders MNQ</code>: bracket accepted (PreSubmitted) and cancelled. Foreign-exposure guard
correctly blocked MGC (account held +4 MGCZ6 from the supertrend bot).</td></tr>
</tbody></table>

<h2 id="method">Method</h2>
<ul>
<li>Data: <code>Historical Data/data/{{SYM}}_cont_5mins_rth.csv</code> + <code>_5m_recent.csv</code> (IB continuous futures, RTH), sessions from {args.start}
(older rows in those files are forward-fill padded). Bars 09:30–15:55 ET.</li>
<li>Entries on the bar close → next bar open (+1 tick) or a stop-entry order; stop-market exits (+1 tick); 2R limit target from the
actual fill; same-bar stop/target → stop; commission {', '.join(f'{k} ${v}' for k, v in cfg.get('commission_per_side', {}).items())} per side.</li>
<li>Portfolio rules (same as the bot): one position per symbol (earlier entry wins, then <code>strategy_priority</code>),
<code>max_risk_usd</code> per symbol, <code>max_trades_per_day</code>, <code>daily_loss_limit_usd</code>.</li>
<li>Research behind the selection: <code>scalping-v1/RR2_Strategy_Report.md</code> and <code>Windows_Report.md</code>
(18 strategy families, 160+ configs, time-window study).</li>
</ul>
<div class="foot">Not financial advice. Paper-first. Scalping v2 bot · scalping_v2_backtest.py</div>
</div></body></html>"""
    open(os.path.join(HERE, "backtest_results.html"), "w", encoding="utf-8").write(doc)
