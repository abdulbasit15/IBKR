"""Supertrend-bot backtest — long_short, FILTER COMBINATIONS.  MNQ & MES, 15m/30m/1h.

Compares 4 entry-filter combos on the same faithful engine (ST(10,3), 24H, 1 contract,
reverse on every flip):
    NONE          - pure Supertrend
    DEMA          - DEMA(200) gate (LONG close>DEMA, SHORT close<DEMA)
    ADX           - ADX(14) >= 25 (trend-strength gate; direction from Supertrend)
    DEMA+ADX      - both must pass

ADX math = Wilder, identical to Indicators/trend/adx.py. Filters gate ENTRIES (incl. the
reverse leg of a flip); if a filter blocks, the bot goes flat and retries on later bars.
"""
import csv
from datetime import datetime

DATA_DIR = r"C:\Users\abdbasit\Downloads\Personal\Trade"
START_CAPITAL = 100_000.0
ATR_PERIOD, MULTIPLIER = 10, 3.0
DEMA_PERIOD = 200
ADX_PERIOD, ADX_THRESH = 14, 25.0
MIN_STOP_PCT = 0.005
WARMUP = 400
COMMISSION_RT = 1.04

SERIES = [
    ("MNQ", 2.0, [("15 mins", "MNQ_15mins_bt.csv"), ("30 mins", "MNQ_30mins_bt.csv"),
                  ("1 hour", "MNQ_1hour_bt.csv")]),
    ("MES", 5.0, [("15 mins", "MES_15mins_bt.csv"), ("30 mins", "MES_30mins_bt.csv"),
                  ("1 hour", "MES_1hour_bt.csv")]),
]
COMBOS = [("NONE", False, False), ("DEMA", True, False),
          ("ADX", False, True), ("DEMA+ADX", True, True)]

OUT = []
def emit(s=""):
    print(s); OUT.append(s)


def load(path):
    """Load bars, DROPPING zero-volume synthetic placeholder bars. The far-dated contract
    (MNQU6/MESU6) returns flat O=H=L=C bars with no volume during hours it had no trades;
    those pollute the indicators and manufacture fake gap-trades. The live bot only ever
    pulls liquid recent front-month data, so filtering them makes the backtest representative."""
    bars = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            vol = float(r["volume"] or 0)
            if vol <= 0:
                continue
            bars.append({"ts": datetime.fromisoformat(r["date"]), "open": float(r["open"]),
                         "high": float(r["high"]), "low": float(r["low"]),
                         "close": float(r["close"]), "volume": vol})
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


def adx_series(h, l, c, period=14):
    """Wilder ADX — identical to Indicators/trend/adx.py (returns adx list, None in warmup)."""
    n = len(c); ax = [None] * n
    if period <= 0 or n < period + 1:
        return ax
    tr = [0.0]*n; pdm = [0.0]*n; mdm = [0.0]*n
    for i in range(1, n):
        up = h[i] - h[i-1]; dnm = l[i-1] - l[i]
        pdm[i] = up if (up > dnm and up > 0) else 0.0
        mdm[i] = dnm if (dnm > up and dnm > 0) else 0.0
        tr[i] = max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1]))
    s_tr = [None]*n; s_p = [None]*n; s_m = [None]*n
    s_tr[period] = sum(tr[1:period+1]); s_p[period] = sum(pdm[1:period+1]); s_m[period] = sum(mdm[1:period+1])
    for i in range(period+1, n):
        s_tr[i] = s_tr[i-1] - s_tr[i-1]/period + tr[i]
        s_p[i] = s_p[i-1] - s_p[i-1]/period + pdm[i]
        s_m[i] = s_m[i-1] - s_m[i-1]/period + mdm[i]
    dx = [None]*n
    for i in range(period, n):
        rng = s_tr[i]
        if rng:
            pdi = 100.0*s_p[i]/rng; mdi = 100.0*s_m[i]/rng
            denom = pdi + mdi
            dx[i] = 100.0*abs(pdi-mdi)/denom if denom else 0.0
    first = period*2 - 1
    if first < n:
        seed = [dx[j] for j in range(period, first+1) if dx[j] is not None]
        if len(seed) == period:
            ax[first] = sum(seed)/period
            for i in range(first+1, n):
                if dx[i] is not None and ax[i-1] is not None:
                    ax[i] = (ax[i-1]*(period-1) + dx[i]) / period
    return ax


def resolve_stop(side, entry_ref, line):
    if side == "LONG":
        return min(line, entry_ref * (1 - MIN_STOP_PCT))
    return max(line, entry_ref * (1 + MIN_STOP_PCT))


