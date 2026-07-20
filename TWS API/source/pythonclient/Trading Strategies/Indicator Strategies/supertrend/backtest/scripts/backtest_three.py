"""3-way compare: ST vs ST+DEMA vs REGIME (ST+DEMA+regime gate), long_short.
Period with BOTH choppy (Nov25-Mar26) and trending (Apr-Jul26) phases. All timeframes, MNQ&MES.
Continuous futures (vol>0), 1 contract. Each layer adds one thing so you see its contribution.

  ST      = raw Supertrend long_short (no filters)
  ST+DEMA = + DEMA(200) trend gate (long only close>DEMA, short only close<DEMA)
  REGIME  = + regime gate on top (Choppiness+ADX): stand aside in CHOP, trade in TREND
"""
import os, sys
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backtest_regime as R

D = R.D
WARM = 500
WINDOWS = [("CHOPPY Nov25-Mar26","2025-11-01","2026-04-01"),
           ("TREND  Apr-Jul26","2026-04-01","2026-07-18"),
           ("BOTH   Nov25-Jul26","2025-11-01","2026-07-18")]
SERIES = [("MNQ",2.0,[("15m","MNQ_cont_15mins.csv"),("30m","MNQ_cont_30mins.csv"),("1h","MNQ_cont_1hour.csv")]),
          ("MES",5.0,[("15m","MES_cont_15mins.csv"),("30m","MES_cont_30mins.csv"),("1h","MES_cont_1hour.csv")])]
STRATS = ["ST","ST+DEMA","REGIME"]
OUT=[]
def emit(s=""):
    print(s); OUT.append(s)

def idx_at(bars,ds):
    dt=datetime.fromisoformat(ds)
    for i,b in enumerate(bars):
        if b["ts"].replace(tzinfo=None)>=dt: return i
    return len(bars)

def run(bars,mult,strat,start_i):
    n=len(bars)
    h=[b["high"] for b in bars]; l=[b["low"] for b in bars]; c=[b["close"] for b in bars]; o=[b["open"] for b in bars]
    trend,line=R.supertrend(h,l,c,R.ATR_P,R.ST_MULT); bull=[t==1 for t in trend]
    dema=R._dema(c,R.DEMA_P)
    adx=R.adx_series(h,l,c,R.ADX_P); chop=R.choppiness(h,l,c,R.CHOP_P); reg=R.regimes(adx,chop)
    use_dema = strat in ("ST+DEMA","REGIME")
    use_regime = strat=="REGIME"
    trades=[]; side=None; entry=stop=0.0
    def close_t(px):
        pnl=(px-entry)*mult if side=="LONG" else (entry-px)*mult
        trades.append(pnl)
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
            if side=="LONG" and l[j]<=stop: close_t(stop); side=None
            elif side=="SHORT" and h[j]>=stop: close_t(stop); side=None
        if j+1>=n: continue
        des="LONG" if bull[j] else "SHORT"
        if side is not None and des!=side:
            close_t(o[j+1]); side=None
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
    if side is not None: close_t(c[-1])
    return trades

def summ(t):
    if not t: return {"n":0,"win":0,"pf":0,"net":0,"mdd":0}
    n=len(t); wins=[x for x in t if x>0]; gw=sum(wins); gl=abs(sum(x for x in t if x<=0)) or 1e-9
    eq=[0.0]; acc=0.0
    for x in t: acc+=x; eq.append(acc)
    peak=eq[0]; mdd=0.0
    for e in eq: peak=max(peak,e); mdd=min(mdd,e-peak)
    return {"n":n,"win":len(wins)/n*100,"pf":gw/gl,"net":sum(t),"mdd":mdd}

def main():
    emit("3-WAY: ST vs ST+DEMA vs REGIME  (long_short, continuous futures, 1 contract)")
    emit("Period Nov 2025-Jul 2026 = choppy phase (Nov-Mar) + trending/reversal phase (Apr-Jul). MNQ $2/pt, MES $5/pt.")
    tot={w[0]:{s:0.0 for s in STRATS} for w in WINDOWS}
    for sym,mult,tfs in SERIES:
        for tf,fname in tfs:
            bars=R.load(os.path.join(D,fname))
            emit(f"\n{'='*84}\n{sym} {tf}")
            emit(f"  {'phase':<20}{'strat':<9}{'Trd':>5}{'Win%':>7}{'PF':>6}{'NetP/L$':>11}{'MaxDD$':>10}")
            for wname,ws,we in WINDOWS:
                si=idx_at(bars,ws); ei=idx_at(bars,we)
                sub=bars[max(0,si-WARM):ei]; start_i=si-max(0,si-WARM)
                for s in STRATS:
                    r=summ(run(sub,mult,s,start_i)); tot[wname][s]+=r["net"]
                    emit(f"  {wname:<20}{s:<9}{r['n']:>5}{r['win']:>7.1f}{r['pf']:>6.2f}{r['net']:>+11,.0f}{r['mdd']:>+10,.0f}")
                emit("")
    emit("="*84)
    emit("TOTALS across all 6 series (Net P/L $):")
    emit(f"  {'phase':<20}" + "".join(f"{s:>12}" for s in STRATS))
    for wname,_,_ in WINDOWS:
        emit(f"  {wname:<20}" + "".join(f"{tot[wname][s]:>+12,.0f}" for s in STRATS))
    emit("="*84)
    with open(os.path.join(D,"mnq_mes_st_dema_regime.txt"),"w") as f:
        f.write("\n".join(OUT))
    print("\nSaved -> mnq_mes_st_dema_regime.txt")

if __name__=="__main__":
    main()
