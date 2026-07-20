"""Supertrend-bot backtest — long_short: DEMA(200) ON vs OFF.  MNQ & MES, 15m/30m/1h.

Same faithful engine as backtest_ls.py. Only difference tested here: the DEMA(200) entry
filter. With DEMA OFF, long_short is PURE Supertrend — always in market, LONG when bullish
/ SHORT when bearish, reversing on every flip (no close-vs-DEMA gate). ST(10,3), 24H, 1 ctr.
"""
import csv
from datetime import datetime

DATA_DIR = r"C:\Users\abdbasit\Downloads\Personal\Trade"
START_CAPITAL = 100_000.0
ATR_PERIOD, MULTIPLIER = 10, 3.0
DEMA_PERIOD = 200
MIN_STOP_PCT = 0.005
WARMUP = 400
COMMISSION_RT = 1.04

SERIES = [
    ("MNQ", 2.0, [("15 mins", "MNQ_15mins_bt.csv"), ("30 mins", "MNQ_30mins_bt.csv"),
                  ("1 hour", "MNQ_1hour_bt.csv")]),
    ("MES", 5.0, [("15 mins", "MES_15mins_bt.csv"), ("30 mins", "MES_30mins_bt.csv"),
                  ("1 hour", "MES_1hour_bt.csv")]),
]

OUT = []
def emit(s=""):
    print(s); OUT.append(s)


def load(path):
    bars = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            bars.append({"ts": datetime.fromisoformat(r["date"]), "open": float(r["open"]),
                         "high": float(r["high"]), "low": float(r["low"]),
                         "close": float(r["close"]), "volume": float(r["volume"] or 0)})
    bars.sort(key=lambda b: b["ts"]); return bars


def _rma(v, n):
    out = [None] * len(v)
    if not v: return out
    prev = v[0]; out[0] = prev; a = 1.0 / n
    for i in range(1, len(v)):
        x = v[i] if v[i] is not None else prev
        prev = prev + a * (x - prev); out[i] = prev
    return out

def _ema(v, n):
    out = [None] * len(v)
    if not v: return out
    a = 2.0 / (n + 1.0); prev = v[0]; out[0] = prev
    for i in range(1, len(v)):
        prev = (v[i] - prev) * a + prev; out[i] = prev
    return out

def _dema(v, n):
    e1 = _ema(v, n); e2 = _ema(e1, n)
    return [(2.0 * e1[i] - e2[i]) if (e1[i] is not None and e2[i] is not None) else None
            for i in range(len(v))]

def _tr(h, l, c):
    tr = [h[0] - l[0]]
    for i in range(1, len(c)):
        tr.append(max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])))
    return tr

def supertrend(h, l, c, atr_period=10, mult=3.0):
    n = len(c); a = _rma(_tr(h, l, c), atr_period)
    up = [0.0]*n; dn = [0.0]*n; trend = [1]*n; line = [0.0]*n
    for i in range(n):
        hl2 = (h[i] + l[i]) / 2.0
        bu = hl2 - mult * (a[i] or 0.0); bd = hl2 + mult * (a[i] or 0.0)
        if i == 0:
            up[i] = bu; dn[i] = bd; trend[i] = 1; line[i] = bu; continue
        pc = c[i - 1]
        up[i] = bu if (bu > up[i - 1] or pc < up[i - 1]) else up[i - 1]
        dn[i] = bd if (bd < dn[i - 1] or pc > dn[i - 1]) else dn[i - 1]
        pt = trend[i - 1]
        trend[i] = 1 if (pt == -1 and c[i] > dn[i]) else (-1 if (pt == 1 and c[i] < up[i]) else pt)
        line[i] = up[i] if trend[i] == 1 else dn[i]
    return trend, line


def dema_ok(side, close, dema, dema_enabled):
    if not dema_enabled:
        return True
    if dema is None:
        return False
    return close > dema if side == "LONG" else close < dema


def resolve_stop(side, entry_ref, line):
    if side == "LONG":
        return min(line, entry_ref * (1 - MIN_STOP_PCT))
    return max(line, entry_ref * (1 + MIN_STOP_PCT))


def run(bars, mult, dema_enabled):
    """direction = long_short always here."""
    n = len(bars)
    h = [b["high"] for b in bars]; l = [b["low"] for b in bars]; c = [b["close"] for b in bars]
    o = [b["open"] for b in bars]; ts = [b["ts"] for b in bars]
    trend, line = supertrend(h, l, c, ATR_PERIOD, MULTIPLIER)
    bull = [t == 1 for t in trend]; dema = _dema(c, DEMA_PERIOD)

    trades = []; side = None; entry = stop = 0.0; held = 0; exp = 0

    def close_trade(exit_px, reason):
        pnl = (exit_px - entry) * mult if side == "LONG" else (entry - exit_px) * mult
        trades.append({"side": side, "pnl": pnl, "reason": reason})

    def try_open(des, j):
        if not dema_ok(des, c[j], dema[j], dema_enabled):
            return None
        e = o[j + 1]; s = resolve_stop(des, c[j], line[j])
        if des == "LONG" and s >= e:
            return None
        if des == "SHORT" and s <= e:
            return None
        return (des, e, s)

    for j in range(WARMUP, n):
        if side is not None:
            exp += 1
            if side == "LONG" and l[j] <= stop:
                close_trade(stop, "STOP"); side = None
            elif side == "SHORT" and h[j] >= stop:
                close_trade(stop, "STOP"); side = None
        if j + 1 >= n:
            continue
        des = "LONG" if bull[j] else "SHORT"
        if side is not None and des != side:
            close_trade(o[j + 1], "FLIP"); side = None
            opened = try_open(des, j)
            if opened:
                side, entry, stop = opened
        elif side is None:
            opened = try_open(des, j)
            if opened:
                side, entry, stop = opened
        else:
            if side == "LONG":
                ns = min(line[j], c[j] * (1 - 1e-4))
                if ns > stop: stop = ns
            else:
                ns = max(line[j], c[j] * (1 + 1e-4))
                if ns < stop: stop = ns
            held += 1
    if side is not None:
        close_trade(c[-1], "END")
    return trades, exp


