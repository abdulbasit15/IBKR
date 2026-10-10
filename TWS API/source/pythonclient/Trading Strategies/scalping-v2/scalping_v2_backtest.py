"""
Backtest the Scalping v2 bot EXACTLY as configured (same scalping_v2_core engine the live bot replays).

Data: 5-min RTH CSVs in ../Historical Data/data :  {SYM}_cont_5mins_rth.csv (+ {SYM}_5m_recent.csv appended,
roll gap back-adjusted). Bars before --start are dropped (older history in those files is forward-fill padded).

Portfolio rules applied like the live bot (turn off with --no-portfolio):
  * one_position_per_symbol: a trade is skipped if another strategy is already in that symbol
    (resolved by entry time, then strategy_priority)
  * symbols.<SYM>.max_risk_usd: skip trades whose risk x contracts exceeds it
  * max_trades_per_day / daily_loss_limit_usd (realized, all symbols)
Sizing: symbols.<SYM>.contracts (sizing.mode="fixed") or risk-based (sizing.mode="risk").

Outputs (in --out, default backtest_out/):
  scalping_v2_bt_<strategy>.csv    one row per trade, Backtest-Journal format (same columns as the live bot)
  scalping_v2_bt_summary.csv       per strategy x symbol x period
  ../backtest_results.html  with --html

  python scalping_v2_backtest.py                       # backtest scalping_v2.json
  python scalping_v2_backtest.py --html                # + rebuild backtest_results.html
  python scalping_v2_backtest.py --config scalping_v2_live.json --slip 2
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import scalping_v2_core as C  # noqa: E402

TRADE_COLS = ["symbol", "strat", "entry_id", "side", "qty", "entry_time_et", "entry_price",
              "exit_time_et", "exit_price", "reason", "R_points", "R_result", "pnl"]
DEFAULT_DATA = os.path.normpath(os.path.join(HERE, "..", "Historical Data", "data"))


def load_csv_bars(sym: str, data_dir: str, start: str) -> pd.DataFrame:
    path = os.path.join(data_dir, f"{sym}_cont_5mins_rth.csv")
    if not os.path.exists(path):                       # e.g. CL: full-session bars, trimmed to 09:30-16:00 below
        path = os.path.join(data_dir, f"{sym}_cont_5mins_eth.csv")
    a = pd.read_csv(path)
    a["date"] = pd.to_datetime(a["date"], utc=True)
    rp = os.path.join(data_dir, f"{sym}_5m_recent.csv")
    if os.path.exists(rp):
        b = pd.read_csv(rp)
        b["date"] = pd.to_datetime(b["date"], utc=True)
        m = a.merge(b, on="date", suffixes=("_a", "_b"))
        off = float((m.close_b - m.close_a).median()) if len(m) else 0.0     # continuous-contract roll gap
        if off:
            for k in ("open", "high", "low", "close"):
                a[k] = a[k] + off
        a = pd.concat([a[a.date < b.date.min()], b])
    df = C.prepare_bars(a)
    return df[df.day >= pd.Timestamp(start).date()].reset_index(drop=True)


def qty_for(cfg: dict, sym: str, risk_usd_1lot: float) -> int:
    sz = cfg.get("sizing", {})
    if sz.get("mode") == "risk":
        q = int(sz.get("risk_usd", 200) // max(risk_usd_1lot, 1e-9))
        return max(0, min(q, int(sz.get("max_contracts", 1))))
    return int(cfg["symbols"][sym].get("contracts", 1))


def run(cfg: dict, data_dir: str, start: str, slip: int, portfolio: bool, only=None):
    comm_cfg = cfg.get("commission_per_side", {})
    prio = {s: k for k, s in enumerate(cfg.get("strategy_priority", list(cfg["strategies"])))}
    all_tr, days_by_sym = [], {}
    for sym, scfg in cfg["symbols"].items():
        if not scfg.get("enabled", True):
            continue
        spec = dict(C.SPECS[sym])
        spec["comm"] = float(comm_cfg.get(sym, spec["comm"]))
        df = C.add_indicators(load_csv_bars(scfg.get("data_symbol", spec.get("data", sym)), data_dir, start), spec["tick"])
        days_by_sym[sym] = sorted(df.day.unique())
        for name, st_cfg in cfg["strategies"].items():
            if not st_cfg.get("enabled", True) or sym not in st_cfg.get("symbols", []):
                continue
            if only and name not in only:
                continue
            st, p = C.build_strategy(name, st_cfg)
            t = C.simulate(sym, df, st, p, spec, slip_ticks=slip)
            if len(t):
                t["pv"], t["comm"] = spec["pv"], spec["comm"]
                all_tr.append(t)
    if not all_tr:
        return pd.DataFrame(), days_by_sym
    T = pd.concat(all_tr, ignore_index=True)
    T["risk_usd_1lot"] = T.risk * T.pv
    T["prio"] = T.strategy.map(prio).fillna(99)
    T = T.sort_values(["day", "et", "prio"]).reset_index(drop=True)
    T["qty"] = [qty_for(cfg, s, r) for s, r in zip(T.sym, T.risk_usd_1lot)]
    T["taken"], T["skip"] = True, ""
    if portfolio:
        busy_until, day_n, day_pnl = {}, {}, {}
        lim, maxn = float(cfg.get("daily_loss_limit_usd", 0) or 0), int(cfg.get("max_trades_per_day", 999))
        for ix, r in T.iterrows():
            key = (r.day, r.sym)
            why = ""
            if r.qty < 1:
                why = "size<1"
            elif r.risk_usd_1lot * r.qty > float(cfg["symbols"][r.sym].get("max_risk_usd", 1e9)):
                why = "max_risk"
            elif cfg.get("one_position_per_symbol", True) and busy_until.get(key, -1) > r.et:
                why = "symbol_busy"
            elif day_n.get(r.day, 0) >= maxn:
                why = "max_trades"
            elif lim and day_pnl.get(r.day, 0.0) <= -lim:
                why = "daily_loss"
            if why:
                T.at[ix, "taken"], T.at[ix, "skip"] = False, why
                continue
            busy_until[key] = r.xt + 5
            day_n[r.day] = day_n.get(r.day, 0) + 1
            day_pnl[r.day] = day_pnl.get(r.day, 0.0) + (r.pts * r.pv - 2 * r.comm) * r.qty
    T["net"] = (T.pts * T.pv - 2 * T.comm) * T.qty
    return T, days_by_sym


def to_journal(t: pd.DataFrame) -> pd.DataFrame:
    def ts(day, m):
        return f"{day} {m // 60:02d}:{m % 60:02d}:00"
    rows = []
    for _, r in t.iterrows():
        rows.append({"symbol": r.sym, "strat": "sv2_" + r.strategy,
                     "entry_id": f"{r.sym}-{r.strategy}-{str(r.day).replace('-', '')}-{r.et:04d}",
                     "side": "Long" if r.dir == 1 else "Short", "qty": int(r.qty),
                     "entry_time_et": ts(r.day, r.et), "entry_price": round(r.entry, 4),
                     "exit_time_et": ts(r.day, r.xt + 5), "exit_price": round(r.exit, 4), "reason": r.why,
                     "R_points": round(r.risk, 4), "R_result": f"{r.pts / r.risk:+.2f}R",
                     "pnl": round(r.net, 2)})
    return pd.DataFrame(rows, columns=TRADE_COLS)


def summarize(T: pd.DataFrame, days_by_sym: dict, split: str) -> pd.DataFrame:
    sp = pd.Timestamp(split).date()
    alldays = sorted({d for v in days_by_sym.values() for d in v})
    rows = []
    taken = T[T.taken]
    groups = [("ALL", "ALL", taken)] + [(s, "ALL", g) for s, g in taken.groupby("strategy")] \
        + [(s, y, g) for (s, y), g in taken.groupby(["strategy", "sym"])] + [("ALL", y, g) for y, g in taken.groupby("sym")]
    for strat, sym, g in groups:
        for part, dd in (("ALL", alldays), ("IS", [d for d in alldays if d < sp]), ("OOS", [d for d in alldays if d >= sp])):
            x = g[g.day.isin(dd)]
            m = C.metrics(x, dd)
            rows.append(dict(strategy=strat, sym=sym, part=part, **m))
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser(description="Backtest the Scalping v2 bot config")
    ap.add_argument("--config", default=os.path.join(HERE, "scalping_v2.json"))
    ap.add_argument("--data", default=DEFAULT_DATA)
    ap.add_argument("--start", default="2025-09-02", help="first session (older CSV history is padded)")
    ap.add_argument("--split", default="2026-05-01", help="in-sample / out-of-sample boundary")
    ap.add_argument("--slip", type=int, default=1, help="slippage ticks per market/stop fill")
    ap.add_argument("--no-portfolio", action="store_true", help="each strategy independently (no symbol/risk/day caps)")
    ap.add_argument("--strategies", nargs="*", help="subset of strategies")
    ap.add_argument("--out", default=os.path.join(HERE, "backtest_out"))
    ap.add_argument("--html", action="store_true", help="rebuild backtest_results.html")
    a = ap.parse_args()
    cfg = json.load(open(a.config, encoding="utf-8"))
    T, days = run(cfg, a.data, a.start, a.slip, not a.no_portfolio, a.strategies)
    if T.empty:
        print("no trades")
        return
    os.makedirs(a.out, exist_ok=True)
    for s, g in T[T.taken].groupby("strategy"):
        to_journal(g).to_csv(os.path.join(a.out, f"scalping_v2_bt_{s}.csv"), index=False)
    S = summarize(T, days, a.split)
    S.to_csv(os.path.join(a.out, "scalping_v2_bt_summary.csv"), index=False)
    T.drop(columns=["prio"]).to_csv(os.path.join(a.out, "scalping_v2_bt_all_signals.csv"), index=False)
    pd.set_option("display.width", 200)
    print(f"Backtest {a.config}  data {min(min(v) for v in days.values())} .. {max(max(v) for v in days.values())}  "
          f"slip={a.slip} tick  portfolio={'on' if not a.no_portfolio else 'off'}")
    sk = T[~T.taken].skip.value_counts().to_dict()
    print(f"signals {len(T)}  taken {int(T.taken.sum())}  skipped {sk}")
    v = S[S.part == "ALL"].copy()
    for part in ("IS", "OOS"):
        v[f"pf_{part}"] = S[S.part == part].pf.values
    print(v[["strategy", "sym", "n", "win", "tgt", "pf", "net", "dd", "avgR", "sharpe", "pf_IS", "pf_OOS"]]
          .round(3).to_string(index=False))
    if a.html:
        import scalping_v2_report
        scalping_v2_report.build(T, S, days, cfg, a)
        print("wrote backtest_results.html")


if __name__ == "__main__":
    main()
