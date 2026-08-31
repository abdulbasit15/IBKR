"""Multi-tranche scale-out analysis vs existing exit, on the deployed regime-adaptive strategy
(ST(10,3)+DEMA200+regime stand-aside, long_short). MNQ & MES, all TFs, both-phase window.

A tranche = (fraction_of_Q, R_multiple). Each fires once when price reaches entry +/- Rmult*R
(a limit take-profit). Before the FIRST trim the position uses the Supertrend trailing stop
(existing). After the first trim the REMAINDER trails with a 1R stop (locks profit; each fired
tranche bumps the stop to target-1R) and still exits on a Supertrend flip. Runner = whatever
fraction is left after all tranches (trails 1R indefinitely). R = |entry - initial stop|.

Q=12 (25%=3, 33%=4, 50%=6). Continuous futures (vol>0). MNQ $2/pt, MES $5/pt.
"""
import os, sys
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backtest_regime as R

D=R.D; WARM=500; QTY=12
WIN=("BOTH Nov25-Jul26","2025-11-01","2026-07-18")
CHOP=("CHOPPY","2025-11-01","2026-04-01"); TREND=("TREND","2026-04-01","2026-07-18")
SERIES=[("MNQ",2.0,[("15m","MNQ_cont_15mins.csv"),("30m","MNQ_cont_30mins.csv"),("1h","MNQ_cont_1hour.csv")]),
        ("MES",5.0,[("15m","MES_cont_15mins.csv"),("30m","MES_cont_30mins.csv"),("1h","MES_cont_1hour.csv")])]
# scheme -> list of (fraction, R multiple). [] = existing (no scale-out).
SCHEMES = {
    "EXISTING":       [],
    "50@2R":          [(0.50,2)],
    "25/25/25@1,2,3": [(0.25,1),(0.25,2),(0.25,3)],
    "33/33@2,3":      [(1/3,2),(1/3,3)],
    "25x4@1,2,3,4":   [(0.25,1),(0.25,2),(0.25,3),(0.25,4)],
}
OUT=[]
def emit(s=""):
    print(s); OUT.append(s)
def idx_at(bars,ds):
    dt=datetime.fromisoformat(ds)
    for i,b in enumerate(bars):
        if b["ts"].replace(tzinfo=None)>=dt: return i
    return len(bars)

def tranche_qty(scheme, q):
    """Return list of (qty_i, Rmult_i) with sum<=q; runner=q-sum."""
    out=[]; used=0
    for frac,rm in scheme:
        qi=int(round(frac*q))
        qi=max(0,min(qi, q-used))
        if qi>0: out.append((qi,rm)); used+=qi
    return out, q-used   # tranches, runner

def run(bars,mult,scheme,start_i,q=QTY):
    n=len(bars)
    h=[b["high"] for b in bars]; l=[b["low"] for b in bars]; c=[b["close"] for b in bars]; o=[b["open"] for b in bars]
    trend,line=R.supertrend(h,l,c,R.ATR_P,R.ST_MULT); bull=[t==1 for t in trend]
    dema=R._dema(c,R.DEMA_P); adx=R.adx_series(h,l,c,R.ADX_P); chop=R.choppiness(h,l,c,R.CHOP_P); reg=R.regimes(adx,chop)
    tr_spec,_=tranche_qty(scheme,q)   # (qty, Rmult) list, ascending assumed
    trades=[]; trims=0
    side=None; entry=stop=Rr=0.0; qopen=0; tidx=0; trimmed=False; pend=[]
    def rec(pnl,partial=False): trades.append({"pnl":pnl,"partial":partial})
    def allowed(des,j):
        if dema[j] is None: return False
        if des=="LONG" and not c[j]>dema[j]: return False
        if des=="SHORT" and not c[j]<dema[j]: return False
        if reg[j]=="CHOP": return False
        return True
    def opn(des,j):
        if not allowed(des,j): return None
        e=o[j+1]; s=(min(line[j],c[j]*(1-R.MIN_STOP_PCT)) if des=="LONG" else max(line[j],c[j]*(1+R.MIN_STOP_PCT)))
        if des=="LONG" and s>=e: return None
        if des=="SHORT" and s<=e: return None
        return (des,e,s)
    for j in range(start_i,n):
        if side is not None:
            # A) stop hit -> exit all remaining
            if side=="LONG" and l[j]<=stop:
                rec((stop-entry)*mult*qopen); side=None; continue
            if side=="SHORT" and h[j]>=stop:
                rec((entry-stop)*mult*qopen); side=None; continue
            # B) fire tranches reached this bar (in order)
            while tidx<len(pend) and qopen>0:
                qi,rm=pend[tidx]
                tgt=entry+rm*Rr if side=="LONG" else entry-rm*Rr
                hit=(h[j]>=tgt) if side=="LONG" else (l[j]<=tgt)
                if not hit: break
                qi=min(qi,qopen)
                rec((tgt-entry)*mult*qi if side=="LONG" else (entry-tgt)*mult*qi, True)
                qopen-=qi; tidx+=1; trims+=1; trimmed=True
                lock=(tgt-Rr) if side=="LONG" else (tgt+Rr)
                stop=max(stop,lock) if side=="LONG" else min(stop,lock)
            if qopen<=0: side=None; continue
            if j+1>=n: continue
            # C) flip -> exit remainder next open
            des_now="LONG" if bull[j] else "SHORT"
            if des_now!=side:
                ex=o[j+1]; rec(((ex-entry) if side=="LONG" else (entry-ex))*mult*qopen); side=None; continue
            # D) trail: Supertrend until first trim, then 1R
            if not trimmed:
                if side=="LONG": stop=max(stop,min(line[j],c[j]*(1-1e-4)))
                else: stop=min(stop,max(line[j],c[j]*(1+1e-4)))
            else:
                if side=="LONG": stop=max(stop,c[j]-Rr)
                else: stop=min(stop,c[j]+Rr)
        else:
            if j+1>=n: continue
            des="LONG" if bull[j] else "SHORT"
            op=opn(des,j)
            if op:
                side,entry,stop=op; Rr=abs(entry-stop); qopen=q
                pend=list(tr_spec); tidx=0; trimmed=False
    if side is not None:
        rec(((c[-1]-entry) if side=="LONG" else (entry-c[-1]))*mult*qopen)
    return trades,trims

