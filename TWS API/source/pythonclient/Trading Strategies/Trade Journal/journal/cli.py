"""Command-line entrypoint: import trades, analyze, and build the report."""
from __future__ import annotations

import argparse
import glob
import os
import sys
import webbrowser
from pathlib import Path

from . import ai, analytics, autotag, config, excel_io, market, news, report, webapp
from .tradovate_import import import_csv


_LOCK_MSG = ("  ⚠ Could not write to the workbook — it looks like it's open in "
             "Excel.\n    Close 'ZTH Trade Tracker - AB.xlsx' and re-run. "
             "(The web app still reflects everything.)")


def _latest_csv() -> Path | None:
    """Newest Tradovate export in the folder (by modified time).

    Matches tradovate-orders-*.csv and orders*.csv / Orders*.csv, so you can just
    drop a new export in and run — no need to pass --csv.
    """
    patterns = ["tradovate-orders-*.csv", "orders*.csv", "Orders*.csv"]
    hits = []
    for pat in patterns:
        hits += glob.glob(str(config.ROOT / pat))
    hits = list(dict.fromkeys(hits))  # de-dup (case-insensitive FS)
    if not hits:
        return None
    return Path(max(hits, key=lambda p: Path(p).stat().st_mtime))


def _recent_trades(trades, n=25) -> list[dict]:
    out = []
    for t in sorted(trades, key=lambda x: x.timestamp or 0, reverse=True)[:n]:
        out.append({
            "when": t.timestamp.strftime("%m/%d %H:%M") if t.timestamp else "",
            "asset": t.asset, "direction": t.direction,
            "entry": t.entry, "exit": t.exit, "size": int(t.size) if t.size else "",
            "rr_realized": round(t.rr_realized, 2) if t.rr_realized is not None else "",
            "pnl": t.pnl, "setup": t.setup,
        })
    return out


def cmd_import(args) -> int:
    csv_path = Path(args.csv) if args.csv else _latest_csv()
    if not csv_path or not csv_path.exists():
        print("No Tradovate CSV found. Use --csv <path>.")
        return 1
    print(f"Importing: {csv_path.name}")
    try:
        res = import_csv(csv_path, config.WORKBOOK, dry_run=args.dry_run)
    except PermissionError:
        print(_LOCK_MSG)
        return 1
    print(f"  orders in CSV      : {res['orders_in_csv']}")
    print(f"  round-trips built  : {res['round_trips_built']}")
    print(f"  already in journal : {res['already_in_journal']}")
    print(f"  new trades         : {res['new_trades']}")
    if args.dry_run:
        print("  (dry run — nothing written)")
        for t in res["trades"]:
            print(f"    + {str(t.date)[:10]} {t.asset} {t.direction} "
                  f"{t.entry}->{t.exit} x{int(t.size)}")
    else:
        print(f"  rows written       : {res['written']}")
    return 0


def cmd_report(args) -> int:
    config.load_dotenv()
    trades = excel_io.read_trades(config.WORKBOOK)
    if not trades:
        print("No trades found in the workbook.")
        return 1
    print(f"Analyzing {len(trades)} trades...")
    metrics = analytics.compute_metrics(trades)

    market_ctx = {} if args.no_market else market.summarize_days(trades)
    if not args.no_market:
        got = sum(1 for v in market_ctx.values() if v and v.get("available"))
        print(f"  market context     : {got}/{len(market_ctx)} instrument-days")
    news_ctx = {} if args.no_news else news.summarize_days(trades)
    if not args.no_news:
        days = sum(1 for v in news_ctx.values() if v is not None)
        print(f"  news calendar      : {days} day(s) in feed window")

    recent = _recent_trades(trades)
    if args.no_ai:
        ai_text = "[AI disabled with --no-ai]"
    else:
        print(f"  calling Claude ({ai.backend_label()})...")
        ai_text = ai.coach(metrics, market_ctx, news_ctx, recent)
        if ai_text.startswith("[AI"):
            print(f"  {ai_text.splitlines()[0]}")

    path = report.write_report(metrics, ai_text, recent, news_ctx or None)
    print(f"\nDashboard: {path}")

    if not args.no_writeback:
        try:
            excel_io.write_analysis_sheets(metrics, ai_text, config.WORKBOOK)
            print(f"Wrote 'Analysis' + 'AI Suggestions' sheets to {config.WORKBOOK.name}")
        except PermissionError:
            print(_LOCK_MSG)

    if args.open:
        webbrowser.open(path.as_uri())
    return 0


