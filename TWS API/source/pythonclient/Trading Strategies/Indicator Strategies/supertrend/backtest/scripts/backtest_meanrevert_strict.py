"""STRICTER mean-reversion fade in CHOP — salvage attempt for the tier-2 feature.

The plain tier-2 fade (backtest_meanrevert.py) lost because its dominant exit was 'regime flip to
TREND' — it kept fading ranges that were already breaking out. The trading literature says a band
fade only works in a CONFIRMED, FLAT range with room on the stop. This tests that guidance:

  gates added on top of the CHOP regime before a fade is allowed
    - DEEP chop      : Choppiness[j] >= chop_min   (genuine chop, not the hysteresis hold-zone)
    - NO trend build : ADX[j] <= adx_max
    - FLAT bands     : Bollinger bandwidth[j] <= rolling median (bands not expanding = no vol breakout)
    - EXTREME entry  : stricter %B and RSI
    - WIDER stop     : stop_atr_mult raised so normal noise doesn't stop us at the band

Compared (all long_short, continuous futures vol>0, 1 contract, ST(10,3)+DEMA(200)+regime base):
  ST+DEMA+REG     - stand aside in chop (deployed baseline)
  +MR(orig)       - the plain tier-2 fade (reproduces backtest_meanrevert.py)
  +MR(strict1)    - deep-chop + low-ADX + flat-band + wider stop
  +MR(strict2)    - even stricter (deeper chop, lower ADX, more extreme entry, widest stop)

Period Nov25-Jul26 (choppy + trending). MNQ $2/pt, MES $5/pt.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backtest_regime as R
import backtest_meanrevert as M

D = R.D
WARM = M.WARM
WINDOWS = M.WINDOWS
SERIES = M.SERIES

# gate configs. chop_min=0 / adx_max=999 / flat=False / stop=1.0 / pb=0.05 / rsi 30-70 == original tier-2
VARIANTS = {
    "+MR(orig)":     dict(chop_min=0.0,  adx_max=999.0, flat=False, bww=50, entry_pb=0.05, rsi_os=30, rsi_ob=70, stop_atr=1.0, max_hold=12),
    "+MR(chop45)":   dict(chop_min=45.0, adx_max=999.0, flat=False, bww=50, entry_pb=0.05, rsi_os=30, rsi_ob=70, stop_atr=1.5, max_hold=12),
    "+MR(chop50)":   dict(chop_min=50.0, adx_max=30.0,  flat=False, bww=50, entry_pb=0.05, rsi_os=30, rsi_ob=70, stop_atr=1.5, max_hold=12),
    "+MR(chop55w)":  dict(chop_min=55.0, adx_max=28.0,  flat=False, bww=50, entry_pb=0.05, rsi_os=32, rsi_ob=68, stop_atr=2.0, max_hold=10),
}
COLS = ["ST+DEMA+REG"] + list(VARIANTS.keys())

OUT = []
def emit(s=""):
    print(s); OUT.append(s)


def roll_median_le(series, i, w):
    """True if series[i] <= median of the last w non-None values ending at i (bands not expanding)."""
    vals = [series[k] for k in range(max(0, i - w + 1), i + 1) if series[k] is not None]
    if len(vals) < max(5, w // 2) or series[i] is None:
        return False
    s = sorted(vals); n = len(s)
    med = s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2
    return series[i] <= med


def run_strict(bars, mult, start_i, cfg):
    n = len(bars)
    h = [b["high"] for b in bars]; l = [b["low"] for b in bars]; c = [b["close"] for b in bars]; o = [b["open"] for b in bars]
    trend, line = R.supertrend(h, l, c, R.ATR_P, R.ST_MULT); bull = [t == 1 for t in trend]
    dema = R._dema(c, R.DEMA_P)
    adx = R.adx_series(h, l, c, R.ADX_P); chop = R.choppiness(h, l, c, R.CHOP_P); reg = R.regimes(adx, chop)
    rs = R.rsi(c, R.RSI_P)
    basis, upper, lower, pb = M.bollinger(c, M.BB_LEN, M.BB_MULT)
    bw = [((upper[i] - lower[i]) / basis[i]) if (basis[i] and upper[i] is not None) else None for i in range(n)]

    CHOP_MIN, ADX_MAX, FLAT, BWW = cfg["chop_min"], cfg["adx_max"], cfg["flat"], cfg["bww"]
    E_PB, R_OS, R_OB, STOP_ATR, MAX_HOLD = cfg["entry_pb"], cfg["rsi_os"], cfg["rsi_ob"], cfg["stop_atr"], cfg["max_hold"]
    atrv = R._rma(R._tr(h, l, c), M.MR_ATR_P)

    trades = []; side = None; kind = None; entry = stop = target = 0.0; j0 = 0
    def close_t(px, why):
        trades.append({"pnl": (px - entry) * mult if side == "LONG" else (entry - px) * mult, "why": why})

    def opn_trend(des, j):
        if dema[j] is None: return None
        if des == "LONG" and not c[j] > dema[j]: return None
        if des == "SHORT" and not c[j] < dema[j]: return None
        e = o[j + 1]; s = (min(line[j], c[j] * (1 - R.MIN_STOP_PCT)) if des == "LONG" else max(line[j], c[j] * (1 + R.MIN_STOP_PCT)))
        if des == "LONG" and s >= e: return None
        if des == "SHORT" and s <= e: return None
        return (des, e, s)

    def opn_mr(j):
        # strict gates: deep chop, no trend strength, flat bands
        if chop[j] is None or chop[j] < CHOP_MIN: return None
        if adx[j] is not None and adx[j] > ADX_MAX: return None
        if FLAT and not roll_median_le(bw, j, BWW): return None
        if pb[j] is None or rs[j] is None: return None
        des = None
        if pb[j] <= E_PB and (rs[j] <= R_OS): des = "LONG"
        elif pb[j] >= (1.0 - E_PB) and (rs[j] >= R_OB): des = "SHORT"
        if des is None: return None
        if atrv[j] is None or lower[j] is None or upper[j] is None or basis[j] is None: return None
        e = o[j + 1]
        if des == "LONG":
            s = min(lower[j] - STOP_ATR * atrv[j], c[j] * (1 - R.MIN_STOP_PCT))
            if basis[j] <= c[j] or s >= e: return None
        else:
            s = max(upper[j] + STOP_ATR * atrv[j], c[j] * (1 + R.MIN_STOP_PCT))
            if basis[j] >= c[j] or s <= e: return None
        return (des, e, s, basis[j], j)

    for j in range(start_i, n):
        if side is not None:
            if side == "LONG" and l[j] <= stop:
                close_t(stop, "MR_STOP" if kind == "MR" else "STOP"); side = kind = None
            elif side == "SHORT" and h[j] >= stop:
                close_t(stop, "MR_STOP" if kind == "MR" else "STOP"); side = kind = None
        if j + 1 >= n: continue
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
            continue
        des = "LONG" if bull[j] else "SHORT"
        if side is not None and des != side:
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
        else:
            if side == "LONG":
                ns = min(line[j], c[j] * (1 - 1e-4))
                if ns > stop: stop = ns
            else:
                ns = max(line[j], c[j] * (1 + 1e-4))
                if ns < stop: stop = ns
    if side is not None:
        close_t(c[-1], "END")
    return trades


def main():
    emit("STRICTER MEAN-REVERT FADE in CHOP — salvage test (long_short, continuous futures, 1 contract)")
    emit("Gates: deep chop (CHOP>=min), low ADX, flat bands (bw<=rolling median), extreme %B/RSI, wider stop.")
    emit("Baseline = stand-aside (deployed). Period Nov25-Jul26. MNQ $2/pt, MES $5/pt.")
    tot = {w[0]: {s: 0.0 for s in COLS} for w in WINDOWS}
    ntr = {w[0]: {s: 0 for s in COLS} for w in WINDOWS}
    for sym, mult, tfs in SERIES:
        for tf, fname in tfs:
            bars = R.load(os.path.join(D, fname))
            emit(f"\n{'='*100}\n{sym} {tf}")
            emit(f"  {'phase':<20}{'strategy':<14}{'Trd':>5}{'Win%':>7}{'PF':>6}{'NetP/L$':>11}{'MaxDD$':>10}   mr-exits")
            for wname, ws, we in WINDOWS:
                si = M.idx_at(bars, ws); ei = M.idx_at(bars, we)
                sub = bars[max(0, si - WARM):ei]; start_i = si - max(0, si - WARM)
                for s in COLS:
                    if s == "ST+DEMA+REG":
                        raw = M.run_baseline(sub, mult, s, start_i)
                    else:
                        raw = run_strict(sub, mult, start_i, VARIANTS[s])
                    r = M.summ(raw); tot[wname][s] += r["net"]; ntr[wname][s] += r["n"]
                    rx = M.reasons(raw)
                    rxs = " ".join(f"{k.split('_')[1].lower()}:{v}" for k, v in sorted(rx.items()) if k.startswith("MR")) if s != "ST+DEMA+REG" else ""
                    emit(f"  {wname:<20}{s:<14}{r['n']:>5}{r['win']:>7.1f}{r['pf']:>6.2f}{r['net']:>+11,.0f}{r['mdd']:>+10,.0f}   {rxs}")
                emit("")
    emit("=" * 100)
    emit("TOTALS across all 6 series - Net P/L $ (chop-fade trade count in parens for the +MR columns):")
    emit(f"  {'phase':<20}" + "".join(f"{s:>16}" for s in COLS))
    for wname, _, _ in WINDOWS:
        emit(f"  {wname:<20}" + "".join(f"{tot[wname][s]:>+16,.0f}" for s in COLS))
    emit("=" * 100)
    out_path = os.path.join(D, "mnq_mes_meanrevert_strict.txt")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(OUT))
    print(f"\nSaved -> {out_path}")


if __name__ == "__main__":
    main()