def summarize(trades, exp, nbars):
    if not trades:
        return None
    n = len(trades)
    wins = [t for t in trades if t["pnl"] > 0]; loss = [t for t in trades if t["pnl"] <= 0]
    gw = sum(t["pnl"] for t in wins); gl = abs(sum(t["pnl"] for t in loss)) or 1e-9
    net = sum(t["pnl"] for t in trades)
    longs = [t for t in trades if t["side"] == "LONG"]; shorts = [t for t in trades if t["side"] == "SHORT"]
    eq = [START_CAPITAL]; acc = START_CAPITAL
    for t in trades:
        acc += t["pnl"]; eq.append(acc)
    peak = eq[0]; mdd = 0.0
    for e in eq:
        peak = max(peak, e); mdd = min(mdd, (e - peak) / peak * 100)
    tb = nbars - WARMUP
    return {"n": n, "win": len(wins) / n * 100, "pf": gw / gl, "net": net,
            "ret": net / START_CAPITAL * 100, "mdd": mdd, "comm": net - n * COMMISSION_RT,
            "exp": exp / tb * 100 if tb > 0 else 0, "nl": len(longs), "ns": len(shorts),
            "long_pnl": sum(t["pnl"] for t in longs), "short_pnl": sum(t["pnl"] for t in shorts)}


def main():
    emit("Supertrend-bot backtest — long_short: DEMA(200) ON vs OFF  (ST(10,3), 24H, 1 contract)")
    emit(f"Start ${START_CAPITAL:,.0f}, warmup {WARMUP} bars. MNQ $2/pt, MES $5/pt. Windows end 2026-07-17.")
    rows = []
    for sym, mult, tfs in SERIES:
        for label, fname in tfs:
            bars = load(f"{DATA_DIR}\\{fname}")
            period = f"{bars[WARMUP]['ts'].date()}->{bars[-1]['ts'].date()}"
            on_t, on_e = run(bars, mult, True)
            off_t, off_e = run(bars, mult, False)
            a = summarize(on_t, on_e, len(bars))    # DEMA ON
            b = summarize(off_t, off_e, len(bars))   # DEMA OFF
            emit("\n" + "=" * 78)
            emit(f"{sym} {label}   ({len(bars):,} bars, 24H)   trading {period}")
            emit(f"  {'':16}{'DEMA ON':>16}{'DEMA OFF':>16}")
            def L(name, x, y, fmt):
                emit(f"  {name:<16}{fmt(x):>16}{fmt(y):>16}")
            L("Trades", a['n'], b['n'], lambda z: f"{z}")
            L("  long / short", f"{a['nl']}/{a['ns']}", f"{b['nl']}/{b['ns']}", lambda z: z)
            L("Win rate", a['win'], b['win'], lambda z: f"{z:.1f}%")
            L("Profit factor", a['pf'], b['pf'], lambda z: f"{z:.2f}")
            L("Net P/L $", a['net'], b['net'], lambda z: f"{z:+,.0f}")
            L("Return %", a['ret'], b['ret'], lambda z: f"{z:+.2f}%")
            L("Net after comm", a['comm'], b['comm'], lambda z: f"{z:+,.0f}")
            L("Max drawdown", a['mdd'], b['mdd'], lambda z: f"{z:.2f}%")
            L("Time in mkt", a['exp'], b['exp'], lambda z: f"{z:.1f}%")
            emit(f"  P/L split ON : long ${a['long_pnl']:+,.0f} / short ${a['short_pnl']:+,.0f}")
            emit(f"  P/L split OFF: long ${b['long_pnl']:+,.0f} / short ${b['short_pnl']:+,.0f}")
            rows.append((sym, label, a, b))
    emit("\n" + "=" * 100)
    emit("SUMMARY — long_short  (gross Net P/L $ | PF | Win% | Trades)")
    emit("-" * 100)
    emit(f"{'Series':<12}{'DEMA ON P/L':>15}{'PF':>6}{'Win%':>7}{'Tr':>5}   "
         f"{'DEMA OFF P/L':>15}{'PF':>6}{'Win%':>7}{'Tr':>5}")
    emit("-" * 100)
    for sym, label, a, b in rows:
        emit(f"{sym+' '+label:<12}{a['net']:>+15,.0f}{a['pf']:>6.2f}{a['win']:>7.1f}{a['n']:>5}   "
             f"{b['net']:>+15,.0f}{b['pf']:>6.2f}{b['win']:>7.1f}{b['n']:>5}")
    emit("=" * 100)
    emit("DEMA OFF = pure Supertrend long_short (always in market, reverse on every flip).")
    emit("Stops modeled as filling exactly at the trailed Supertrend level (no slippage/gaps).")
    with open(f"{DATA_DIR}\\mnq_mes_longshort_dema_on_off.txt", "w") as f:
        f.write("\n".join(OUT))
    print("\nSaved -> mnq_mes_longshort_dema_on_off.txt")


if __name__ == "__main__":
    main()
