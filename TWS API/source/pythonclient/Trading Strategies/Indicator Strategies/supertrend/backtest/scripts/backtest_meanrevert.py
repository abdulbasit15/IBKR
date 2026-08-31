"""TIER-2 MEAN-REVERSION validation. Does fading Bollinger-band extremes in the CHOP regime
(the supertrendv2 tier-2 feature) beat simply standing aside?

Three long_short strategies over continuous futures (vol>0), 1 contract, ST(10,3)+DEMA(200) base:
  ST+REGIME       - regime gate, NO DEMA, stand-aside in chop      (baseline, no-DEMA)
  ST+DEMA+REG     - regime gate + DEMA, stand-aside in chop        (DEPLOYED baseline; reproduces
                                                                    mnq_mes_regime_dema_vs_nodema.txt)
  ST+DEMA+REG+MR  - same, but in CHOP FADE the bands back to the mean instead of standing aside
                    (tier-2: LONG when %B<=entry_pb & RSI<=oversold, SHORT when %B>=1-entry_pb &
                     RSI>=overbought; fixed stop = stop_atr_mult*ATR beyond the band; take-profit at
                     the Bollinger basis; also exits on a regime flip to TREND or max_hold_bars).

The first two runs are copied verbatim from backtest_two.py so their numbers MATCH the published
table exactly — the +MR column is the only new behaviour, isolated to the CHOP regime, so the
difference is purely the mean-reversion contribution. Period Nov25-Jul26 (choppy + trending).
"""
import os, sys
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backtest_regime as R

D = R.D
WARM = 500
WINDOWS = [("CHOPPY Nov25-Mar26", "2025-11-01", "2026-04-01"),
           ("TREND  Apr-Jul26", "2026-04-01", "2026-07-18"),
           ("BOTH   Nov25-Jul26", "2025-11-01", "2026-07-18")]
SERIES = [("MNQ", 2.0, [("15m", "MNQ_cont_15mins.csv"), ("30m", "MNQ_cont_30mins.csv"), ("1h", "MNQ_cont_1hour.csv")]),
          ("MES", 5.0, [("15m", "MES_cont_15mins.csv"), ("30m", "MES_cont_30mins.csv"), ("1h", "MES_cont_1hour.csv")])]
STRATS = ["ST+REGIME", "ST+DEMA+REG", "ST+DEMA+REG+MR"]

# --- tier-2 mean-revert params (mirror supertrendv2/supertrendv2.json -> regime_filter.mean_revert)
BB_LEN, BB_MULT = 20, 2.0
ENTRY_PB = 0.05
REQUIRE_RSI, RSI_OS, RSI_OB = True, 30.0, 70.0
MR_ATR_P, STOP_ATR = 14, 1.0
MAX_HOLD = 12
ALLOW_LONG, ALLOW_SHORT = True, True   # long_short

OUT = []
def emit(s=""):
    print(s); OUT.append(s)


def idx_at(bars, ds):
    dt = datetime.fromisoformat(ds)
    for i, b in enumerate(bars):
        if b["ts"].replace(tzinfo=None) >= dt:
            return i
    return len(bars)


def _sma(v, n):
    out = [None] * len(v)
    for i in range(len(v)):
        if i >= n - 1:
            out[i] = sum(v[i - n + 1:i + 1]) / n
    return out


def bollinger(c, n=20, mult=2.0):
    """(basis, upper, lower, percent_b) — SMA basis + population stdev, matching Indicators."""
    basis = _sma(c, n)
    up = [None] * len(c); lo = [None] * len(c); pb = [None] * len(c)
    for i in range(len(c)):
        if basis[i] is None:
            continue
        w = c[i - n + 1:i + 1]
        m = basis[i]
        sd = (sum((x - m) ** 2 for x in w) / n) ** 0.5
        up[i] = m + mult * sd; lo[i] = m - mult * sd
        rng = up[i] - lo[i]
        pb[i] = (c[i] - lo[i]) / rng if rng else 0.0
    return basis, up, lo, pb


