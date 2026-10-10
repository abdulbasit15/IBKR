"""
Time-window breakdown for the bot's strategies (shared by backtest_results.html and stocks/Stocks_Report.html).

For every strategy x entry window x mode the same engine (scalping_v2_core) is re-run with the strategy restricted to
ENTER inside the window:
  hold : enter in the window, manage to 2R / stop / 16:00 (entries <= 15:25)
  flat : enter in the window and be flat by the window end
Strategy parameters stay exactly as in the config; only the window/mode change.
"""
from __future__ import annotations

import copy
import numpy as np
import pandas as pd

import scalping_v2_core as C

SESSIONS = [("09:30", "11:30"), ("11:30", "13:30"), ("13:30", "16:00"), ("09:30", "16:00")]
HOURS = [("09:30", "10:30"), ("10:30", "11:30"), ("11:30", "12:30"), ("12:30", "13:30"),
         ("13:30", "14:30"), ("14:30", "15:30"), ("15:30", "16:00")]
LABEL = {"ib_trend": "IB Trend Breakout", "orb2nd": "ORB Second Break", "h2l2_trend": "H2/L2 Trend Pullback",
         "confluence_pb": "Trend-Confluence Pullback"}


def wname(w):
    return "Full RTH" if w == ("09:30", "16:00") else f"{w[0]}–{w[1]}"


def window_trades(frames: dict, cfg: dict, sym_lists: dict, slip_ticks: int = 1, hours: bool = True) -> pd.DataFrame:
    """frames: sym -> (indicator DataFrame, spec). sym_lists: strategy -> symbols to run it on.
    Returns all trades with columns strategy, sym, window, mode (+ simulate() columns)."""
    out = []
    wins = SESSIONS + (HOURS if hours else [])
    for name, sc in cfg["strategies"].items():
        for w in wins:
            for mode in ("hold", "flat"):
                if w == ("09:30", "16:00") and mode == "flat":
                    continue
                if mode == "hold" and w[0] >= "15:30":
                    continue                            # hold-mode entries stop at 15:25
                s2 = copy.deepcopy(sc)
                s2["window"], s2["mode"] = list(w), mode
                for sym in sym_lists.get(name, []):
                    if sym not in frames:
                        continue
                    df, spec = frames[sym]
                    st, p = C.build_strategy(name, s2)
                    t = C.simulate(sym, df, st, p, spec, slip_ticks=slip_ticks)
                    if len(t):
                        t["window"], t["mode"] = wname(w), mode
                        out.append(t)
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def _dd(series):
    d = series.sort_index().cumsum()
    return float((d.cummax().clip(lower=0) - d).max()) if len(d) else 0.0


def summarize(T: pd.DataFrame, years: float, value: str, split=None) -> pd.DataFrame:
    """Per strategy x window x mode: n, win, 2R hit, PF, avg R, yearly value, max DD (on `value`, daily-summed)."""
    rows = []
    sp = pd.Timestamp(split) if split is not None else None
    for (st, w, m), g in T.groupby(["strategy", "window", "mode"]):
        v = g[value]
        wins = v > 0
        gl = -v[~wins].sum()
        daily = g.groupby("day")[value].sum()
        r = dict(strategy=st, window=w, mode=m, n=len(g), win=wins.mean(), tgt=(g.why == "target").mean(),
                 pf=v[wins].sum() / gl if gl > 0 else np.inf, avgR=g.R.mean(), yearly=v.sum() / years, dd=_dd(daily))
        if sp is not None:
            d = pd.to_datetime(g.day)
            r["y1R"], r["y2R"] = g.R[d < sp].mean(), g.R[d >= sp].mean()
        rows.append(r)
    return pd.DataFrame(rows)


def html_tables(S: pd.DataFrame, cfg: dict, fmt_yearly, fmt_dd, note: str, show_years=False) -> str:
    """One table per strategy: rows = windows (sessions, then hours), columns = hold | flat metrics.
    The window/mode currently configured in the bot is marked ★."""
    order = [wname(w) for w in SESSIONS] + [wname(w) for w in HOURS]
    out = []
    for st in LABEL:
        g = S[S.strategy == st]
        if g.empty:
            continue
        sc = cfg["strategies"].get(st, {})
        cur_w, cur_m = wname(tuple(sc.get("window", ["09:30", "16:00"]))), sc.get("mode", "hold")
        head = ("<tr><th rowspan=2>Entry window</th><th colspan=%d>HOLD (to 2R / stop / 16:00)</th>"
                "<th colspan=%d>FLAT (out at window end)</th></tr>") % (6 + 2 * show_years, 6 + 2 * show_years)
        sub = "".join(f"<th>{h}</th>" for h in (["Trades", "PF", "Avg R", "Yearly", "Max DD", "2R hit"] + (["Y1 R", "Y2 R"] if show_years else [])) * 2)
        rows = []
        for w in order:
            if w == wname(HOURS[0]):
                rows.append(f"<tr><td colspan={13 + 4 * show_years} class='sub' style='padding-top:10px'><b>by hour</b></td></tr>")
            cells = []
            for m in ("hold", "flat"):
                r = g[(g.window == w) & (g["mode"] == m)]
                k = 6 + 2 * show_years
                if r.empty or r.n.iloc[0] < 5:
                    cells.append(f"<td colspan={k} class='muted'>{'–' if r.empty else f'{int(r.n.iloc[0])} trades'}</td>")
                    continue
                r = r.iloc[0]
                star = " ★" if (w == cur_w and m == cur_m) else ""
                c = "good" if r.yearly > 0 and r.pf >= 1.1 else ("bad" if r.yearly < 0 else "")
                cell = (f"<td>{int(r.n)}{star}</td><td class='{c}'><b>{r.pf:.2f}</b></td><td>{r.avgR:+.2f}</td>"
                        f"<td class='{c}'>{fmt_yearly(r.yearly)}</td><td>{fmt_dd(r.dd)}</td><td>{r.tgt:.0%}</td>")
                if show_years:
                    cell += f"<td>{r.y1R:+.2f}</td><td>{r.y2R:+.2f}</td>"
                cells.append(cell)
            style = " style='background:color-mix(in srgb,var(--s1) 8%,transparent)'" if w == cur_w else ""
            rows.append(f"<tr{style}><td>{w}</td>{''.join(cells)}</tr>")
        out.append(f"<h3>{LABEL[st]} <span class='sub'>· symbols {', '.join(sc.get('symbols', []))} · bot uses {cur_w} {cur_m} ★</span></h3>"
                   f"<table><thead>{head}<tr>{sub}</tr></thead><tbody>{''.join(rows)}</tbody></table>")
    return "".join(out) + f"<p class='sub'>{note}</p>"
