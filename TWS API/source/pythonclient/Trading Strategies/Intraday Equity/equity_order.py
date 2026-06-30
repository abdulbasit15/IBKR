"""Equity order helpers for the intraday long-only bots.

Key adversarial-review fixes baked in:
* LIMIT-ONLY ENTRIES: the entry walk NEVER falls back to a MarketOrder (the reused
  custom_order.py did). On no-fill it cancels and returns None. Market orders are used
  ONLY for emergency flatten / EOD.
* ATOMIC PROTECTION: protective TP + stop children are attached to the entry parent
  (parentId + transmit chaining) and OCA-grouped, so the stop is server-side the instant
  the parent fills - no "naked long" window.
* DUAL STOP TYPE: native stop-MARKET child (ORB / NR7) OR stop-LIMIT child (PDH, to cap
  slippage) via the same builder.
* LONG-ONLY ASSERTS: opening leg must be BUY; protective/exit legs must be SELL.
"""
from __future__ import annotations
import time as _t

from ib_async import LimitOrder, MarketOrder, StopOrder, StopLimitOrder


def round_to_tick(price: float, tick: float = 0.01) -> float:
    if not tick or tick <= 0:
        tick = 0.01
    return round(round(price / tick) * tick, 6)


def build_bracket(ib, qty: int, entry_limit: float, take_profit: float, stop_trigger: float,
                  *, stop_limit_price: float | None = None, order_ref: str = "",
                  account: str = "", tick: float = 0.01, tif: str = "DAY"):
    """Build a long bracket: BUY-limit parent + SELL take-profit + SELL stop child.
    Children are attached to the parent (parentId) and OCA-grouped; the stop is a
    stop-market unless stop_limit_price is given (then stop-limit).
    Returns (parent, take_profit_order, stop_order) - not yet placed."""
    entry_limit = round_to_tick(entry_limit, tick)
    take_profit = round_to_tick(take_profit, tick)
    stop_trigger = round_to_tick(stop_trigger, tick)

    bracket = ib.bracketOrder("BUY", qty, entry_limit, take_profit, stop_trigger)
    parent, tp, stop = bracket.parent, bracket.takeProfit, bracket.stopLoss

    if stop_limit_price is not None:
        sl = StopLimitOrder("SELL", qty, round_to_tick(stop_limit_price, tick), stop_trigger)
        sl.orderId = stop.orderId
        sl.parentId = stop.parentId
        sl.transmit = stop.transmit
        stop = sl

    oca = order_ref or f"oca{parent.orderId}"
    for child in (tp, stop):
        child.ocaGroup = oca
        child.ocaType = 1  # cancel remaining + proportionally reduce
    for o in (parent, tp, stop):
        if order_ref:
            o.orderRef = order_ref
        if account:
            o.account = account
        o.tif = tif

    assert parent.action == "BUY", "LONG-ONLY: entry parent must be BUY"
    assert tp.action == "SELL" and stop.action == "SELL", "LONG-ONLY: exits must be SELL"
    return parent, tp, stop


