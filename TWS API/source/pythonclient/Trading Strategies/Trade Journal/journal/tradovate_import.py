"""Convert Tradovate order-export CSVs into round-trip trades.

Handles two known Tradovate export layouts:
  A) "tradovate-orders-all-*.csv": columns Symbol/Side/Type/Update Time, with
     explicit "Take Profit"/"Stop Loss" order types.
  B) "Orders.csv": columns B/S, Contract/Product, Fill Time, values padded with
     leading spaces, and Market/Limit/Stop order types (brackets inferred from
     side + price relative to entry).

Both are normalized to one canonical schema, then trades are reconstructed by
walking filled orders chronologically per instrument and tracking net position;
a completed round-trip is emitted every time the position returns to flat. A
single fill that crosses through zero (a flip) is split into a close + a new
open. Stop/target prices are recovered from the protective orders in the trade's
time window.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from . import config
from .excel_io import Trade, read_trades

# Canonical columns produced by normalize():
#   root, sym, side(buy/sell), otype, status(filled/canceled/...),
#   fqty(float), avgpx(float|None), t(datetime|None), limit_px, stop_px
_TIME_FORMATS = ("%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M",
                 "%Y-%m-%d %H:%M:%S", "%m/%d/%y %H:%M")


def _parse_time(v):
    if v is None or (isinstance(v, float) and pd.isna(v)) or str(v).strip() == "":
        return None
    if isinstance(v, datetime):
        return v
    s = str(v).strip()
    for fmt in _TIME_FORMATS:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    try:
        return pd.to_datetime(s).to_pydatetime()
    except Exception:
        return None


def _fnum(v):
    try:
        if v is None or (isinstance(v, float) and pd.isna(v)) or str(v).strip() == "":
            return None
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def normalize(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [c.strip() for c in df.columns]
    cols = set(df.columns)
    rows = []

    if "B/S" in cols:  # Format B (Orders.csv)
        for _, o in df.iterrows():
            sym = str(o.get("Contract", "")).strip()
            prod = str(o.get("Product", "")).strip()
            root = prod if prod in config.MULTIPLIERS else config.root_from_symbol(sym)
            t = _parse_time(o.get("Fill Time")) or _parse_time(o.get("Timestamp")) \
                or _parse_time(o.get("Date"))
            rows.append({
                "root": root, "sym": sym,
                "side": str(o.get("B/S", "")).strip().lower(),
                "otype": str(o.get("Type", "")).strip().lower(),
                "status": str(o.get("Status", "")).strip().lower(),
                "fqty": _fnum(o.get("Filled Qty")) or 0.0,
                "avgpx": _fnum(o.get("Avg Fill Price")),
                "t": t,
                "limit_px": _fnum(o.get("Limit Price")),
                "stop_px": _fnum(o.get("Stop Price")),
            })
    else:              # Format A (tradovate-orders-all-*.csv)
        for _, o in df.iterrows():
            sym = str(o.get("Symbol", "")).strip()
            rows.append({
                "root": config.root_from_symbol(sym), "sym": sym,
                "side": str(o.get("Side", "")).strip().lower(),
                "otype": str(o.get("Type", "")).strip().lower(),
                "status": str(o.get("Status", "")).strip().lower(),
                "fqty": _fnum(o.get("Filled Qty")) or 0.0,
                "avgpx": _fnum(o.get("Avg Fill Price")),
                "t": _parse_time(o.get("Update Time")),
                "limit_px": _fnum(o.get("Limit Price")),
                "stop_px": _fnum(o.get("Stop Price")),
            })
    return pd.DataFrame(rows)


def load_orders(csv_path: Path) -> pd.DataFrame:
    return normalize(pd.read_csv(Path(csv_path)))


def _brackets(orders: pd.DataFrame, direction: str, entry_px: float,
              start: datetime, end: datetime):
    """Recover planned (take-profit, stop-loss) from protective orders in window.

    The exit side is opposite the entry. Among exit-side orders in the window:
      - stop-loss  = a Stop order priced beyond entry in the losing direction
      - take-profit = a Limit order priced beyond entry in the winning direction
    Picks the furthest-favorable TP and the protective SL if several exist.
    """
    exit_side = "sell" if direction == "Long" else "buy"
    tp = sl = None
    lo = start - timedelta(minutes=3)
    hi = (end or start) + timedelta(minutes=3)
    for _, o in orders.iterrows():
        t = o["t"]
        if t is None or t < lo or t > hi or o["side"] != exit_side:
            continue
        otype = o["otype"]
        if ("stop" in otype) and o["stop_px"] is not None:
            px = o["stop_px"]
            if (direction == "Long" and px < entry_px) or \
               (direction == "Short" and px > entry_px):
                sl = px if sl is None else (min(sl, px) if direction == "Long"
                                            else max(sl, px))
        elif (("limit" in otype) or ("profit" in otype)) and o["limit_px"] is not None:
            px = o["limit_px"]
            if (direction == "Long" and px > entry_px) or \
               (direction == "Short" and px < entry_px):
                tp = px if tp is None else (max(tp, px) if direction == "Long"
                                            else min(tp, px))
    return tp, sl


def build_trades(df: pd.DataFrame) -> list[Trade]:
    trades: list[Trade] = []
    for root, grp in df.groupby("root"):
        if not root:
            continue
        grp = grp.sort_values("t", kind="stable")
        filled = grp[(grp["status"] == "filled") & (grp["fqty"] > 0)]

        pos = 0.0
        direction = None
        t_open = t_close = None
        en = eq = xn = xq = 0.0

        def emit():
            nonlocal pos, direction, t_open, t_close, en, eq, xn, xq
            entry_px = en / eq
            exit_px = xn / xq if xq else None
            tp, sl = _brackets(grp, direction, entry_px, t_open, t_close)
            trades.append(Trade(
                date=t_open, time=t_open.time() if t_open else None,
                asset=root, direction=direction,
                entry=round(entry_px, 6),
                exit=round(exit_px, 6) if exit_px is not None else None,
                size=eq, stop=sl, target=tp,
                setup="", notes="Imported from Tradovate",
            ))
            pos = 0.0
            direction = None
            en = eq = xn = xq = 0.0

        for _, o in filled.iterrows():
            side, qty, px = o["side"], o["fqty"], o["avgpx"]
            if px is None or qty <= 0:
                continue
            remaining = qty if side == "buy" else -qty

            while remaining != 0:
                if pos == 0:
                    direction = "Long" if remaining > 0 else "Short"
                    t_open = o["t"]
                    en = eq = xn = xq = 0.0

                same_dir = (pos > 0 and remaining > 0) or (pos < 0 and remaining < 0)
                if pos == 0 or same_dir:                # add to position
                    en += px * abs(remaining)
                    eq += abs(remaining)
                    pos += remaining
                    remaining = 0
                else:                                   # reduce / close
                    step = min(abs(remaining), abs(pos))
                    sgn = 1 if remaining > 0 else -1
                    xn += px * step
                    xq += step
                    t_close = o["t"]
                    pos += sgn * step
                    remaining -= sgn * step
                    if abs(pos) < 1e-9:
                        emit()                          # flat -> round-trip done
    trades.sort(key=lambda t: (t.date or datetime.min))
    return trades


def import_csv(csv_path: Path, workbook: Path | None = None,
               dry_run: bool = False) -> dict:
    df = load_orders(Path(csv_path))
    built = build_trades(df)

    existing_keys = {t.dedupe_key() for t in read_trades(workbook)}
    fresh, seen = [], set(existing_keys)
    for t in built:                      # dedupe vs journal AND within this file
        k = t.dedupe_key()
        if k in seen:
            continue
        seen.add(k)
        fresh.append(t)

    written = 0
    if not dry_run and fresh:
        from .excel_io import append_trades
        written = append_trades(fresh, workbook)

    return {
        "orders_in_csv": len(df),
        "round_trips_built": len(built),
        "already_in_journal": len(built) - len(fresh),
        "new_trades": len(fresh),
        "written": written,
        "trades": fresh,
    }