def cmd_tag(args) -> int:
    trades = excel_io.read_trades(config.WORKBOOK)
    if not trades:
        print("No trades found.")
        return 1
    trades = [t for t in trades if t.timestamp is not None]
    trades.sort(key=lambda t: t.timestamp)
    print(f"Auto-tagging {len(trades)} trades from intraday price action...")
    labels = autotag.autotag(trades)
    from collections import Counter
    dist = Counter(v for v in labels.values() if v)
    for name, n in dist.most_common():
        print(f"  {name:14} {n}")
    if args.dry_run:
        print("  (dry run — nothing written)")
        return 0
    try:
        written = excel_io.write_setups(labels, config.WORKBOOK, only_blank=True)
        print(f"Wrote {written} setup tags into blank cells (backed up first).")
    except PermissionError:
        print(_LOCK_MSG)
    return 0


def cmd_app(args) -> int:
    config.load_dotenv()
    trades = excel_io.read_trades(config.WORKBOOK)
    if not trades:
        print("No trades found in the workbook.")
        return 1
    ai_text = ""
    if not args.no_ai:
        print(f"  calling Claude ({ai.backend_label()}) for the Notebook...")
        metrics = analytics.compute_metrics(trades)
        market_ctx = {} if args.no_market else market.summarize_days(trades)
        news_ctx = {} if args.no_news else news.summarize_days(trades)
        ai_text = ai.coach(metrics, market_ctx, news_ctx, _recent_trades(trades))
        if ai_text.startswith("[AI"):
            print(f"  {ai_text.splitlines()[0]}")
            ai_text = ""
    out = webapp.build_app(config.WORKBOOK, ai_text)
    print(f"Web app: {out}")
    if args.open:
        webbrowser.open(out.as_uri())
    return 0


def cmd_all(args) -> int:
    rc = cmd_import(args)
    print()
    if rc != 0:
        return rc
    cmd_tag(args)
    print()
    rc = cmd_report(args)
    print()
    return cmd_app(args) if rc == 0 else rc


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="journal", description="Local AI futures trading journal.")
    sub = p.add_subparsers(dest="cmd")

    def common(sp):
        sp.add_argument("--csv", help="path to a Tradovate orders CSV")
        sp.add_argument("--dry-run", action="store_true",
                        help="preview import without writing")
        sp.add_argument("--no-ai", action="store_true", help="skip Claude call")
        sp.add_argument("--no-market", action="store_true", help="skip market data")
        sp.add_argument("--no-news", action="store_true", help="skip news feed")
        sp.add_argument("--no-writeback", action="store_true",
                        help="do not write analysis sheets into the workbook")
        sp.add_argument("--open", action="store_true",
                        help="open the HTML report in a browser")

    common(sub.add_parser("import", help="import Tradovate CSV into Excel"))
    common(sub.add_parser("tag", help="auto-tag setups from price action"))
    common(sub.add_parser("report", help="analyze + AI + HTML + write-back"))
    common(sub.add_parser("app", help="build the TradeZella-style web app"))
    common(sub.add_parser("all", help="import + tag + report + app (default)"))
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    cmd = args.cmd or "all"
    return {"import": cmd_import, "tag": cmd_tag, "report": cmd_report,
            "app": cmd_app, "all": cmd_all}[cmd](args)


if __name__ == "__main__":
    sys.exit(main())
