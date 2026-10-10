"""Stocks_Report.html: the Scalping v2 strategies on liquid stocks / ETFs (runs the backtests itself)."""
import json
import os
import re
import subprocess
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LABEL = {"ib_trend": "IB Trend Breakout", "orb2nd": "ORB Second Break", "h2l2_trend": "H2/L2 Trend Pullback",
         "confluence_pb": "Trend-Confluence Pullback"}
ETFS = ["SPY", "QQQ", "IWM", "DIA"]


def run_bt(slip, comm):
    subprocess.run([sys.executable, os.path.join(HERE, "backtest_stocks.py"), "--slip", str(slip), "--comm", str(comm)],
                   check=True, capture_output=True)
    tag = f"slip{slip}_comm{comm}"
    return (pd.read_csv(os.path.join(HERE, "results", f"stock_trades_{tag}.csv")),
            pd.read_csv(os.path.join(HERE, "results", f"stock_summary_{tag}.csv")))


RISK_PCT = 0.005          # risk per trade as % of account for the % columns (0.5%)


def yr_dd(g, years):
    """(yearly R, max drawdown R) from the daily-summed equity curve of trade set g."""
    d = g.groupby("day").R_net.sum().sort_index().cumsum()
    dd = float((d.cummax().clip(lower=0) - d).max()) if len(d) else 0.0
    return g.R_net.sum() / years, dd


def cls(v, good=0.05, bad=0.0):
    if pd.isna(v):
        return ""
    return "good" if v >= good else ("bad" if v < bad else "")


FUT = ["NQ", "ES", "GC", "YM", "CL"]


def stock_window_html(T_syms, years, split):
    """Time-window breakdown on index ETFs and on large-cap stocks (R-based, % at RISK_PCT)."""
    import copy
    import json as _json
    sys.path.insert(0, ROOT)
    import scalping_v2_windows as W
    from backtest_stocks import load as load_stock
    cfg = _json.load(open(os.path.join(ROOT, "scalping_v2.json"), encoding="utf-8"))
    spec = dict(pv=1.0, tick=0.01, comm=0.0)
    frames = {s: (load_stock(s), spec) for s in T_syms}
    out = []
    for grp, syms in (("Index ETFs", [s for s in T_syms if s in ETFS]), ("Large-cap stocks", [s for s in T_syms if s not in ETFS])):
        c = copy.deepcopy(cfg)
        for st in c["strategies"].values():
            st["symbols"] = syms
        T = W.window_trades({s: frames[s] for s in syms}, c, {k: syms for k in c["strategies"]}, 1)
        T["R"] = (T.pts - 2 * 0.0035) / T.risk
        S = W.summarize(T, years, "R", split)
        out.append(f"<h3 style='margin-top:26px'>{grp}: {', '.join(syms)}</h3>")
        out.append(W.html_tables(S, c, lambda v: f"{v:+.1f}R<br><b>{v * RISK_PCT:+.1%}</b>", lambda v: f"{v:.1f}R<br><b>{v * RISK_PCT:.1%}</b>",
                                 f"Yearly / Max DD in R (all symbols in the group traded together) and % at {RISK_PCT:.1%} risk per trade. "
                                 f"Y1 = Oct 2024–Sep 2025, Y2 = Oct 2025–Oct 2026 (avg R per trade). ★ = the window the futures bot uses.",
                                 show_years=True))
    return "".join(out)