def run(bars, mult, use_dema, use_adx):
    n = len(bars)
    h = [b["high"] for b in bars]; l = [b["low"] for b in bars]; c = [b["close"] for b in bars]
    o = [b["open"] for b in bars]; ts = [b["ts"] for b in bars]
    trend, line = supertrend(h, l, c, ATR_PERIOD, MULTIPLIER)
    bull = [t == 1 for t in trend]
    dema = _dema(c, DEMA_PERIOD)
    ax = adx_series(h, l, c, ADX_PERIOD)

    trades = []; side = None; entry = stop = 0.0; exp = 0

    def close_trade(exit_px, reason):
        pnl = (exit_px - entry) * mult if side == "LONG" else (entry - exit_px) * mult
        trades.append({"side": side, "pnl": pnl, "reason": reason})

    def filt_ok(des, j):
        if use_dema:
            if dema[j] is None:
                return False
            if des == "LONG" and not (c[j] > dema[j]):
                return False
            if des == "SHORT" and not (c[j] < dema[j]):
                return False
        if use_adx:
            if ax[j] is None or ax[j] < ADX_THRESH:
                return False
        return True

    def try_open(des, j):
        if not filt_ok(des, j):
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
    if side is not None:
        close_trade(c[-1], "END")
    return trades, exp


def summarize(trades, exp, nbars):
    if not trades:
        return {"n": 0, "win": 0, "pf": 0, "net": 0, "ret": 0, "mdd": 0, "exp": 0,
                "nl": 0, "ns": 0, "long_pnl": 0, "short_pnl": 0}
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
    return {"n": n, "win": len(wins)/n*100, "pf": gw/gl, "net": net, "ret": net/START_CAPITAL*100,
            "mdd": mdd, "exp": exp/tb*100 if tb > 0 else 0, "nl": len(longs), "ns": len(shorts),
            "long_pnl": sum(t["pnl"] for t in longs), "short_pnl": sum(t["pnl"] for t in shorts)}


def main():
    emit("Supertrend-bot backtest — long_short, FILTER COMBINATIONS  (ST(10,3), 24H, 1 contract)")
    emit(f"ADX = Wilder ADX({ADX_PERIOD}) >= {ADX_THRESH:.0f}. DEMA = DEMA({DEMA_PERIOD}). "
         f"MNQ $2/pt, MES $5/pt. Windows end 2026-07-18.")
    all_rows = []
    for sym, mult, tfs in SERIES:
        for label, fname in tfs:
            bars = load(f"{DATA_DIR}\\{fname}")
            period = f"{bars[WARMUP]['ts'].date()}->{bars[-1]['ts'].date()}"
            res = {}
            for cname, ud, ua in COMBOS:
                t, e = run(bars, mult, ud, ua)
                res[cname] = summarize(t, e, len(bars))
            emit("\n" + "=" * 92)
            emit(f"{sym} {label}   ({len(bars):,} bars, 24H)   trading {period}")
            emit(f"  {'metric':<16}" + "".join(f"{cn:>16}" for cn, _, _ in COMBOS))
            def row(name, fmt, key=None, func=None):
                vals = []
                for cn, _, _ in COMBOS:
                    r = res[cn]
                    v = func(r) if func else r[key]
                    vals.append(fmt(v))
                emit(f"  {name:<16}" + "".join(f"{v:>16}" for v in vals))
            row("Trades", lambda z: f"{z}", "n")
            row("  long/short", lambda z: z, func=lambda r: f"{r['nl']}/{r['ns']}")
            row("Win rate", lambda z: f"{z:.1f}%", "win")
            row("Profit factor", lambda z: f"{z:.2f}", "pf")
            row("Net P/L $", lambda z: f"{z:+,.0f}", "net")
            row("Return %", lambda z: f"{z:+.2f}%", "ret")
            row("Max drawdown", lambda z: f"{z:.2f}%", "mdd")
            row("Time in mkt", lambda z: f"{z:.1f}%", "exp")
            row("Long P/L", lambda z: f"{z:+,.0f}", "long_pnl")
            row("Short P/L", lambda z: f"{z:+,.0f}", "short_pnl")
            all_rows.append((sym, label, res))

    emit("\n" + "=" * 92)
    emit("SUMMARY — Net P/L $ (Profit factor) by filter combo, long_short")
    emit("-" * 92)
    emit(f"{'Series':<12}" + "".join(f"{cn:>19}" for cn, _, _ in COMBOS))
    emit("-" * 92)
    for sym, label, res in all_rows:
        cells = "".join(f"{res[cn]['net']:>+11,.0f} ({res[cn]['pf']:>4.2f})" for cn, _, _ in COMBOS)
        emit(f"{sym+' '+label:<12}{cells}")
    emit("=" * 92)
    emit("Best combo per series (by gross Net P/L):")
    for sym, label, res in all_rows:
        best = max(COMBOS, key=lambda cc: res[cc[0]]['net'])
        b = res[best[0]]
        emit(f"  {sym+' '+label:<12} -> {best[0]:<10} ${b['net']:+,.0f}  PF {b['pf']:.2f}  Win {b['win']:.1f}%")
    emit("\nADX gates entries by trend STRENGTH only (>=25); direction still from Supertrend.")
    emit("Stops modeled as filling exactly at the trailed Supertrend level (no slippage/gaps).")

    with open(f"{DATA_DIR}\\mnq_mes_longshort_filter_combos.txt", "w") as f:
        f.write("\n".join(OUT))
    print("\nSaved -> mnq_mes_longshort_filter_combos.txt")


if __name__ == "__main__":
    main()
