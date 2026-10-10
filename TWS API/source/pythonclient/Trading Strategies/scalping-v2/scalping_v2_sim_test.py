"""
Broker-simulator test: drives the REAL bot code (ScalpingV2Bot.evaluate / place_trade / _apply_fill / manage_timers /
flatten / cancel_entry / trade CSV) through past sessions bar by bar against a FAKE IB that fills the bot's
actual orders from historical 5-min bars (same fill rules as the backtest). Then compares the bot's trade
CSV with the backtest (portfolio mode) for the same days.

  python scalping_v2_sim_test.py --days 40          # last 40 sessions, all configured symbols/strategies
No IB connection, no network. Writes into a temp folder (does not touch the real state/CSVs).
"""
import argparse
import itertools
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timedelta
from types import SimpleNamespace

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import scalping_v2_core as C          # noqa: E402
import scalping_v2_bot as B           # noqa: E402
from scalping_v2_backtest import load_csv_bars, DEFAULT_DATA, run as bt_run  # noqa: E402

ET = B.ET
SIM = {"t": None}


class FakeTrade:
    def __init__(self, contract, order):
        self.contract, self.order = contract, order
        self.orderStatus = SimpleNamespace(status="Submitted", filled=0)
        self.log = []


class FakeIB:
    """Minimal stand-in for ib_async.IB used by ScalpingV2Bot. Fills come from the current bar."""
    def __init__(self, bot):
        self.bot = bot
        self._id = itertools.count(1000)
        self.client = SimpleNamespace(getReqId=lambda: next(self._id))
        self.book = {}                  # orderId -> FakeTrade
        self.fills = []
        self.pos = {}                   # conId -> qty
        self._eid = itertools.count(1)

    # api surface used by the bot
    def isConnected(self): return True
    def sleep(self, s=0): pass
    def reqAllOpenOrders(self): return []
    def qualifyContracts(self, *a): return list(a)
    def reqExecutions(self): return list(self.fills)
    def positions(self):
        return [SimpleNamespace(contract=SimpleNamespace(conId=k, secType="FUT", localSymbol=str(k)), position=v,
                                account=self.bot.cfg["account"]) for k, v in self.pos.items() if v]
    def openTrades(self):
        return [t for t in self.book.values() if t.orderStatus.status in ("Submitted", "PreSubmitted")]
    def placeOrder(self, contract, order):
        if not order.orderId:                       # ib_async assigns an id to new orders with orderId 0
            order.orderId = self.client.getReqId()
        if order.orderId in self.book:              # modification
            self.book[order.orderId].order = order
            return self.book[order.orderId]
        t = FakeTrade(contract, order)
        if getattr(order, "parentId", 0):
            t.orderStatus.status = "PreSubmitted"   # child: inactive until the parent fills
        self.book[order.orderId] = t
        return t
    def cancelOrder(self, order):
        t = self.book.get(order.orderId)
        if t and t.orderStatus.status in ("Submitted", "PreSubmitted"):
            t.orderStatus.status = "Cancelled"
            for c in self.book.values():            # cancelling a parent cancels its children
                if getattr(c.order, "parentId", 0) == order.orderId and c.orderStatus.status in ("Submitted", "PreSubmitted"):
                    c.orderStatus.status = "Cancelled"

    # broker side
    def _fill(self, t, px):
        o = t.order
        t.orderStatus.status = "Filled"
        sgn = 1 if o.action == "BUY" else -1
        self.pos[t.contract.conId] = self.pos.get(t.contract.conId, 0) + sgn * int(o.totalQuantity)
        ex = SimpleNamespace(execId=f"E{next(self._eid)}", orderRef=o.orderRef, shares=float(o.totalQuantity),
                             price=float(px), time=SIM["t"], side="BOT" if sgn == 1 else "SLD", orderId=o.orderId)
        self.fills.append(SimpleNamespace(execution=ex))
        for c in self.book.values():                # activate children / OCA-cancel siblings
            if getattr(c.order, "parentId", 0) == o.orderId and c.orderStatus.status == "PreSubmitted":
                c.orderStatus.status = "Submitted"
            if (getattr(o, "ocaGroup", "") and c is not t and getattr(c.order, "ocaGroup", "") == o.ocaGroup
                    and c.orderStatus.status in ("Submitted", "PreSubmitted")):
                c.orderStatus.status = "Cancelled"
        self.bot._apply_fill(ex)                    # the bot's real execution handler

    def process_bar(self, bar, tick, slip, con_id):
        """Fill working orders against one bar: entries first (market at open / stop triggers), then each
        active child: stop before target (stop wins ties), target needs a 1-tick trade-through; on an
        intrabar-triggered entry bar the target only counts if the bar CLOSES through it (engine rule)."""
        o_, h, l, c = bar.open, bar.high, bar.low, bar.close
        intrabar = set()
        mine = lambda: [t for t in self.openTrades() if t.contract.conId == con_id]
        for t in list(mine()):
            o = t.order
            if not o.orderRef.endswith("|entry") or t.orderStatus.status != "Submitted":
                continue
            buy = o.action == "BUY"
            if o.orderType == "MKT":
                self._fill(t, o_ + (slip if buy else -slip))
            elif o.orderType == "STP":
                lvl = o.auxPrice
                if (h >= lvl) if buy else (l <= lvl):
                    px = (max(o_, lvl) + slip) if buy else (min(o_, lvl) - slip)
                    if (lvl - o_) * (1 if buy else -1) > 1e-9:
                        intrabar.add(o.orderId)
                    self._fill(t, px)
        for t in list(self.openTrades()):
            o = t.order
            role = o.orderRef.split("|")[-1]
            if role not in ("tp", "sl") or t.orderStatus.status != "Submitted" or t.contract.conId != con_id:
                continue
            sell = o.action == "SELL"
            par_intra = getattr(o, "parentId", 0) in intrabar
            if role == "sl":
                lvl = o.auxPrice
                if (l <= lvl) if sell else (h >= lvl):
                    self._fill(t, (min(lvl, o_) - slip) if sell else (max(lvl, o_) + slip))
        for t in list(self.openTrades()):
            o = t.order
            role = o.orderRef.split("|")[-1]
            if role != "tp" or t.orderStatus.status != "Submitted" or t.contract.conId != con_id:
                continue
            sell = o.action == "SELL"
            par_intra = getattr(o, "parentId", 0) in intrabar
            hi, lo = (c, c) if par_intra else (h, l)
            lvl = o.lmtPrice
            if (hi >= lvl + tick) if sell else (lo <= lvl - tick):
                self._fill(t, lvl if par_intra else (max(lvl, o_) if sell else min(lvl, o_)))

    def process_closes(self, close_px, slip, con_id):
        for t in list(self.openTrades()):
            o = t.order
            if t.contract.conId != con_id:
                continue
            if o.orderType == "MKT" and not o.orderRef.endswith("|entry") and t.orderStatus.status == "Submitted":
                self._fill(t, close_px - slip if o.action == "SELL" else close_px + slip)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=os.path.join(HERE, "scalping_v2.json"))
    ap.add_argument("--days", type=int, default=40)
    a = ap.parse_args()
    cfg = json.load(open(a.config, encoding="utf-8"))
    cfg.update(dry_run=False, paper=True, account="DUSIM", daily_loss_limit_usd=0)
    tmp = tempfile.mkdtemp(prefix="scalping_v2_sim_")
    B.STATE_FILE = os.path.join(tmp, "state.json")
    B.LOG_DIR = os.path.join(tmp, "logs")
    B._APP_DIR = tmp
    B.now_et = lambda: SIM["t"]
    log_lines = []
    B.log = lambda msg, tag=None: log_lines.append(f"[{SIM['t']:%Y-%m-%d %H:%M:%S}] {msg}")

    data = {}
    for sym, sc in cfg["symbols"].items():
        if sc.get("enabled", True) and any(sym in st.get("symbols", []) for st in cfg["strategies"].values()):
            spec = C.SPECS[sym]
            data[sym] = C.add_indicators(load_csv_bars(C.SPECS[sym].get("data", sym), DEFAULT_DATA, "2025-09-02"), spec["tick"])
    days = sorted(set.intersection(*[set(df.day.unique()) for df in data.values()]))[-a.days:]
    SIM["t"] = datetime(days[0].year, days[0].month, days[0].day, 9, 0, tzinfo=ET)
    bot = B.ScalpingV2Bot(cfg, allow_live=False)
    bot.trades_csv_base = os.path.join(tmp, "scalping_v2_trades.csv")
    bot.signals_csv = os.path.join(tmp, "scalping_v2_signals.csv")
    bot.ib = FakeIB(bot)
    for k, sym in enumerate(data):
        bot.c[sym] = {"cont": None, "fut": SimpleNamespace(conId=k + 1, localSymbol=f"{sym}SIM"),
                      "tick": C.SPECS[sym]["tick"], "pv": C.SPECS[sym]["pv"]}
    bot.check_foreign = lambda: None
    for day in days:
        bot.state.update(date=str(day), seen_signals=[], day_pnl=0.0, day_trades=0)
        bot.day = day
        bars = {s: df[df.day == day].reset_index(drop=True) for s, df in data.items()}
        bot.sess_end = {s: min(960, int(b.tm.iloc[-1]) + 5) for s, b in bars.items()}   # early-close aware
        times = sorted({int(x) for b in bars.values() for x in b.tm})                    # union of bar times
        bot.refresh_today = lambda sym, expect_last_tm=None, retries=3: bot.today_df[sym]
        for tm in times:
            SIM["t"] = datetime(day.year, day.month, day.day, tm // 60, tm % 60, 6, tzinfo=ET)   # bar opens (+6s)
            bot.manage_timers()
            for s, b in bars.items():                                   # completed bars before this one
                bot.today_df[s] = b[b.tm < tm].reset_index(drop=True)
            if tm > 570:
                bot.evaluate(tm)
            cur = {s: b[b.tm == tm] for s, b in bars.items()}
            for s, row in cur.items():                                  # this bar trades
                if len(row):
                    bot.ib.process_bar(row.iloc[0], C.SPECS[s]["tick"], C.SPECS[s]["tick"], bot.c[s]["fut"].conId)
            SIM["t"] = SIM["t"] + timedelta(seconds=5 * 60 - 6 - 15)    # 15s before this bar closes
            bot.manage_timers()                                          # window / EOD flatten
            for s, row in cur.items():
                if len(row):
                    bot.ib.process_closes(float(row.close.iloc[0]), C.SPECS[s]["tick"], bot.c[s]["fut"].conId)
        SIM["t"] = datetime(day.year, day.month, day.day, 16, 3, tzinfo=ET)
        for t in list(bot.active_trades().values()):
            if t["status"] == "open":
                print("LEFT OPEN after session:", t["id"])
    # bot trades
    rows = []
    for f in os.listdir(tmp):
        if f.startswith("scalping_v2_trades_") and f.endswith(".csv"):
            rows.append(pd.read_csv(os.path.join(tmp, f)))
    bt_bot = pd.concat(rows) if rows else pd.DataFrame()
    # backtest (portfolio mode) for the same days
    T, _ = bt_run(cfg, DEFAULT_DATA, "2025-09-02", 1, True)
    T = T[T.taken & T.day.isin(days)]

    def key_bt(r):
        return (r.sym, r.strategy, str(r.day), f"{r.et // 60:02d}:{r.et % 60:02d}", "Long" if r.dir == 1 else "Short")

    def key_bot(r):
        d, tme = r.entry_time.split(" ")
        return (r.symbol, r.strategy.split("_", 2)[2], d, tme[:5], "Long" if r.side == "LONG" else "Short")
    bt_map = {key_bt(r): r for r in T.itertuples()}
    bot_map = {key_bot(r): r for r in bt_bot.itertuples()} if len(bt_bot) else {}
    both = set(bt_map) & set(bot_map)
    same_exit = sum(1 for k in both if abs(bot_map[k].exit - bt_map[k].exit) < 1.01 * C.SPECS[k[0]]["tick"])
    pnl_bt = T.net.sum()
    pnl_bot = bt_bot.pnl.sum() if len(bt_bot) else 0.0
    print(f"days simulated: {len(days)} ({days[0]} .. {days[-1]})")
    print(f"backtest trades {len(bt_map)} | bot trades {len(bot_map)} | matched entries {len(both)} | "
          f"matched with same exit (±1 tick) {same_exit}")
    print(f"P&L backtest ${pnl_bt:,.2f} | bot (sim broker, commission est.) ${pnl_bot:,.2f}")
    for k in sorted(set(bt_map) - set(bot_map))[:8]:
        print("  backtest-only:", k, bt_map[k].why)
    for k in sorted(set(bot_map) - set(bt_map))[:8]:
        print("  bot-only:", k, bot_map[k].reason)
    diffs = [k for k in both if abs(bot_map[k].exit - bt_map[k].exit) >= 1.01 * C.SPECS[k[0]]["tick"]][:8]
    for k in diffs:
        print(f"  exit differs {k}: bot {bot_map[k].exit} [{bot_map[k].reason}] vs backtest {bt_map[k].exit:.2f} [{bt_map[k].why}]")
    with open(os.path.join(HERE, "sim_test_log.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(log_lines))
    print(f"bot log -> sim_test_log.txt ({len(log_lines)} lines); temp dir {tmp}")
    shutil.copy(bot.signals_csv, os.path.join(HERE, "sim_test_signals.csv")) if os.path.exists(bot.signals_csv) else None


if __name__ == "__main__":
    main()
