"""Offline test harness for supertrend_bot.py — exercises the bot's REAL decision path
(SupertrendBot.st_state / desired_side / dema_filter_ok + the shared Indicators math) on
historical CSVs, across 5m/15m/30m/1H, WITHOUT and WITH the DEMA(200) entry filter.

No IBKR connection: bars are loaded from CSV and passed to the same indicator functions the
live bot calls (supertrend_value/dema_value use bars=...). Reports June-2026 (the user's trade
month) return/DD/trades + $ on ~$363k avg deployed capital, a full-history return, and the
CURRENT signal produced by the bot's own methods.

NOTE: SOXL_1m.csv is the IBKR trade-executions export (not 1-min price bars), so a true
1-minute timeframe can't be tested from the provided files; 5-min (SOXL_5mins_1m.csv, ~1mo)
is the finest OHLC available and is used in its place.
"""
import sys, os, csv
from collections import namedtuple
from datetime import datetime

_IS = os.path.dirname(os.path.abspath(__file__))
_TS = os.path.dirname(_IS)
for p in (_IS, _TS):
    if p not in sys.path:
        sys.path.insert(0, p)

from supertrend_bot import SupertrendBot, LONG, SHORT, FLAT       # noqa: E402
from Indicators.trend.supertrend import supertrend               # noqa: E402
from Indicators.dema import dema                                 # noqa: E402

DATA = r"C:\Users\abdbasit\Downloads\Personal\Trade\IBKR\TWS API\source\pythonclient\Tools\Market Data\data"
AVG_CAP = 363_121.0   # user's time-weighted avg deployed capital in June (derived earlier)

Bar = namedtuple("Bar", "open high low close date")

def load(path):
    bars = []
    for r in csv.DictReader(open(path, newline='')):
        bars.append(Bar(float(r['open']), float(r['high']), float(r['low']),
                        float(r['close']), datetime.fromisoformat(r['date'])))
    bars.sort(key=lambda b: b.date)
    return bars

def sim(bot, bars, trend, dm, s, e):
    """Fully-invested long/cash sim mirroring manage_symbol: decide on completed bar i,
    act at bar i+1 open; exit on desired!=side; entries pass the same DEMA + flip gate."""
    C = [b.close for b in bars]
    eq = 1.0; side = FLAT; entry = 0.0; tr = 0; peak = 1.0; mdd = 0.0; inb = 0; tot = 0
    for k in range(s + 1, e + 1):
        i = k - 1; o = bars[k].open
        bull = trend[i] == 1
        desired = bot.desired_side(bull)                      # <-- bot's own method
        if side != FLAT and desired != side:
            eq *= (o / entry) if side == LONG else (entry / o); side = FLAT
        if side == FLAT and desired != FLAT:
            gate = True
            if bot.entry_on_flip_only:
                bp = trend[i - 1] == 1
                gate = (bull and not bp) if desired == LONG else ((not bull) and bp)
            if gate and bot.dema_enabled:                     # mirror dema_filter_ok
                d = dm[i]
                gate = (d is not None) and ((C[i] > d) if desired == LONG else (C[i] < d))
            if gate:
                side = desired; entry = o; tr += 1
        cur = eq * ((C[k] / entry) if side == LONG else (entry / C[k])) if side != FLAT else eq
        peak = max(peak, cur); mdd = min(mdd, (cur - peak) / peak)
        tot += 1; inb += (side != FLAT)
    if side != FLAT:   # close at the WINDOW boundary (bars[e]), not the global last bar
        eq *= (C[e] / entry) if side == LONG else (entry / C[e])
    return (eq - 1) * 100, mdd * 100, tr

TFS = [("5 mins", "SOXL_5mins_1m.csv"), ("15 mins", "SOXL_15mins_2y.csv"),
       ("30 mins", "SOXL_30mins_2y.csv"), ("1 hour", "SOXL_1hour_2y.csv")]

print("="*104)
print("SUPERTREND_BOT.PY — offline test (SOXL, long_only, ST(10,3))   $ on ~$%s avg June capital" % f"{AVG_CAP:,.0f}")
print("="*104)
h = f"{'Timeframe':<10}{'DEMA200':>9}{'Jun Ret%':>9}{'Jun DD%':>9}{'Jun Trd':>8}{'Jun $P&L':>13}{'FullRet%':>10}{'Now (bot)':>16}"
print(h); print("-"*len(h))

for bar_size, fn in TFS:
    bars = load(f"{DATA}\\{fn}")
    H=[b.high for b in bars]; L=[b.low for b in bars]; C=[b.close for b in bars]
    trend, line = supertrend(H, L, C, 10, 3.0)
    jidx = [k for k, b in enumerate(bars) if b.date.year == 2026 and b.date.month == 6]
    js, je = jidx[0], jidx[-1]
    fs = min(400, len(bars) // 4)
    for dema_on in (False, True):
        cfg = {"symbols": ["SOXL"], "bar_size": bar_size, "direction": "long_only",
               "supertrend": {"atr_period": 10, "multiplier": 3.0},
               "dema_filter": {"enabled": dema_on, "period": 200},
               "entry_on_flip_only": False, "log_dir": "logs"}
        bot = SupertrendBot(cfg, _IS)
        dm = dema(C, bot.dema_period) if bot.dema_enabled else [None]*len(C)
        jr, jd, jt = sim(bot, bars, trend, dm, js, je)
        fr, _, _   = sim(bot, bars, trend, dm, fs, len(bars)-1)
        # CURRENT signal via the bot's REAL methods on the full bars
        st = bot.st_state("SOXL", bars)
        nowsig = bot.desired_side(st[0]) if st else "n/a"
        if st and nowsig != FLAT:
            ok = bot.dema_filter_ok("SOXL", bars, nowsig)
            now = f"{nowsig}{'/ok' if ok else '/gated'}"
        else:
            now = nowsig
        print(f"{bar_size:<10}{('on' if dema_on else 'off'):>9}{jr:>9.1f}{jd:>9.1f}{jt:>8}"
              f"{AVG_CAP*jr/100:>13,.0f}{fr:>10.0f}{now:>16}")
    print(f"{'':<10}{'':>9}  data: {bars[0].date.date()} -> {bars[-1].date.date()}  ({len(bars):,} bars)")
print("-"*len(h))
print("Jun = June 2026 (your trade month). FullRet% = from bar 400 to end (period differs per TF; 5m ~1mo).")