# ============================ BASELINES (verbatim from backtest_two.py) =====================
def run_baseline(bars, mult, strat, start_i):
    n = len(bars)
    h = [b["high"] for b in bars]; l = [b["low"] for b in bars]; c = [b["close"] for b in bars]; o = [b["open"] for b in bars]
    trend, line = R.supertrend(h, l, c, R.ATR_P, R.ST_MULT); bull = [t == 1 for t in trend]
    dema = R._dema(c, R.DEMA_P)
    adx = R.adx_series(h, l, c, R.ADX_P); chop = R.choppiness(h, l, c, R.CHOP_P); reg = R.regimes(adx, chop)
    use_dema = (strat == "ST+DEMA+REG")
    trades = []; side = None; entry = stop = 0.0
    def close_t(px):
        trades.append((px - entry) * mult if side == "LONG" else (entry - px) * mult)
    def allowed(des, j):
        if use_dema:
            if dema[j] is None: return False
            if des == "LONG" and not c[j] > dema[j]: return False
            if des == "SHORT" and not c[j] < dema[j]: return False
        if reg[j] == "CHOP": return False
        return True
    def opn(des, j):
        if not allowed(des, j): return None
        e = o[j + 1]; s = (min(line[j], c[j] * (1 - R.MIN_STOP_PCT)) if des == "LONG" else max(line[j], c[j] * (1 + R.MIN_STOP_PCT)))
        if des == "LONG" and s >= e: return None
        if des == "SHORT" and s <= e: return None
        return (des, e, s)
    for j in range(start_i, n):
        if side is not None:
            if side == "LONG" and l[j] <= stop: close_t(stop); side = None
            elif side == "SHORT" and h[j] >= stop: close_t(stop); side = None
        if j + 1 >= n: continue
        des = "LONG" if bull[j] else "SHORT"
        if side is not None and des != side:
            close_t(o[j + 1]); side = None
            op = opn(des, j)
            if op: side, entry, stop = op
        elif side is None:
            op = opn(des, j)
            if op: side, entry, stop = op
        else:
            if side == "LONG":
                ns = min(line[j], c[j] * (1 - 1e-4))
                if ns > stop: stop = ns
            else:
                ns = max(line[j], c[j] * (1 + 1e-4))
                if ns < stop: stop = ns
    if side is not None: close_t(c[-1])
    return trades


