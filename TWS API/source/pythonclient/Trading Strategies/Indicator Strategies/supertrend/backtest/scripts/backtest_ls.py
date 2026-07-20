"""Supertrend-bot backtest — direction=long_short vs long_only, MNQ & MES, 15m/30m/1h.

Faithful to supertrend_bot.py (post-update; core logic unchanged):
  * long_short = ALWAYS in market: LONG when Supertrend bullish, SHORT when bearish.
      - on a Supertrend flip -> flatten the current side AND immediately reverse into the
        opposite side, BUT only if the DEMA(200) filter permits that side (LONG needs
        close>DEMA, SHORT needs close<DEMA); otherwise go flat and retry on later bars.
  * ST(10,3), Wilder ATR (same indicator math). DEMA(200) entry filter on. ADX off.
  * protective stop = Supertrend line, trailed (initial floored to min_stop_pct=0.5%).
      LONG stop below price (trails up); SHORT stop above price (trails down).
  * exit on stop hit (intrabar) or flip. 24H (hold overnight). fixed 1 contract.
  * acts on last completed bar; entries/flips/reversals fill at the NEXT bar open.
  * MNQ $2/pt, MES $5/pt.
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


def dema_ok(direction, side, close, dema, dema_enabled=True):
    """DEMA(200) filter. long_only: LONG needs close>DEMA. long_short: same for LONG,
    SHORT needs close<DEMA. If dema unavailable, block (bot blocks a filter it can't eval).
    When dema_enabled is False, the filter is off and every entry is permitted."""
    if not dema_enabled:
        return True
    if dema is None:
        return False
    if side == "LONG":
        return close > dema
    return close < dema


def resolve_stop(side, entry_ref, line):
    if side == "LONG":
        return min(line, entry_ref * (1 - MIN_STOP_PCT))
    return max(line, entry_ref * (1 + MIN_STOP_PCT))


def run(bars, mult, direction):
    n = len(bars)
    h = [b["high"] for b in bars]; l = [b["low"] for b in bars]; c = [b["close"] for b in bars]
    o = [b["open"] for b in bars]; ts = [b["ts"] for b in bars]
    trend, line = supertrend(h, l, c, ATR_PERIOD, MULTIPLIER)
    bull = [t == 1 for t in trend]; dema = _dema(c, DEMA_PERIOD)

    trades = []
    side = None; entry = stop = 0.0; entry_ts = None; held = 0; exp = 0

    def desired_of(is_bull):
        if direction == "long_only":
            return "LONG" if is_bull else "FLAT"
        return "LONG" if is_bull else "SHORT"    # long_short

    def close_trade(exit_px, reason, t_out):
        pnl = (exit_px - entry) * mult if side == "LONG" else (entry - exit_px) * mult
        trades.append({"side": side, "pnl": pnl, "reason": reason, "held": held})

    def try_open(des, j):
        """open des side, fill at open[j+1]; returns (side,entry,stop,ts,held) or None."""
        if not dema_ok(direction, des, c[j], dema[j]):
            return None
        e = o[j + 1]; s = resolve_stop(des, c[j], line[j])
        if des == "LONG" and s >= e:  # stop must be below entry
            return None
        if des == "SHORT" and s <= e:  # stop must be above entry
            return None
        return (des, e, s, ts[j + 1], 0)

    for j in range(WARMUP, n):
        # A) protective stop resting during bar j (from prior-bar trail / initial)
        if side is not None:
            exp += 1
            if side == "LONG" and l[j] <= stop:
                close_trade(stop, "STOP", ts[j]); side = None
            elif side == "SHORT" and h[j] >= stop:
                close_trade(stop, "STOP", ts[j]); side = None

        # B) act on completed-bar-j signal, filling at open[j+1]
        if j + 1 >= n:
            continue
        des = desired_of(bull[j])

        if side is not None and des != side:
            # FLIP: flatten at next open, then reverse into des (DEMA-gated)
            ex = o[j + 1]
            close_trade(ex, "FLIP", ts[j + 1]); side = None
            opened = try_open(des, j)
            if opened:
                side, entry, stop, entry_ts, held = opened
        elif side is None:
            if des != "FLAT":
                opened = try_open(des, j)
                if opened:
                    side, entry, stop, entry_ts, held = opened
        else:
            # same side -> trail stop toward the Supertrend line
            if side == "LONG":
                ns = min(line[j], c[j] * (1 - 1e-4))
                if ns > stop:
                    stop = ns
            else:
                ns = max(line[j], c[j] * (1 + 1e-4))
                if ns < stop:
                    stop = ns
            held += 1

    if side is not None:
        close_trade(c[-1], "END", ts[-1])

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
    return {
        "n": n, "win": len(wins) / n * 100, "pf": gw / gl, "net": net,
        "ret": net / START_CAPITAL * 100, "mdd": mdd,
        "comm": net - n * COMMISSION_RT, "exp": exp / tb * 100 if tb > 0 else 0,
        "nl": len(longs), "ns": len(shorts),
        "long_pnl": sum(t["pnl"] for t in longs), "short_pnl": sum(t["pnl"] for t in shorts),
    }


def main():
    emit("Supertrend-bot backtest — long_short vs long_only  (ST(10,3)+DEMA200, 24H, 1 contract)")
    emit(f"Start ${START_CAPITAL:,.0f}, warmup {WARMUP} bars. MNQ $2/pt, MES $5/pt. All windows end 2026-07-17.")
    rows = []
    for sym, mult, tfs in SERIES:
        for label, fname in tfs:
            bars = load(f"{DATA_DIR}\\{fname}")
            period = f"{bars[WARMUP]['ts'].date()}->{bars[-1]['ts'].date()}" if len(bars) > WARMUP else "n/a"
            lo, _ = run(bars, mult, "long_only")
            ls, exp_ls = run(bars, mult, "long_short")
            r_lo = summarize(lo, 0, len(bars))
            r_ls = summarize(ls, exp_ls, len(bars))

            emit("\n" + "=" * 78)
            emit(f"{sym} {label}   ({len(bars):,} bars, 24H)   trading {period}")
            emit(f"  {'':16}{'long_only':>16}{'long_short':>16}")
            def line2(name, a, b, fmt):
                emit(f"  {name:<16}{fmt(a):>16}{fmt(b):>16}")
            line2("Trades", r_lo['n'], r_ls['n'], lambda x: f"{x}")
            line2("  long / short", f"{r_lo['nl']}/{r_lo['ns']}", f"{r_ls['nl']}/{r_ls['ns']}", lambda x: x)
            line2("Win rate", r_lo['win'], r_ls['win'], lambda x: f"{x:.1f}%")
            line2("Profit factor", r_lo['pf'], r_ls['pf'], lambda x: f"{x:.2f}")
            line2("Net P/L $", r_lo['net'], r_ls['net'], lambda x: f"{x:+,.0f}")
            line2("Return %", r_lo['ret'], r_ls['ret'], lambda x: f"{x:+.2f}%")
            line2("Net after comm", r_lo['comm'], r_ls['comm'], lambda x: f"{x:+,.0f}")
            line2("Max drawdown", r_lo['mdd'], r_ls['mdd'], lambda x: f"{x:.2f}%")
            line2("Time in mkt", r_lo['exp'], r_ls['exp'], lambda x: f"{x:.1f}%")
            emit(f"  long_short P/L split: long ${r_ls['long_pnl']:+,.0f} / short ${r_ls['short_pnl']:+,.0f}")
            rows.append((sym, label, r_lo, r_ls))

    emit("\n" + "=" * 100)
    emit("SUMMARY  (gross Net P/L $ | Profit factor | Win% | Trades)")
    emit("-" * 100)
    emit(f"{'Series':<12}{'long_only P/L':>16}{'PF':>6}{'Win%':>7}{'Tr':>5}   "
         f"{'long_short P/L':>16}{'PF':>6}{'Win%':>7}{'Tr':>5}")
    emit("-" * 100)
    for sym, label, a, b in rows:
        emit(f"{sym+' '+label:<12}{a['net']:>+16,.0f}{a['pf']:>6.2f}{a['win']:>7.1f}{a['n']:>5}   "
             f"{b['net']:>+16,.0f}{b['pf']:>6.2f}{b['win']:>7.1f}{b['n']:>5}")
    emit("=" * 100)
    emit("Note: long_short reverses on every Supertrend flip (DEMA-gated); the short leg only")
    emit("triggers when close < DEMA(200), so a slow DEMA blocks many shorts (-> flat instead).")
    emit("Stops modeled as filling exactly at the trailed Supertrend level (no slippage/gaps).")

    with open(f"{DATA_DIR}\\mnq_mes_longshort_backtest.txt", "w") as f:
        f.write("\n".join(OUT))
    print("\nSaved -> mnq_mes_longshort_backtest.txt")


if __name__ == "__main__":
    main()