def futures_sections(T, stock_years):
    """Futures (NQ/ES/GC/YM) with the same strategies/engine: matrix, comparison vs ETFs/stocks, bot portfolio."""
    import copy
    import json as _json
    sys.path.insert(0, ROOT)
    import scalping_v2_backtest as BT
    cfg = _json.load(open(os.path.join(ROOT, "scalping_v2.json"), encoding="utf-8"))
    acct = float(cfg.get("account_size_usd", 150000))

    def run(c, portfolio):
        TT, dd = BT.run(c, BT.DEFAULT_DATA, "2025-09-02", 1, portfolio, None)
        TT = TT[TT.taken].copy()
        TT["day"] = pd.to_datetime(TT.day)
        TT["R_net"] = TT.net / (TT.risk * TT.pv * TT.qty)
        return TT
    c_all = copy.deepcopy(cfg)                          # every strategy on every future, standalone
    c_all["symbols"] = {k: dict(v, enabled=True, max_risk_usd=1e9) for k, v in cfg["symbols"].items() if k in FUT}
    for k in FUT:
        c_all["symbols"].setdefault(k, {"enabled": True, "exchange": BT.C.SPECS[k]["exchange"], "contracts": 1, "max_risk_usd": 1e9})
    for st in c_all["strategies"].values():
        st["symbols"], st["enabled"] = list(FUT), True
    F = run(c_all, False)
    P = run(cfg, True)                                  # the bot exactly as configured
    fy = (F.day.max() - F.day.min()).days / 365.25
    # matrix
    m = ["<table><thead><tr><th>Strategy</th>" + "".join(f"<th>{x} <span class='sub'>(${BT.C.SPECS[x]['pv']:g}/pt)</span></th>" for x in FUT)
         + "</tr></thead><tbody>"]
    for st in LABEL:
        row = f"<tr><td>{LABEL[st]}</td>"
        for x in FUT:
            g = F[(F.strategy == st) & (F.sym == x)]
            if len(g) < 10:
                row += "<td class='muted'>-</td>"
                continue
            w = g.R_net > 0
            pf = g.R_net[w].sum() / -g.R_net[~w].sum() if (~w).any() else np.inf
            yR, ddR = yr_dd(g, fy)
            on = x in cfg["strategies"][st]["symbols"] and cfg["symbols"].get(x, {}).get("enabled", True)
            row += (f"<td class='{cls(g.R_net.mean())}'><b>{g.R_net.mean():+.2f}R</b>{' ✓' if on else ''}<br>"
                    f"<span class='sub'>n={len(g)} · PF {pf:.2f}<br>{yR:+.1f}R/yr ({yR * RISK_PCT:+.1%}) · DD {ddR:.1f}R ({ddR * RISK_PCT:.1%})<br>"
                    f"1 lot: ${g.net.sum() / fy:,.0f}/yr ({g.net.sum() / fy / acct:+.1%}) · DD ${dd_usd(g):,.0f} ({dd_usd(g) / acct:.1%})</span></td>")
        m.append(row + "</tr>")
    m.append("</tbody></table>")
    # comparison per strategy: futures (pooled NQ+ES+GC) vs ETFs vs stocks, R/trade + yearly % @ RISK_PCT
    cmp_rows = []
    Tg = T.assign(grp=np.where(T.sym.isin(ETFS), "ETFs", "Stocks"))
    for st in LABEL:
        cells = []
        for name, g, yrs in (("Futures NQ/ES/GC", F[(F.strategy == st) & F.sym.isin(["NQ", "ES", "GC"])], fy),
                             ("Index ETFs", Tg[(Tg.strategy == st) & (Tg.grp == "ETFs")], stock_years),
                             ("Large-cap stocks", Tg[(Tg.strategy == st) & (Tg.grp == "Stocks")], stock_years)):
            if not len(g):
                cells.append("<td>-</td>")
                continue
            yR, ddR = yr_dd(g, yrs)
            cells.append(f"<td class='{cls(g.R_net.mean())}'><b>{g.R_net.mean():+.3f}R</b> <span class='sub'>(n={len(g)})</span><br>"
                         f"<span class='sub'>{yR * RISK_PCT:+.1%}/yr · DD {ddR * RISK_PCT:.1%}</span></td>")
        cmp_rows.append(f"<tr><td>{LABEL[st]}</td>{''.join(cells)}</tr>")
    cmp = ("<table><thead><tr><th>Strategy</th><th>Futures NQ/ES/GC (13 mo)</th><th>Index ETFs (2 yrs)</th><th>Large-cap stocks (2 yrs)</th></tr></thead>"
           "<tbody>" + "".join(cmp_rows) + "</tbody></table>")
    py = (P.day.max() - P.day.min()).days / 365.25
    pR, pDD = yr_dd(P, py)
    port = (f"<tr><td><b>Futures bot as configured</b> (NQ/ES/GC, 1 contract per signal, one position per symbol)</td><td>{len(P) / py:.0f}</td>"
            f"<td>{P.R_net.mean():+.3f}</td><td>{pR:+.1f}R</td><td><b>{pR * RISK_PCT:+.1%}</b></td><td>{pDD:.1f}R</td><td><b>{pDD * RISK_PCT:.1%}</b></td>"
            f"<td>{pR * 0.01:+.1%}</td><td>{pDD * 0.01:.1%}</td></tr>"
            f"<tr><td colspan=9 class='sub'>Same futures bot in dollars (1 contract each, not risk-sized): ${P.net.sum() / py:,.0f}/yr = "
            f"<b>{P.net.sum() / py / acct:+.1%}</b> of ${acct:,.0f}; max DD ${dd_usd(P):,.0f} = <b>{dd_usd(P) / acct:.1%}</b>. "
            f"Futures history is only 13 months (Sep 2025 – Oct 2026) — it has no 'Y1' test year.</td></tr>")
    return "".join(m), cmp, port