# ============================ TIER-2: mean-revert in CHOP ==================================
def run_mr(bars, mult, start_i):
    """ST+DEMA+REGIME, but CHOP regime FADES the bands instead of standing aside. TREND handling is
    identical to the baseline, so the TREND-phase result matches ST+DEMA+REG; the difference is the
    CHOP mean-reversion. `kind` tags each open position TREND vs MR so each is managed by its own
    rules (MR = fixed stop, revert-to-mean take-profit, regime-flip + time exits, never trailed)."""
    n = len(bars)
    h = [b["high"] for b in bars]; l = [b["low"] for b in bars]; c = [b["close"] for b in bars]; o = [b["open"] for b in bars]
    trend, line = R.supertrend(h, l, c, R.ATR_P, R.ST_MULT); bull = [t == 1 for t in trend]
    dema = R._dema(c, R.DEMA_P)
    adx = R.adx_series(h, l, c, R.ADX_P); chop = R.choppiness(h, l, c, R.CHOP_P); reg = R.regimes(adx, chop)
    rs = R.rsi(c, R.RSI_P)
    basis, upper, lower, pb = bollinger(c, BB_LEN, BB_MULT)
    atrv = R._rma(R._tr(h, l, c), MR_ATR_P)

    trades = []; side = None; kind = None; entry = stop = target = 0.0; j0 = 0
    def close_t(px, why):
        trades.append({"pnl": (px - entry) * mult if side == "LONG" else (entry - px) * mult, "why": why})

    def opn_trend(des, j):                       # identical DEMA gate + ST stop as the baseline
        if dema[j] is None: return None
        if des == "LONG" and not c[j] > dema[j]: return None
        if des == "SHORT" and not c[j] < dema[j]: return None
        e = o[j + 1]; s = (min(line[j], c[j] * (1 - R.MIN_STOP_PCT)) if des == "LONG" else max(line[j], c[j] * (1 + R.MIN_STOP_PCT)))
        if des == "LONG" and s >= e: return None
        if des == "SHORT" and s <= e: return None
        return (des, e, s)

    def opn_mr(j):                               # tier-2 band fade (mirrors maybe_open_mean_revert)
        if pb[j] is None: return None
        if REQUIRE_RSI and rs[j] is None: return None
        des = None
        if pb[j] <= ENTRY_PB and ALLOW_LONG:
            if (not REQUIRE_RSI) or (rs[j] is not None and rs[j] <= RSI_OS): des = "LONG"
        elif pb[j] >= (1.0 - ENTRY_PB) and ALLOW_SHORT:
            if (not REQUIRE_RSI) or (rs[j] is not None and rs[j] >= RSI_OB): des = "SHORT"
        if des is None: return None
        if atrv[j] is None or lower[j] is None or upper[j] is None or basis[j] is None: return None
        e = o[j + 1]
        if des == "LONG":
            s = min(lower[j] - STOP_ATR * atrv[j], c[j] * (1 - R.MIN_STOP_PCT))
            if basis[j] <= c[j] or s >= e: return None      # target must be beyond entry
        else:
            s = max(upper[j] + STOP_ATR * atrv[j], c[j] * (1 + R.MIN_STOP_PCT))
            if basis[j] >= c[j] or s <= e: return None
        return (des, e, s, basis[j], j)

    for j in range(start_i, n):
        # 1) intrabar protective stop (both kinds)
        if side is not None:
            if side == "LONG" and l[j] <= stop:
                close_t(stop, "MR_STOP" if kind == "MR" else "STOP"); side = kind = None
            elif side == "SHORT" and h[j] >= stop:
                close_t(stop, "MR_STOP" if kind == "MR" else "STOP"); side = kind = None
        if j + 1 >= n: continue

        # 2) MR positions: regime-flip / take-profit / time exits (act at next open), never trail/flip
        if side is not None and kind == "MR":
            why = None
            if reg[j] == "TREND":
                why = "MR_REGIME"
            elif basis[j] is not None and ((side == "LONG" and c[j] >= basis[j]) or (side == "SHORT" and c[j] <= basis[j])):
                why = "MR_TARGET"
            elif (j - j0) >= MAX_HOLD:
                why = "MR_TIME"
            if why:
                close_t(o[j + 1], why); side = kind = None
            continue                              # MR never flips/trails; one action per bar

        # 3) trend management + new entries (TREND regime -> trend follow; CHOP -> mean-revert fade)
        des = "LONG" if bull[j] else "SHORT"
        if side is not None and des != side:      # trend flip/reverse
            close_t(o[j + 1], "FLIP"); side = kind = None
            if reg[j] == "TREND":
                op = opn_trend(des, j)
                if op: side, entry, stop = op; kind = "TREND"
            else:
                m = opn_mr(j)
                if m: side, entry, stop, target, j0 = m; kind = "MR"
        elif side is None:
            if reg[j] == "TREND":
                op = opn_trend(des, j)
                if op: side, entry, stop = op; kind = "TREND"
            else:
                m = opn_mr(j)
                if m: side, entry, stop, target, j0 = m; kind = "MR"
        else:                                     # hold trend -> trail the ST stop
            if side == "LONG":
                ns = min(line[j], c[j] * (1 - 1e-4))
                if ns > stop: stop = ns
            else:
                ns = max(line[j], c[j] * (1 + 1e-4))
                if ns < stop: stop = ns
    if side is not None:
        close_t(c[-1], "END")
    return trades