def place_protected_entry(ib, contract, qty: int, entry_limit: float, take_profit: float,
                          stop_trigger: float, *, order_ref: str, account: str, log,
                          stop_limit_price: float | None = None, tick: float = 0.01,
                          entry_timeout_sec: int = 120, max_chase_pct: float = 0.0):
    """Submit a marketable-limit BUY with TP+stop attached. Limit-only walk: if unfilled
    within entry_timeout_sec, cancel and (optionally) re-submit up to max_chase_pct higher.
    NEVER uses a market order. Returns (parent_trade, tp_trade, stop_trade) or (None,)*3.

    Partial fills: if the parent partially fills at timeout we KEEP the filled qty, cancel
    the remainder, and resize the protective children to the filled qty."""
    assert qty > 0, "qty must be positive"
    base = round_to_tick(entry_limit, tick)
    cap = round_to_tick(base * (1 + max_chase_pct), tick) if max_chase_pct > 0 else base
    # Walk base->cap in a few sizable steps (not one tick at a time), waiting only a few
    # seconds per level, so a marketable price is reached quickly on a breakout. With
    # max_chase_pct=0 this degrades to a single passive limit at base for the full timeout.
    n_levels = 5
    step = max(tick, round_to_tick((cap - base) / n_levels, tick)) if cap > base else tick
    per_level = max(2, int(entry_timeout_sec) // n_levels) if cap > base else int(entry_timeout_sec)
    px = base

    while True:
        parent, tp, stop = build_bracket(
            ib, qty, px, take_profit, stop_trigger,
            stop_limit_price=stop_limit_price, order_ref=order_ref, account=account, tick=tick,
        )
        pt = ib.placeOrder(contract, parent)
        tt = ib.placeOrder(contract, tp)
        st = ib.placeOrder(contract, stop)
        log(f"[{order_ref}] entry BUY {qty} {contract.symbol} lmt {px} tp {tp.lmtPrice} stop {stop_trigger}")

        waited = 0
        while waited < per_level:
            ib.sleep(1)
            waited += 1
            if pt.orderStatus.status == "Filled":
                log(f"[{order_ref}] FILLED {contract.symbol} @ {pt.orderStatus.avgFillPrice}")
                return pt, tt, st
            if pt.orderStatus.status in ("Cancelled", "ApiCancelled", "Inactive"):
                break

        filled = float(pt.orderStatus.filled or 0)
        if filled > 0:
            # Keep the partial; cancel remainder; resize children to the filled qty.
            ib.cancelOrder(parent)
            ib.sleep(1)
            if resize_children(ib, contract, tt, st, int(filled), log):
                log(f"[{order_ref}] PARTIAL fill {int(filled)}/{qty} {contract.symbol}; children resized")
                return pt, tt, st
            # Protection could not be guaranteed at filled qty -> cancel children + flatten
            # so an oversized SELL can't flip us short (long-only invariant).
            for ch in (tt, st):
                try:
                    ib.cancelOrder(ch.order)
                except Exception:
                    pass
            ib.sleep(1)
            flatten_position(ib, contract, int(filled), order_ref=order_ref, account=account, log=log)
            log(f"[{order_ref}] PARTIAL protection failed -> flattened {int(filled)} {contract.symbol}")
            return None, None, None

        ib.cancelOrder(parent)
        ib.sleep(1)
        if px >= cap:
            log(f"[{order_ref}] no fill within walk for {contract.symbol} -> SKIP (no market fallback)")
            return None, None, None
        px = round_to_tick(min(px + step, cap), tick)


def resize_children(ib, contract, tp_trade, stop_trade, new_qty: int, log) -> bool:
    """Resize the protective TP/stop legs to new_qty (after a partial entry fill).
    Forces transmit=True so the modification is actually sent (a parked transmit=False
    modify would leave protection at the wrong qty). Returns False if a leg could not be
    resized so the caller can cancel children + flatten the partial (stay long-only)."""
    for trade in (tp_trade, stop_trade):
        try:
            o = trade.order
            o.totalQuantity = new_qty
            o.transmit = True
            t2 = ib.placeOrder(contract, o)
            ib.sleep(1)
            # Verify against the SERVER trade state, not the local object we just mutated:
            # a rejected/terminal modify means protection was NOT actually resized.
            status = t2.orderStatus.status if (t2 and t2.orderStatus) else ""
            if status in ("Rejected", "Cancelled", "ApiCancelled", "Inactive"):
                log(f"resize_children: resize to {new_qty} rejected (status {status})")
                return False
        except Exception as e:  # pragma: no cover
            log(f"resize_children error: {e}")
            return False
    return True


def modify_stop(ib, contract, stop_trade, new_stop_trigger: float, qty: int, *,
                stop_limit_price: float | None = None, tick: float = 0.01, log=print):
    """Move a stop (breakeven / trail). Replaces the existing stop child in-place,
    preserving its OCA group and qty sync. Long-only: action stays SELL."""
    o = stop_trade.order
    assert o.action == "SELL", "LONG-ONLY: stop must be SELL"
    o.totalQuantity = qty
    o.auxPrice = round_to_tick(new_stop_trigger, tick)        # stop trigger
    if stop_limit_price is not None and hasattr(o, "lmtPrice"):
        o.lmtPrice = round_to_tick(stop_limit_price, tick)
    o.transmit = True  # force the breakeven/trail modify to actually transmit
    try:
        return ib.placeOrder(contract, o)
    except Exception as e:  # pragma: no cover
        log(f"modify_stop error: {e}")
        return stop_trade


def flatten_position(ib, contract, qty: int, *, order_ref: str, account: str, log,
                     wait_sec: int = 20):
    """Emergency / EOD market exit of a long position. Market order allowed ONLY here.
    Returns the Trade and waits for a terminal status so callers can use the real fill
    price (and detect a non-fill instead of recording a stale price)."""
    if qty <= 0:
        return None
    o = MarketOrder("SELL", qty)
    o.orderRef = order_ref + "_FLAT"
    if account:
        o.account = account
    assert o.action == "SELL", "LONG-ONLY: flatten must be SELL"
    tr = ib.placeOrder(contract, o)
    log(f"[{order_ref}] FLATTEN market SELL {qty} {contract.symbol}")
    waited = 0
    while waited < wait_sec:
        ib.sleep(1)
        waited += 1
        if tr.orderStatus.status in ("Filled", "Cancelled", "ApiCancelled", "Inactive"):
            break
    return tr
