"""Partial take-profit (scale-out) overlay vs existing exit logic, on the DEPLOYED strategy
(regime-adaptive: ST(10,3) + DEMA200 + regime stand-aside, long_short). MNQ & MES, all TFs.

EXISTING : full Q position, Supertrend trailing stop, exit ALL on stop-hit or ST flip.
PARTIAL  : same entries/stops UNTIL +2R. R = |entry-initial_stop|. If price reaches entry+/-2R,
           book half = Q//2 at the 2R level; the runner (Q-half) then trails with a 1R stop
           (locks +1R, trails 1R behind close) and still exits on a Supertrend flip. If +2R is
           never reached, behaves exactly like EXISTING.

Q = 10 contracts (so half = 5 actually engages; live config uses 1 contract -> half=0 -> no-op).
Window Nov25-Jul26 (choppy + trending). Continuous futures (vol>0). MNQ $2/pt, MES $5/pt.
"""
import os, sys
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backtest_regime as R

D=R.D; WARM=500; QTY=10
WINDOWS=[("CHOPPY Nov25-Mar26","2025-11-01","2026-04-01"),
         ("TREND  Apr-Jul26","2026-04-01","2026-07-18"),
         ("BOTH   Nov25-Jul26","2025-11-01","2026-07-18")]
SERIES=[("MNQ",2.0,[("15m","MNQ_cont_15mins.csv"),("30m","MNQ_cont_30mins.csv"),("1h","MNQ_cont_1hour.csv")]),
        ("MES",5.0,[("15m","MES_cont_15mins.csv"),("30m","MES_cont_30mins.csv"),("1h","MES_cont_1hour.csv")])]
MODES=["EXISTING","PARTIAL"]
OUT=[]
def emit(s=""):
    print(s); OUT.append(s)
def idx_at(bars,ds):
    dt=datetime.fromisoformat(ds)
    for i,b in enumerate(bars):
        if b["ts"].replace(tzinfo=None)>=dt: return i
    return len(bars)

def run(bars,mult,mode,start_i,qty=QTY):
    n=len(bars)
    h=[b["high"] for b in bars]; l=[b["low"] for b in bars]; c=[b["close"] for b in bars]; o=[b["open"] for b in bars]
    trend,line=R.supertrend(h,l,c,R.ATR_P,R.ST_MULT); bull=[t==1 for t in trend]
    dema=R._dema(c,R.DEMA_P)
    adx=R.adx_series(h,l,c,R.ADX_P); chop=R.choppiness(h,l,c,R.CHOP_P); reg=R.regimes(adx,chop)
    half=qty//2; runner0=qty-half
    trades=[]; trims=0
    side=None; entry=stop=Rr=tp2=0.0; qopen=0; trimmed=False
    def rec(pnl,why,partial=False):
        trades.append({"pnl":pnl,"why":why,"partial":partial})
    def allowed(des,j):  # deployed gate: DEMA + regime stand-aside
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
            # A) stop hit (resting stop during bar j) -> exit remaining open qty
            if side=="LONG" and l[j]<=stop:
                rec((stop-entry)*mult*qopen,"STOP"); side=None; continue
            if side=="SHORT" and h[j]>=stop:
                rec((entry-stop)*mult*qopen,"STOP"); side=None; continue
            # B) partial TP at 2R (only once, PARTIAL mode, half>0, not yet trimmed)
            if mode=="PARTIAL" and not trimmed and half>0:
                if side=="LONG" and h[j]>=tp2:
                    rec((tp2-entry)*mult*half,"TP2",True); trims+=1
                    qopen-=half; trimmed=True
                    stop=max(stop, entry+Rr)          # lock +1R on the runner
                elif side=="SHORT" and l[j]<=tp2:
                    rec((entry-tp2)*mult*half,"TP2",True); trims+=1
                    qopen-=half; trimmed=True
                    stop=min(stop, entry-Rr)
            if j+1>=n: continue
            # C) Supertrend flip -> exit remaining at next open
            des_now="LONG" if bull[j] else "SHORT"
            if des_now!=side:
                ex=o[j+1]
                rec(((ex-entry) if side=="LONG" else (entry-ex))*mult*qopen,"FLIP"); side=None; continue
            # D) trail
            if not trimmed:
                if side=="LONG":
                    ns=min(line[j],c[j]*(1-1e-4));  stop=max(stop,ns)
                else:
                    ns=max(line[j],c[j]*(1+1e-4));  stop=min(stop,ns)
            else:   # runner: 1R trail behind close
                if side=="LONG":
                    ns=c[j]-Rr;  stop=max(stop,ns)
                else:
                    ns=c[j]+Rr;  stop=min(stop,ns)
        else:
            if j+1>=n: continue
            des="LONG" if bull[j] else "SHORT"
            op=opn(des,j)
            if op:
                side,entry,stop=op
                Rr=abs(entry-stop); tp2=(entry+2*Rr) if side=="LONG" else (entry-2*Rr)
                qopen=qty; trimmed=False
    if side is not None:
        rec(((c[-1]-entry) if side=="LONG" else (entry-c[-1]))*mult*qopen,"END")
    return trades, trims