def summ(t):
    # accepts a list of floats (baselines) OR dicts with 'pnl' (mr)
    pnls = [x["pnl"] if isinstance(x, dict) else x for x in t]
    if not pnls: return {"n": 0, "win": 0, "pf": 0, "net": 0, "mdd": 0}
    wins = [x for x in pnls if x > 0]; gw = sum(wins); gl = abs(sum(x for x in pnls if x <= 0)) or 1e-9
    eq = [0.0]; acc = 0.0
    for x in pnls: acc += x; eq.append(acc)
    peak = eq[0]; mdd = 0.0
    for e in eq: peak = max(peak, e); mdd = min(mdd, e - peak)
    return {"n": len(pnls), "win": len(wins) / len(pnls) * 100, "pf": gw / gl, "net": sum(pnls), "mdd": mdd}


def reasons(t):
    d = {}
    for x in t:
        if isinstance(x, dict):
            d[x["why"]] = d.get(x["why"], 0) + 1
    return d


def main():
    emit("TIER-2 MEAN-REVERSION vs STAND-ASIDE  (long_short, continuous futures, 1 contract)")
    emit("Does fading the bands in CHOP beat sitting out? ST(10,3)+DEMA(200)+regime base. "
         f"BB({BB_LEN},{BB_MULT}) %B<= {ENTRY_PB}, RSI {RSI_OS:.0f}/{RSI_OB:.0f}, stop {STOP_ATR}xATR({MR_ATR_P}), "
         f"hold<= {MAX_HOLD}. Period Nov25-Jul26 (choppy + trending). MNQ $2/pt, MES $5/pt.")
    tot = {w[0]: {s: 0.0 for s in STRATS} for w in WINDOWS}
    dd = {w[0]: {s: 0.0 for s in STRATS} for w in WINDOWS}
    for sym, mult, tfs in SERIES:
        for tf, fname in tfs:
            bars = R.load(os.path.join(D, fname))
            emit(f"\n{'='*92}\n{sym} {tf}")
            emit(f"  {'phase':<20}{'strategy':<16}{'Trd':>5}{'Win%':>7}{'PF':>6}{'NetP/L$':>11}{'MaxDD$':>10}   mr-exits")
            for wname, ws, we in WINDOWS:
                si = idx_at(bars, ws); ei = idx_at(bars, we)
                sub = bars[max(0, si - WARM):ei]; start_i = si - max(0, si - WARM)
                for s in STRATS:
                    if s == "ST+DEMA+REG+MR":
                        raw = run_mr(sub, mult, start_i)
                    else:
                        raw = run_baseline(sub, mult, s, start_i)
                    r = summ(raw); tot[wname][s] += r["net"]; dd[wname][s] = min(dd[wname][s], r["mdd"])
                    rx = reasons(raw)
                    rxs = " ".join(f"{k.split('_')[1].lower()}:{v}" for k, v in sorted(rx.items()) if k.startswith("MR")) if s.endswith("MR") else ""
                    emit(f"  {wname:<20}{s:<16}{r['n']:>5}{r['win']:>7.1f}{r['pf']:>6.2f}{r['net']:>+11,.0f}{r['mdd']:>+10,.0f}   {rxs}")
                emit("")
    emit("=" * 92)
    emit("TOTALS across all 6 series - Net P/L $ (and worst single-series MaxDD $):")
    emit(f"  {'phase':<20}" + "".join(f"{s:>18}" for s in STRATS))
    for wname, _, _ in WINDOWS:
        emit(f"  {wname:<20}" + "".join(f"{tot[wname][s]:>+18,.0f}" for s in STRATS))
    emit(f"  {'(worst series DD)':<20}" + "".join(f"{dd[wname][s]:>18,.0f}" for wname in [WINDOWS[-1][0]] for s in STRATS))
    emit("=" * 92)
    out_path = os.path.join(D, "mnq_mes_meanrevert_vs_standaside.txt")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(OUT))
    print(f"\nSaved -> {out_path}")


if __name__ == "__main__":
    main()
