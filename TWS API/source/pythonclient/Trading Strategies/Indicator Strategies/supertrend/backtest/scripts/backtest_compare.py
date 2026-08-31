"""Compare ONLY-SUPERTREND vs the REGIME-ADAPTIVE strategy over a period that contains BOTH a
choppy phase (Nov 2025-Mar 2026) and a trending phase (Apr-Jul 2026). long_short, continuous
futures (vol>0), 1 contract. Reports each phase separately + combined so you can see behavior
in each regime. Indicators warm on ~500 bars before each window; trades counted inside it.

Strategies:
  ONLY_ST   - raw Supertrend long_short (no DEMA, no momentum, no regime) — the baseline
  REGIME    - Supertrend + regime gate (stand-aside in chop)  [isolates the regime effect]
  LIVE      - Supertrend + DEMA200 base gate + regime gate (stand-aside) [as deployed]
"""
import os, sys
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backtest_regime as R   # reuse identical indicator math + regime classifier

D = R.D
WARM = 500
WINDOWS = [
    ("CHOPPY  Nov25-Mar26", "2025-11-01", "2026-04-01"),
    ("TREND   Apr-Jul26",   "2026-04-01", "2026-07-18"),
    ("COMBINED Nov25-Jul26","2025-11-01", "2026-07-18"),
]
SERIES = [
    ("MNQ", 2.0, [("15m","MNQ_cont_15mins.csv"),("30m","MNQ_cont_30mins.csv"),("1h","MNQ_cont_1hour.csv")]),
    ("MES", 5.0, [("15m","MES_cont_15mins.csv"),("30m","MES_cont_30mins.csv"),("1h","MES_cont_1hour.csv")]),
]
OUT=[]
def emit(s=""):
    print(s); OUT.append(s)


def idx_at(bars, ds):
    dt=datetime.fromisoformat(ds)
    for i,b in enumerate(bars):
        if b["ts"].replace(tzinfo=None) >= dt: return i
    return len(bars)


def run(bars, mult, strat, start_i):
    """strat in {ONLY_ST, REGIME, LIVE}. Trades from start_i..end. Regime warmed on prior bars."""
    n=len(bars)
    h=[b["high"] for b in bars]; l=[b["low"] for b in bars]; c=[b["close"] for b in bars]; o=[b["open"] for b in bars]
    trend,line=R.supertrend(h,l,c,R.ATR_P,R.ST_MULT); bull=[t==1 for t in trend]
    dema=R._dema(c,R.DEMA_P)
    adx=R.adx_series(h,l,c,R.ADX_P); chop=R.choppiness(h,l,c,R.CHOP_P); reg=R.regimes(adx,chop)
    use_dema = (strat=="LIVE")
    use_regime = (strat in ("REGIME","LIVE"))
    trades=[]; side=None; entry=stop=0.0; exp=0
    def close_t(px,why):
        pnl=(px-entry)*mult if side=="LONG" else (entry-px)*mult
        trades.append({"side":side,"pnl":pnl,"why":why})
    def allowed(des,j):
        if use_dema:
            if dema[j] is None: return False
            if des=="LONG" and not c[j]>dema[j]: return False
            if des=="SHORT" and not c[j]<dema[j]: return False
        if use_regime and reg[j]=="CHOP":
            return False   # stand aside in chop
        return True
    def opn(des,j):
        if not allowed(des,j): return None
        e=o[j+1]; s=(min(line[j],c[j]*(1-R.MIN_STOP_PCT)) if des=="LONG" else max(line[j],c[j]*(1+R.MIN_STOP_PCT)))
        if des=="LONG" and s>=e: return None
        if des=="SHORT" and s<=e: return None
        return (des,e,s)
    for j in range(start_i,n):
        if side is not None:
            exp+=1
            if side=="LONG" and l[j]<=stop: close_t(stop,"STOP"); side=None
            elif side=="SHORT" and h[j]>=stop: close_t(stop,"STOP"); side=None
        if j+1>=n: continue
        des="LONG" if bull[j] else "SHORT"
        if side is not None and des!=side:
            close_t(o[j+1],"FLIP"); side=None
            op=opn(des,j)
            if op: side,entry,stop=op
        elif side is None:
            op=opn(des,j)
            if op: side,entry,stop=op
        else:
            if side=="LONG":
                ns=min(line[j],c[j]*(1-1e-4))
                if ns>stop: stop=ns
            else:
                ns=max(line[j],c[j]*(1+1e-4))
                if ns<stop: stop=ns
    if side is not None: close_t(c[-1],"END")
    tot=n-start_i; trend_pct=sum(1 for i in range(start_i,n) if reg[i]=="TREND")/tot*100 if tot else 0
    return trades, trend_pct


