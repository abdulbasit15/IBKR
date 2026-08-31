"""REAL backtest on freshly-pulled IB data (continuous futures through 2026-07-20).
Compare the bot's evolution, long_short, deployed size Q=4:
  PLAIN_ST  = raw Supertrend (no DEMA/regime/partial)          -- original strategy
  PREVIOUS  = ST + DEMA200 + regime gate (stand-aside)         -- prior deployed bot
  CURRENT   = PREVIOUS + partial_tp 50%@2R (runner trails 1R)  -- now deployed
MNQ & MES, 15m/30m/1h. Full available history + choppy/trend phase split. MNQ $2/pt, MES $5/pt.
"""
import os, sys
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backtest_regime as R

D=R.D; WARM=500; QTY=4
SERIES=[("MNQ",2.0,[("15m","MNQ_cont_15mins.csv"),("30m","MNQ_cont_30mins.csv"),("1h","MNQ_cont_1hour.csv")]),
        ("MES",5.0,[("15m","MES_cont_15mins.csv"),("30m","MES_cont_30mins.csv"),("1h","MES_cont_1hour.csv")])]
MODES=["PLAIN_ST","PREVIOUS","CURRENT"]
OUT=[]
def emit(s=""):
    print(s); OUT.append(s)
def idx_at(bars,ds):
    if ds is None: return WARM
    dt=datetime.fromisoformat(ds)
    for i,b in enumerate(bars):
        if b["ts"].replace(tzinfo=None)>=dt: return i
    return len(bars)

def run(bars,mult,mode,start_i,q=QTY):
    n=len(bars)
    h=[b["high"] for b in bars]; l=[b["low"] for b in bars]; c=[b["close"] for b in bars]; o=[b["open"] for b in bars]
    trend,line=R.supertrend(h,l,c,R.ATR_P,R.ST_MULT); bull=[t==1 for t in trend]
    dema=R._dema(c,R.DEMA_P); adx=R.adx_series(h,l,c,R.ADX_P); chop=R.choppiness(h,l,c,R.CHOP_P); reg=R.regimes(adx,chop)
    use_dema = mode in ("PREVIOUS","CURRENT")
    use_regime = mode in ("PREVIOUS","CURRENT")
    use_partial = mode=="CURRENT"
    half=q//2
    trades=[]; trims=0
    side=None; entry=stop=Rr=tp2=0.0; qopen=0; trimmed=False
    def rec(pnl,partial=False): trades.append({"pnl":pnl,"partial":partial})
    def allowed(des,j):
        if use_dema:
            if dema[j] is None: return False
            if des=="LONG" and not c[j]>dema[j]: return False
            if des=="SHORT" and not c[j]<dema[j]: return False
        if use_regime and reg[j]=="CHOP": return False
        return True
    def opn(des,j):
        if not allowed(des,j): return None
        e=o[j+1]; s=(min(line[j],c[j]*(1-R.MIN_STOP_PCT)) if des=="LONG" else max(line[j],c[j]*(1+R.MIN_STOP_PCT)))
        if des=="LONG" and s>=e: return None
        if des=="SHORT" and s<=e: return None
        return (des,e,s)
    for j in range(start_i,n):
        if side is not None:
            # stop
            if side=="LONG" and l[j]<=stop: rec((stop-entry)*mult*qopen); side=None; continue
            if side=="SHORT" and h[j]>=stop: rec((entry-stop)*mult*qopen); side=None; continue
            # partial TP @2R (once)
            if use_partial and not trimmed and half>0:
                if side=="LONG" and h[j]>=tp2:
                    rec((tp2-entry)*mult*half,True); trims+=1; qopen-=half; trimmed=True; stop=max(stop,entry+Rr)
                elif side=="SHORT" and l[j]<=tp2:
                    rec((entry-tp2)*mult*half,True); trims+=1; qopen-=half; trimmed=True; stop=min(stop,entry-Rr)
            if qopen<=0: side=None; continue
            if j+1>=n: continue
            des_now="LONG" if bull[j] else "SHORT"
            if des_now!=side:
                ex=o[j+1]; rec(((ex-entry) if side=="LONG" else (entry-ex))*mult*qopen); side=None; continue
            # trail
            if trimmed:
                if side=="LONG": stop=max(stop,c[j]-Rr)
                else: stop=min(stop,c[j]+Rr)
            else:
                if side=="LONG": stop=max(stop,min(line[j],c[j]*(1-1e-4)))
                else: stop=min(stop,max(line[j],c[j]*(1+1e-4)))
        else:
            if j+1>=n: continue
            des="LONG" if bull[j] else "SHORT"
            op=opn(des,j)
            if op:
                side,entry,stop=op; Rr=abs(entry-stop); tp2=(entry+2*Rr) if side=="LONG" else (entry-2*Rr)
                qopen=q; trimmed=False
    if side is not None:
        rec(((c[-1]-entry) if side=="LONG" else (entry-c[-1]))*mult*qopen)
    return trades,trims