def dd_usd(g):
    d = g.groupby("day").net.sum().sort_index().cumsum()
    return float((d.cummax().clip(lower=0) - d).max()) if len(d) else 0.0


def main():
    css = re.search(r"<style>(.*?)</style>", open(os.path.join(ROOT, "configuration.html"), encoding="utf-8").read(), re.S).group(1)
    T, S = run_bt(1, 0.0035)
    T2, S2 = run_bt(2, 0.005)
    T["day"] = pd.to_datetime(T.day)
    split = pd.Timestamp("2025-10-01")
    syms = sorted(T.sym.unique(), key=lambda s: (s not in ETFS, s))
    strategies = list(LABEL)
    first, last = T.day.min().date(), T.day.max().date()
    years = (T.day.max() - T.day.min()).days / 365.25

    # matrix: avg R per trade, by strategy x symbol (both years) + year split
    def cell(g):
        if len(g) < 10:
            return "<td class='muted'>–</td>"
        y1, y2 = g[g.day < split].R_net.mean(), g[g.day >= split].R_net.mean()
        w = g.R_net > 0
        pf = g.R_net[w].sum() / -g.R_net[~w].sum() if (~w).any() else np.inf
        both = "★" if (y1 > 0 and y2 > 0 and len(g) >= 30) else ""
        return (f"<td class='{cls(g.R_net.mean())}'><b>{g.R_net.mean():+.2f}R</b> {both}<br>"
                f"<span class='sub'>n={len(g)} · PF {pf:.2f}<br>Y1 {y1:+.2f} · Y2 {y2:+.2f}</span></td>")
    mat = ["<table><thead><tr><th>Strategy</th>" + "".join(f"<th>{s}</th>" for s in syms) + "</tr></thead><tbody>"]
    for st in strategies:
        mat.append(f"<tr><td>{LABEL[st]}</td>" + "".join(cell(T[(T.strategy == st) & (T.sym == s)]) for s in syms) + "</tr>")
    mat.append("</tbody></table>")

    # pooled by strategy x group x year
    T["group"] = np.where(T.sym.isin(ETFS), "ETFs", "Stocks")
    T["year"] = np.where(T.day < split, "Y1 Oct24–Sep25", "Y2 Oct25–Oct26")
    pool = []
    for st in strategies:
        for grp in ("ETFs", "Stocks"):
            g = T[(T.strategy == st) & (T.group == grp)]
            if not len(g):
                continue
            w = g.R_net > 0
            pf = g.R_net[w].sum() / -g.R_net[~w].sum()
            tt = g.R_net.mean() / g.R_net.std() * np.sqrt(len(g))
            y = g.groupby("year").R_net.mean()
            g2 = T2[(T2.strategy == st) & (T2.sym.isin(ETFS) == (grp == "ETFs"))]
            yR, ddR = yr_dd(g, years)
            pool.append(f"<tr><td>{LABEL[st]}</td><td>{grp}</td><td>{len(g)}</td><td>{w.mean():.0%}</td>"
                        f"<td>{(g.why == 'target').mean():.0%}</td><td class='{cls(g.R_net.mean())}'><b>{g.R_net.mean():+.3f}</b></td>"
                        f"<td>{pf:.2f}</td><td>{tt:+.2f}</td><td class='{cls(y.iloc[0])}'>{y.iloc[0]:+.3f}</td>"
                        f"<td class='{cls(y.iloc[-1])}'>{y.iloc[-1]:+.3f}</td><td class='{cls(g2.R_net.mean())}'>{g2.R_net.mean():+.3f}</td>"
                        f"<td class='{cls(yR, 0.01)}'>{yR:+.1f}R<br><b>{yR * RISK_PCT:+.1%}</b></td>"
                        f"<td>{ddR:.1f}R<br><b>{ddR * RISK_PCT:.1%}</b></td>"
                        f"<td>${g.usd.sum():,.0f}</td></tr>")
    # robust list: positive in both years, n>=30
    rob = []
    for (st, s), g in T.groupby(["strategy", "sym"]):
        y1, y2 = g[g.day < split].R_net, g[g.day >= split].R_net
        if len(g) >= 30 and y1.mean() > 0 and y2.mean() > 0:
            g2 = T2[(T2.strategy == st) & (T2.sym == s)]
            yR, ddR = yr_dd(g, years)
            rob.append((g.R_net.mean(), f"<tr><td>{LABEL[st]}</td><td>{s}</td><td>{len(g)}</td><td><b>{g.R_net.mean():+.3f}</b></td>"
                                        f"<td>{yR:+.1f}R ({yR * RISK_PCT:+.1%})</td><td>{ddR:.1f}R ({ddR * RISK_PCT:.1%})</td>"
                                        f"<td>{y1.mean():+.3f} ({len(y1)})</td><td>{y2.mean():+.3f} ({len(y2)})</td>"
                                        f"<td class='{cls(g2.R_net.mean())}'>{g2.R_net.mean():+.3f}</td><td>${g.usd.sum():,.0f}</td></tr>"))
    rob = [r for _, r in sorted(rob, reverse=True)]
    # cross-check output
    cc = subprocess.run([sys.executable, os.path.join(HERE, "crosscheck_etf_vs_futures.py")], capture_output=True, text=True).stdout
    cc_rows = []
    for line in cc.splitlines()[1:]:
        p = line.split()
        if len(p) >= 9:
            cc_rows.append(f"<tr><td>{LABEL.get(p[0], p[0])}</td><td>{p[1]} vs {p[3]}</td><td>{p[4]} · {float(p[5]):+.3f}R</td>"
                           f"<td>{p[6]} · {float(p[7]):+.3f}R</td><td>{float(p[8]):.0%}</td></tr>")
    tot = T.R_net.mean()
    cand = T[((T.strategy == "ib_trend") & T.sym.isin(["MSFT", "AAPL", "META", "AMD", "NVDA", "SPY", "QQQ"]))
             | ((T.strategy == "orb2nd") & T.sym.isin(["QQQ", "IWM"]))]
    cR, cDD = yr_dd(cand, years)
    aR, aDD = yr_dd(T, years)
    cand_html = (f"<table><thead><tr><th>Portfolio</th><th>Trades/yr</th><th>Avg R</th><th>Yearly R</th><th>Yearly % @ {RISK_PCT:.1%} risk</th>"
                 f"<th>Max DD R</th><th>Max DD % @ {RISK_PCT:.1%}</th><th>Yearly % @ 1% risk</th><th>Max DD % @ 1%</th></tr></thead><tbody>"
                 f"<tr><td>Candidate set: IB Trend on MSFT/AAPL/META/AMD/NVDA/SPY/QQQ + ORB 2nd on QQQ/IWM</td><td>{len(cand) / years:.0f}</td>"
                 f"<td>{cand.R_net.mean():+.3f}</td><td>{cR:+.1f}R</td><td><b>{cR * RISK_PCT:+.1%}</b></td><td>{cDD:.1f}R</td>"
                 f"<td><b>{cDD * RISK_PCT:.1%}</b></td><td>{cR * 0.01:+.1%}</td><td>{cDD * 0.01:.1%}</td></tr>"
                 f"<tr><td>All 4 strategies × all 13 symbols</td><td>{len(T) / years:.0f}</td><td>{T.R_net.mean():+.3f}</td><td>{aR:+.1f}R</td>"
                 f"<td class='bad'><b>{aR * RISK_PCT:+.1%}</b></td><td>{aDD:.1f}R</td><td><b>{aDD * RISK_PCT:.1%}</b></td>"
                 f"<td>{aR * 0.01:+.1%}</td><td>{aDD * 0.01:.1%}</td></tr>"
                 "{FUTPORT}</tbody></table>"
                 "<p class='sub'>The candidate set was chosen AFTER seeing these results (both-years survivors), so its numbers are optimistic.</p>")
    fut_html, fut_cmp, fut_port = futures_sections(T, years)
    cand_html = cand_html.replace("{FUTPORT}", fut_port)
    sys.path.insert(0, ROOT)
    import scalping_v2_report as FR
    _cfg = json.load(open(os.path.join(ROOT, "scalping_v2.json"), encoding="utf-8"))
    import scalping_v2_backtest as _BT
    fut_win_html, _ = FR.futures_window_html(_cfg, _BT.DEFAULT_DATA, "2025-09-02", 1, float(_cfg.get("account_size_usd", 150000)), "2026-05-01")
    stk_win_html = stock_window_html(syms, years, split)
    oth_win_html = ""
    for _sym, _nm in (("CL", "Crude oil CL (disabled in the bot)"), ("YM", "Dow YM (disabled in the bot)")):
        _h, _ = FR.futures_window_html(_cfg, _BT.DEFAULT_DATA, "2025-09-02", 1, float(_cfg.get("account_size_usd", 150000)), "2026-05-01", [_sym])
        oth_win_html += f"<h3 style='margin-top:26px'>{_nm} — every strategy, 1 contract per trade</h3>" + _h
    doc = f"""<!DOCTYPE html><html lang="en" data-theme="light"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Scalping v2 strategies — futures, ETFs &amp; stocks</title>
<style>{css} td.good{{color:var(--good);}} td.bad{{color:#c0392b}} .muted{{color:var(--muted)}}</style></head><body><div class="wrap">
<header><div><h1>Scalping v2 strategies — futures, ETFs &amp; stocks</h1>
<p class="sub">Futures NQ · ES · GC · YM · CL (Sep 2025 – Oct 2026) and {', '.join(syms)} · 5-min RTH bars from IB · {first} → {last} (2 years) · same engine, windows and parameters as <code>scalping_v2.json</code></p></div>
<button class="toggle" onclick="var r=document.documentElement;r.dataset.theme=r.dataset.theme==='dark'?'light':'dark'">◐ Theme</button></header>

<div class="callout warn"><strong>Verdict: not as-is.</strong> Across all 13 symbols and 2 years the four strategies average
<b>{tot:+.3f}R</b> per trade after costs. Year 2 (Oct 2025–Oct 2026, the period the futures strategies were selected on) is
positive on the index ETFs — and SPY/QQQ track MES/MNQ almost signal-for-signal — but Year 1 (Oct 2024–Sep 2025, never used for
selection) is mostly negative. That is the honest out-of-sample test, and most of the edge does not survive it. Only a handful of
strategy × symbol pairs were positive in <em>both</em> years (★ below).</div>

<div class="toc"><a href="#port">Yearly % / DD</a><a href="#compare">Futures vs ETFs vs stocks</a><a href="#futures">Futures matrix</a><a href="#windows">Time windows</a><a href="#matrix">Strategy × symbol</a><a href="#pool">ETFs vs stocks</a><a href="#robust">Both-years survivors</a>
<a href="#cross">ETF vs futures</a><a href="#method">Method</a></div>

<h2 id="port">Yearly return &amp; drawdown — portfolios</h2>
{cand_html}

<h2 id="compare">Each strategy: futures vs index ETFs vs stocks</h2>
{fut_cmp}
<p class="sub">Avg R per trade net of costs; % columns at {RISK_PCT:.1%} account risk per trade (yearly % = yearly R × {RISK_PCT:.1%}).</p>

<h2 id="futures">Futures — every strategy on NQ · ES · GC · YM · CL</h2>
{fut_html}
<p class="sub">✓ = enabled in <code>scalping_v2.json</code>. Same engine/windows/params, standalone (no one-position-per-symbol). Full-size contracts
priced from the micro 5-min RTH history (MNQ/MES/MGC/MYM, Sep 2025 – Oct 2026); costs 1 tick slippage per fill + $2.25–2.42/side.
R and % rows are size-independent; "1 lot" rows are 1 full-size contract per trade on account_size_usd.</p>

<h2 id="windows">Time windows — return per entry window</h2>
<p>Every strategy re-run with entries allowed only inside each window (same params). <b>HOLD</b> = hold to 2R / stop / 16:00;
<b>FLAT</b> = out at the window end. ★ = what the futures bot currently runs.</p>
<h3 style="margin-top:18px">Futures (bot symbols: NQ / ES / GC) — 1 contract per trade, % of account_size_usd</h3>
{fut_win_html}
{oth_win_html}
{stk_win_html}

<h2 id="matrix">Stocks &amp; ETFs — average R per trade (net of costs), every strategy on every symbol</h2>
{''.join(mat)}
<p class="sub">Y1 = Oct 2024 – Sep 2025 (new data, never used to pick the strategies) · Y2 = Oct 2025 – Oct 2026 (overlaps the futures selection period).
★ = positive in both years with ≥ 30 trades. Break-even is 0R; +0.10R ≈ a good intraday edge.</p>

<h2 id="pool">Pooled: index ETFs vs single stocks</h2>
<table><thead><tr><th>Strategy</th><th>Group</th><th>Trades</th><th>Win%</th><th>2R hit</th><th>Avg R</th><th>PF</th><th>t-stat</th>
<th>Y1 avg R</th><th>Y2 avg R</th><th>Avg R @ 2¢ slip + $0.005/sh</th><th>Yearly R / %</th><th>Max DD R / %</th>
<th>$ @ $1k risk/trade (2 yrs)</th></tr></thead><tbody>{''.join(pool)}</tbody></table>
<p class="sub">% columns assume risk of {RISK_PCT:.1%} of the account per trade: yearly % = yearly R × {RISK_PCT:.1%}, DD % = max-DD R × {RISK_PCT:.1%}
(simple, non-compounded; all symbols in the group traded together, so concurrent trades are included in the drawdown).</p>

<h2 id="robust">Survivors: positive in both years (≥ 30 trades)</h2>
<table><thead><tr><th>Strategy</th><th>Symbol</th><th>Trades</th><th>Avg R</th><th>Yearly R (%)</th><th>Max DD R (%)</th><th>Y1 R (n)</th><th>Y2 R (n)</th><th>R @ higher costs</th><th>$ @ $1k risk</th></tr></thead>
<tbody>{''.join(rob) or '<tr><td colspan=8>none</td></tr>'}</tbody></table>
<p>Even these are small samples (≈30–60 trades a year per symbol); with ~50 strategy × symbol combinations tested, a few will be
positive in both years by chance. Treat them as candidates to paper-trade, not as proven.</p>

<h2 id="cross">Same dates, ETF vs future (2025-09-02 → 2026-10-07)</h2>
<table><thead><tr><th>Strategy</th><th>Pair</th><th>ETF trades · avg R</th><th>Future trades · avg R</th><th>Same day + direction</th></tr></thead>
<tbody>{''.join(cc_rows)}</tbody></table>
<p>The breakout strategies fire on the same days in the same direction on SPY/MES and QQQ/MNQ (95–100%), with similar results — the
strategies transfer to the ETFs mechanically. The difference between the futures backtest and the 2-year stock test is the
<b>extra (older) year</b>, i.e. regime, not the instrument. That also means the futures bot would likely have struggled in 2024-25 too.</p>

<h2 id="method">Method</h2>
<ul><li>Data: IB 5-min TRADES, useRTH, 2 × 1-year requests per symbol (<code>download_stocks_5m_rth.py</code>) →
<code>Historical Data/data/equity_rth/</code>. Same day filter as the bot (session opens 09:30, ≥ 40 bars).</li>
<li>Engine: <code>scalping_v2_core.simulate</code> — identical to the futures bot. Strategies/windows/params from <code>scalping_v2.json</code>
(IB Trend 09:30–11:30 hold, ORB 2nd 09:30–11:30 flat, H2/L2 09:30–11:30 hold, Confluence 13:30–16:00 hold), applied to every symbol.</li>
<li>Costs: 1¢ slippage per market/stop fill + $0.0035/share/side commission (stress: 2¢ + $0.005). R = (P&amp;L/share − costs) / risk/share.</li>
<li>$ figures: $1,000 risk per trade, shares capped at $250k notional, no compounding, each strategy × symbol independent.</li></ul>
<div class="foot">Generated by <code>stocks/make_stock_report.py</code> · not financial advice</div>
</div></body></html>"""
    open(os.path.join(HERE, "Stocks_Report.html"), "w", encoding="utf-8").write(doc)
    print("wrote Stocks_Report.html; overall avg R", round(tot, 4))
    print(T.groupby(["strategy", "group", "year"]).R_net.agg(["count", "mean"]).round(3).to_string())
    print("survivors:", len(rob))


if __name__ == "__main__":
    main()