def summ(trades):
    if not trades: return {"n":0,"win":0,"pf":0,"net":0,"mdd":0}
    n=len(trades); wins=[t for t in trades if t["pnl"]>0]; loss=[t for t in trades if t["pnl"]<=0]
    gw=sum(t["pnl"] for t in wins); gl=abs(sum(t["pnl"] for t in loss)) or 1e-9
    net=sum(t["pnl"] for t in trades); eq=[0.0]; acc=0.0
    for t in trades: acc+=t["pnl"]; eq.append(acc)
    peak=eq[0]; mdd=0.0
    for e in eq: peak=max(peak,e); mdd=min(mdd,e-peak)
    return {"n":n,"win":len(wins)/n*100,"pf":gw/gl,"net":net,"mdd":mdd}


def main():
    emit("ONLY-SUPERTREND vs REGIME-ADAPTIVE — period with BOTH choppy & trending phases")
    emit("long_short, continuous futures, 1 contract. ONLY_ST=raw ST | REGIME=ST+regime stand-aside | LIVE=ST+DEMA+regime")
    emit(f"Regime: TREND when CHOP<{R.CHOP_LO:.0f} & ADX>{R.ADX_TR:.0f}; CHOP when CHOP>{R.CHOP_HI:.0f}. MNQ $2/pt, MES $5/pt.")
    STRATS=["ONLY_ST","REGIME","LIVE"]
    combo_tot={s:0.0 for s in STRATS}
    for sym,mult,tfs in SERIES:
        for tf,fname in tfs:
            bars=R.load(os.path.join(D,fname))
            emit(f"\n{'='*90}\n{sym} {tf}   ({len(bars):,} bars)")
            emit(f"  {'phase':<22}{'strategy':<10}{'Trades':>7}{'Win%':>7}{'PF':>6}{'NetP/L$':>11}{'MaxDD$':>10}{'%TREND':>8}")
            for wname,ws,we in WINDOWS:
                si=idx_at(bars,ws); ei=idx_at(bars,we)
                sub=bars[max(0,si-WARM):ei]; start_i=si-max(0,si-WARM)
                for strat in STRATS:
                    t,tp=run(sub,mult,strat,start_i); r=summ(t)
                    if wname.startswith("COMBINED"): combo_tot[strat]+=r["net"]
                    emit(f"  {wname:<22}{strat:<10}{r['n']:>7}{r['win']:>7.1f}{r['pf']:>6.2f}"
                         f"{r['net']:>+11,.0f}{r['mdd']:>+10,.0f}{tp:>7.0f}%")
                emit("")
    emit("="*90)
    emit("COMBINED-window totals across all 6 series (Net P/L $):")
    for s in STRATS:
        emit(f"  {s:<10} {combo_tot[s]:>+12,.0f}")
    emit("="*90)
    emit("REGIME/LIVE stand aside in chop (fewer trades, smaller DD); ONLY_ST trades everything.")
    emit("Stops modeled filling at the trailed Supertrend level (no slippage/gaps).")
    with open(os.path.join(D,"mnq_mes_regime_vs_supertrend.txt"),"w") as f:
        f.write("\n".join(OUT))
    print("\nSaved -> mnq_mes_regime_vs_supertrend.txt")


if __name__=="__main__":
    main()
