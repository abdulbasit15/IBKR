"""Backtest the Supertrend bot on MNQ across 1m/5m/15m/30m/1h — faithful to supertrend_bot.py.

Strategy replicated (from supertrend - futures.json / supertrend_bot.py):
  * direction long_only  -> LONG when Supertrend bullish, else FLAT (never short)
  * Supertrend ST(atr_period=10, multiplier=3)  (Wilder ATR, seeded — same as indicator)
  * DEMA(200) trend filter enabled -> enter LONG only when close > DEMA(200)
  * ADX filter disabled
  * market_hours 24H (no RTH filter, hold overnight / swing)
  * protective stop = the Supertrend line, TRAILED up each bar (never lowered):
        initial stop = min(ST_line, close*(1-min_stop_pct))     [min_stop_pct=0.005]
        trailed stop = max(prev, min(ST_line, close*(1-1e-4)))   [_st_stop clamp]
  * exit on stop hit (intrabar) OR on Supertrend flip to bearish (market, next bar open)
  * sizing fixed_stocks = 1 contract; MNQ multiplier = $2 / point
  * acts on the last COMPLETED bar; entry/flip fills modeled at the NEXT bar's open

Pure stdlib (matches the SOXL research engine). Reports per timeframe + a summary table.
"""
import csv
from datetime import datetime

DATA_DIR = r"C:\Users\abdbasit\Downloads\Personal\Trade"
START_CAPITAL = 100_000.0
MULT = 2.0            # MNQ = $2 per index point
CONTRACTS = 1        # fixed_stocks = 1
ATR_PERIOD, MULTIPLIER = 10, 3.0
DEMA_PERIOD = 200
MIN_STOP_PCT = 0.005
WARMUP = 400         # let DEMA(200) settle before trading (~2x period)
COMMISSION_RT = 1.04  # est. round-trip commission per MNQ contract ($/RT), for a net view

TFS = [("1 min", "MNQ_1min_bt.csv"), ("5 mins", "MNQ_5mins_bt.csv"),
       ("15 mins", "MNQ_15mins_bt.csv"), ("30 mins", "MNQ_30mins_bt.csv"),
       ("1 hour", "MNQ_1hour_bt.csv")]

OUT = []
def emit(s=""):
    print(s); OUT.append(s)


def load(path):
    bars = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            bars.append({"ts": datetime.fromisoformat(r["date"]),
                         "open": float(r["open"]), "high": float(r["high"]),
                         "low": float(r["low"]), "close": float(r["close"]),
                         "volume": float(r["volume"] or 0)})
    bars.sort(key=lambda b: b["ts"])
    return bars


# ---- indicators (identical math to Indicators/trend/supertrend.py & Indicators/dema.py) ----
def _rma(v, n):
    out = [None] * len(v)
    if not v:
        return out
    prev = v[0]; out[0] = prev; a = 1.0 / n
    for i in range(1, len(v)):
        x = v[i] if v[i] is not None else prev
        prev = prev + a * (x - prev); out[i] = prev
    return out


def _ema(v, n):
    out = [None] * len(v)
    if not v:
        return out
    a = 2.0 / (n + 1.0); prev = v[0]; out[0] = prev
    for i in range(1, len(v)):
        prev = (v[i] - prev) * a + prev; out[i] = prev
    return out


def _dema(v, n):
    e1 = _ema(v, n); e2 = _ema(e1, n)
    return [(2.0 * e1[i] - e2[i]) if (e1[i] is not None and e2[i] is not None) else None
            for i in range(len(v))]


def _true_range(h, l, c):
    tr = [h[0] - l[0]]
    for i in range(1, len(c)):
        tr.append(max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])))
    return tr


def supertrend(h, l, c, atr_period=10, mult=3.0):
    n = len(c); a = _rma(_true_range(h, l, c), atr_period)
    up = [0.0] * n; dn = [0.0] * n; trend = [1] * n; line = [0.0] * n
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