def summ(trades):
    if not trades: return {"net":0,"pf":0,"mdd":0,"n":0}
    net=sum(t["pnl"] for t in trades)
    gw=sum(t["pnl"] for t in trades if t["pnl"]>0); gl=abs(sum(t["pnl"] for t in trades if t["pnl"]<=0)) or 1e-9
    eq=[0.0]; acc=0.0
    for t in trades: acc+=t["pnl"]; eq.append(acc)
    peak=eq[0]; mdd=0.0
    for e in eq: peak=max(peak,e); mdd=min(mdd,e-peak)
    n=sum(1 for t in trades if not t["partial"])
    return {"net":net,"pf":gw/gl,"mdd":mdd,"n":n}

def bt(bars,mult,scheme,ws,we):
    si=idx_at(bars,ws); ei=idx_at(bars,we)
    sub=bars[max(0,si-WARM):ei]; start_i=si-max(0,si-WARM)
    t,tr=run(sub,mult,scheme,start_i); r=summ(t); r["trims"]=tr; return r

def main():
    emit("MULTI-TRANCHE SCALE-OUT analysis — regime-adaptive strategy, long_short, Q=12")
    emit("Each tranche = limit TP at entry+/-(Rmult*R); after 1st trim the remainder trails 1R. Window Nov25-Jul26.")
    names=list(SCHEMES)
    grand={s:{"chop":0.0,"trend":0.0,"both":0.0,"dd":0.0} for s in names}
    for sym,mult,tfs in SERIES:
        for tf,fname in tfs:
            bars=R.load(os.path.join(D,fname))
            emit(f"\n{'='*96}\n{sym} {tf}   (BOTH window)")
            emit(f"  {'scheme':<18}{'Entries':>8}{'PF':>6}{'NetP/L$':>12}{'MaxDD$':>11}{'trims':>7}")
            for s in names:
                r=bt(bars,mult,SCHEMES[s],WIN[1],WIN[2])
                grand[s]["both"]+=r["net"]; grand[s]["dd"]+=r["mdd"]
                emit(f"  {s:<18}{r['n']:>8}{r['pf']:>6.2f}{r['net']:>+12,.0f}{r['mdd']:>+11,.0f}{r['trims']:>7}")
            # phase split (net only)
            emit(f"  {'--- phase net ---':<18}")
            for s in names:
                rc=bt(bars,mult,SCHEMES[s],CHOP[1],CHOP[2]); rt=bt(bars,mult,SCHEMES[s],TREND[1],TREND[2])
                grand[s]["chop"]+=rc["net"]; grand[s]["trend"]+=rt["net"]
                emit(f"  {s:<18}{'':>8}{'':>6}{'chop '+format(rc['net'],'+,.0f'):>18}{'  trend '+format(rt['net'],'+,.0f')}")
    emit("\n"+"="*96)
    emit("TOTALS across all 6 series (Net P/L $), Q=12:")
    emit(f"  {'scheme':<18}{'CHOPPY':>13}{'TREND':>13}{'BOTH':>13}{'sum MaxDD$':>13}")
    for s in names:
        g=grand[s]
        emit(f"  {s:<18}{g['chop']:>+13,.0f}{g['trend']:>+13,.0f}{g['both']:>+13,.0f}{g['dd']:>+13,.0f}")
    emit("="*96)
    emit("BOTH beats EXISTING? & drawdown (sum of per-series MaxDD, less negative = better):")
    base=grand["EXISTING"]
    for s in names:
        if s=="EXISTING": continue
        g=grand[s]
        emit(f"  {s:<18} both diff {g['both']-base['both']:>+11,.0f}   dd diff {g['dd']-base['dd']:>+11,.0f}")
    emit("="*96)
    emit("PF is leg-level (each trim = a winning leg). Compare on Net P/L + MaxDD. Exact fills (no slippage).")
    with open(os.path.join(D,"mnq_mes_tranche_scaleout.txt"),"w") as f:
        f.write("\n".join(OUT))
    print("\nSaved -> mnq_mes_tranche_scaleout.txt")

if __name__=="__main__":
    main()