def summ(t):
    if not t: return {"net":0,"pf":0,"mdd":0,"n":0}
    net=sum(x["pnl"] for x in t); gw=sum(x["pnl"] for x in t if x["pnl"]>0); gl=abs(sum(x["pnl"] for x in t if x["pnl"]<=0)) or 1e-9
    eq=[0.0]; acc=0.0
    for x in t: acc+=x["pnl"]; eq.append(acc)
    peak=eq[0]; mdd=0.0
    for e in eq: peak=max(peak,e); mdd=min(mdd,e-peak)
    n=sum(1 for x in t if not x["partial"])
    return {"net":net,"pf":gw/gl,"mdd":mdd,"n":n}

def bt(bars,mult,mode,ws,we):
    si=idx_at(bars,ws); ei=idx_at(bars,we) if we else len(bars)
    sub=bars[max(0,si-WARM):ei]; start_i=si-max(0,si-WARM)
    t,tr=run(sub,mult,mode,start_i); r=summ(t); r["trims"]=tr; return r

def main():
    emit("REAL BACKTEST (fresh IB data thru 2026-07-20) — bot evolution, long_short, Q=4")
    emit("PLAIN_ST | PREVIOUS(ST+DEMA+regime) | CURRENT(+partial_tp 50%@2R). MNQ $2/pt, MES $5/pt.")
    tot={m:0.0 for m in MODES}
    for sym,mult,tfs in SERIES:
        for tf,fname in tfs:
            bars=R.load(os.path.join(D,fname))
            span=f"{bars[WARM]['ts'].date()}..{bars[-1]['ts'].date()}"
            emit(f"\n{'='*82}\n{sym} {tf}   FULL history {span}  ({len(bars):,} bars)")
            emit(f"  {'mode':<10}{'Entries':>8}{'PF':>6}{'NetP/L$':>12}{'MaxDD$':>11}{'trims':>7}")
            for m in MODES:
                r=bt(bars,mult,m,None,None)
                if tf=="15m": tot[m]+=r["net"]
                emit(f"  {m:<10}{r['n']:>8}{r['pf']:>6.2f}{r['net']:>+12,.0f}{r['mdd']:>+11,.0f}{r['trims']:>7}")
            # phase split (net only) for context
            for label,ws,we in [("  choppy Nov25-Mar26","2025-11-01","2026-04-01"),("  trend  Apr-Jul26","2026-04-01","2026-07-21")]:
                cells=[]
                for m in MODES:
                    r=bt(bars,mult,m,ws,we); cells.append(f"{m[:4]} {r['net']:+,.0f}")
                emit(f"{label:<20} " + " | ".join(cells))
    emit(f"\n{'='*82}")
    emit("DEPLOYED 15m TOTALS (MNQ+MES, Q=4), Net P/L $:")
    for m in MODES:
        emit(f"  {m:<10}{tot[m]:>+14,.0f}")
    emit(f"  CURRENT vs PREVIOUS: {tot['CURRENT']-tot['PREVIOUS']:+,.0f}")
    emit(f"  PREVIOUS vs PLAIN_ST: {tot['PREVIOUS']-tot['PLAIN_ST']:+,.0f}")
    emit("="*82)
    with open(os.path.join(D,"mnq_mes_real_backtest_evolution.txt"),"w") as f:
        f.write("\n".join(OUT))
    print("\nSaved -> mnq_mes_real_backtest_evolution.txt")

if __name__=="__main__":
    main()