def summ(trades):
    # group by trade is complex (partials split); treat each record as a realized leg for P/L,
    # but count "trades" as entries (STOP/FLIP/END legs); win% on full-trade net is approximated
    # by summing legs per entry. Simpler: report leg-level net + counts.
    if not trades: return {"legs":0,"net":0,"pf":0,"mdd":0,"wins":0,"n":0}
    net=sum(t["pnl"] for t in trades)
    gw=sum(t["pnl"] for t in trades if t["pnl"]>0); gl=abs(sum(t["pnl"] for t in trades if t["pnl"]<=0)) or 1e-9
    eq=[0.0]; acc=0.0
    for t in trades: acc+=t["pnl"]; eq.append(acc)
    peak=eq[0]; mdd=0.0
    for e in eq: peak=max(peak,e); mdd=min(mdd,e-peak)
    # count entries = non-partial exits (STOP/FLIP/END)
    n=sum(1 for t in trades if not t["partial"])
    return {"legs":len(trades),"net":net,"pf":gw/gl,"mdd":mdd,"n":n}

def main():
    emit("PARTIAL take-profit (trim half @2R, runner trails 1R) vs EXISTING exit — regime-adaptive strategy")
    emit(f"long_short, ST(10,3)+DEMA200+regime stand-aside. Q={QTY} contracts (half={QTY//2}). Window Nov25-Jul26.")
    emit("MNQ $2/pt, MES $5/pt. Continuous futures (vol>0).")
    tot={w[0]:{m:0.0 for m in MODES} for w in WINDOWS}
    for sym,mult,tfs in SERIES:
        for tf,fname in tfs:
            bars=R.load(os.path.join(D,fname))
            emit(f"\n{'='*84}\n{sym} {tf}")
            emit(f"  {'phase':<20}{'mode':<10}{'Entries':>8}{'PF':>6}{'NetP/L$':>12}{'MaxDD$':>11}{'trims':>7}")
            for wname,ws,we in WINDOWS:
                si=idx_at(bars,ws); ei=idx_at(bars,we)
                sub=bars[max(0,si-WARM):ei]; start_i=si-max(0,si-WARM)
                for m in MODES:
                    t,tr=run(sub,mult,m,start_i); r=summ(t); tot[wname][m]+=r["net"]
                    emit(f"  {wname:<20}{m:<10}{r['n']:>8}{r['pf']:>6.2f}{r['net']:>+12,.0f}{r['mdd']:>+11,.0f}{tr:>7}")
                emit("")
    emit("="*84)
    emit(f"TOTALS across all 6 series, Q={QTY} (Net P/L $):")
    emit(f"  {'phase':<20}{'EXISTING':>14}{'PARTIAL':>14}{'diff':>12}")
    for wname,_,_ in WINDOWS:
        e=tot[wname]["EXISTING"]; p=tot[wname]["PARTIAL"]
        emit(f"  {wname:<20}{e:>+14,.0f}{p:>+14,.0f}{p-e:>+12,.0f}")
    emit("="*84)
    emit("PF here is leg-level (partial TP counts as a winning leg). Entries = number of positions opened.")
    emit("trims = how many positions reached +2R and scaled out. Stops/TP modeled as exact fills (no slippage).")
    with open(os.path.join(D,"mnq_mes_partial_tp.txt"),"w") as f:
        f.write("\n".join(OUT))
    print("\nSaved -> mnq_mes_partial_tp.txt")

if __name__=="__main__":
    main()