# ---- backtest engine (mirrors supertrend_bot.manage_symbol semantics) ----
def run(bars):
    n = len(bars)
    h = [b["high"] for b in bars]; l = [b["low"] for b in bars]; c = [b["close"] for b in bars]
    trend, line = supertrend(h, l, c, ATR_PERIOD, MULTIPLIER)
    bull = [t == 1 for t in trend]
    dema = _dema(c, DEMA_PERIOD)

    trades = []
    in_trade = False
    entry = stop = 0.0
    entry_ts = None
    bars_held = 0
    exposure_bars = 0

    for j in range(WARMUP, n):
        if in_trade:
            exposure_bars += 1
            # 1) protective stop resting during THIS bar (trailed to prior completed bar's line)
            if l[j] <= stop:
                _close(trades, entry_ts, bars[j]["ts"], entry, stop, "STOP", bars_held)
                in_trade = False; continue
            # 2) Supertrend flip -> bearish: exit at NEXT bar open (market on flip detection)
            if not bull[j]:
                ex = bars[j + 1]["open"] if j + 1 < n else c[j]
                _close(trades, entry_ts, (bars[j + 1]["ts"] if j + 1 < n else bars[j]["ts"]),
                       entry, ex, "FLIP", bars_held)
                in_trade = False; continue
            # 3) still bullish -> trail the stop up to the current Supertrend line
            new_stop = min(line[j], c[j] * (1 - 1e-4))
            if new_stop > stop:
                stop = new_stop
            bars_held += 1
        else:
            # flat -> entry gate on completed bar j: bullish AND close > DEMA(200); fill next open
            if bull[j] and dema[j] is not None and c[j] > dema[j] and j + 1 < n:
                e = bars[j + 1]["open"]
                s = min(line[j], c[j] * (1 - MIN_STOP_PCT))
                if s < e:                       # stop must sit below entry (bot skips otherwise)
                    in_trade = True; entry = e; stop = s
                    entry_ts = bars[j + 1]["ts"]; bars_held = 0

    if in_trade:
        _close(trades, entry_ts, bars[-1]["ts"], entry, c[-1], "END", bars_held)

    return trades, exposure_bars


def _close(trades, t_in, t_out, entry, exit_px, reason, held):
    pnl = (exit_px - entry) * MULT * CONTRACTS
    trades.append({"t_in": t_in, "t_out": t_out, "entry": entry, "exit": exit_px,
                   "pnl": pnl, "reason": reason, "held": held,
                   "ret_pts": exit_px - entry})


def metrics(label, bars, trades, exposure_bars):
    period = f"{bars[0]['ts'].date()} -> {bars[-1]['ts'].date()}"
    emit("\n" + "=" * 70)
    emit(f"Timeframe : {label}   ({len(bars):,} bars, 24H)   {period}")
    if not trades:
        emit("  NO TRADES"); return None
    n = len(trades)
    wins = [t for t in trades if t["pnl"] > 0]
    loss = [t for t in trades if t["pnl"] <= 0]
    gw = sum(t["pnl"] for t in wins); gl = abs(sum(t["pnl"] for t in loss)) or 1e-9
    net_pnl = sum(t["pnl"] for t in trades)
    net_after_comm = net_pnl - n * COMMISSION_RT
    # equity curve for drawdown
    eq = [START_CAPITAL]; acc = START_CAPITAL
    for t in trades:
        acc += t["pnl"]; eq.append(acc)
    peak = eq[0]; mdd = 0.0
    for e in eq:
        peak = max(peak, e); mdd = min(mdd, (e - peak) / peak * 100)
    total_ret = net_pnl / START_CAPITAL * 100
    win_rate = len(wins) / n * 100
    pf = gw / gl
    avg_w = gw / len(wins) if wins else 0
    avg_l = (sum(t["pnl"] for t in loss) / len(loss)) if loss else 0
    avg_hold = sum(t["held"] for t in trades) / n
    reasons = {}
    for t in trades:
        reasons[t["reason"]] = reasons.get(t["reason"], 0) + 1
    total_bars = len(bars) - WARMUP
    exposure = exposure_bars / total_bars * 100 if total_bars > 0 else 0

    emit(f"  Trades          : {n}   (STOP {reasons.get('STOP',0)} / FLIP {reasons.get('FLIP',0)} / END {reasons.get('END',0)})")
    emit(f"  Win rate        : {win_rate:.1f}%")
    emit(f"  Profit factor   : {pf:.2f}")
    emit(f"  Net P/L (gross) : ${net_pnl:+,.0f}   ({total_ret:+.2f}% on $100k, 1 contract)")
    emit(f"  Net P/L (comm.) : ${net_after_comm:+,.0f}   (after ~${COMMISSION_RT:.2f}/RT x {n})")
    emit(f"  Max drawdown    : {mdd:.2f}%   (on closed-trade equity)")
    emit(f"  Avg win / loss  : ${avg_w:+,.0f} / ${avg_l:+,.0f}   (payoff {abs(avg_w/avg_l):.2f})" if avg_l else
         f"  Avg win / loss  : ${avg_w:+,.0f} / $0")
    emit(f"  Avg hold (bars) : {avg_hold:.1f}")
    emit(f"  Time in market  : {exposure:.1f}%")
    return {"label": label, "n": n, "win": win_rate, "pf": pf, "pnl": net_pnl,
            "ret": total_ret, "mdd": mdd, "period": period}


def buyhold(bars):
    e = bars[WARMUP]["open"]; x = bars[-1]["close"]
    return (x - e) * MULT * CONTRACTS


def main():
    emit("MNQ Supertrend-bot backtest  —  long_only ST(10,3) + DEMA(200), 24H, 1 contract ($2/pt)")
    emit(f"Front month contract: MNQU6 (Sep 2026).  Start capital ${START_CAPITAL:,.0f}, warmup {WARMUP} bars.")
    rows = []
    for label, fname in TFS:
        try:
            bars = load(f"{DATA_DIR}\\{fname}")
        except FileNotFoundError:
            emit(f"\n{label}: data file {fname} missing"); continue
        if len(bars) <= WARMUP + 10:
            emit(f"\n{label}: only {len(bars)} bars (<= warmup); skipping"); continue
        trades, exp = run(bars)
        r = metrics(label, bars, trades, exp)
        if r:
            r["bh"] = buyhold(bars)
            rows.append(r)

    emit("\n" + "=" * 92)
    emit("SUMMARY  (long_only ST(10,3)+DEMA200, 24H, 1 MNQ contract, gross)")
    emit("-" * 92)
    emit(f"{'TF':<9}{'Trades':>7}{'Win%':>7}{'PF':>6}{'NetP/L$':>11}{'Ret%':>8}{'MaxDD%':>9}"
         f"{'B&H$':>10}")
    emit("-" * 92)
    for r in rows:
        emit(f"{r['label']:<9}{r['n']:>7}{r['win']:>7.1f}{r['pf']:>6.2f}{r['pnl']:>+11,.0f}"
             f"{r['ret']:>+8.2f}{r['mdd']:>9.2f}{r['bh']:>+10,.0f}")
    emit("=" * 92)
    emit("Notes: B&H = buy 1 contract at first bar, hold to last (same window). Stops modeled as")
    emit("filling exactly at the trailed Supertrend level (no slippage/gap-through). Single-contract")
    emit("futures history thins out in older months (contract not yet active), so longer-TF windows")
    emit("carry less liquid early data — treat 1h/30m results as shorter effective samples.")

    with open(f"{DATA_DIR}\\mnq_supertrend_backtest.txt", "w") as f:
        f.write("\n".join(OUT))
    print("\nSaved -> mnq_supertrend_backtest.txt")


if __name__ == "__main__":
    main()
