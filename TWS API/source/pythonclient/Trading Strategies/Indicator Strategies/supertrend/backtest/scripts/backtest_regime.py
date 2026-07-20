"""Tier-1 regime GATE validation: Choppiness Index + ADX classify TREND vs CHOP, then switch
the momentum filters. long_short, continuous futures (vol>0), DEMA(200) base gate always on.

Regime (hysteresis): flip to TREND when CHOP<38 AND ADX>25; flip to CHOP when CHOP>61; else hold.

Modes compared (all: ST(10,3) + DEMA200 base gate):
  PURE_ST        - never require momentum (raw Supertrend)
  ALL_MOM        - ALWAYS require RSI>50/<50 AND MACD hist agree      (current live config)
  REGIME_FILT    - TREND: no momentum ; CHOP: require RSI+MACD        (gate: tighten in chop)
  REGIME_ASIDE   - TREND: no momentum ; CHOP: take NO new entries     (gate: sit out chop)

Run over FULL continuous history (15m ~1y, 30m ~2y, 1h ~3y = many regimes). MNQ $2/pt, MES $5/pt.
"""
import csv, os, math
from datetime import datetime

D = r"C:\Users\abdbasit\Downloads\Personal\Trade"
ATR_P, ST_MULT = 10, 3.0
DEMA_P = 200
RSI_P = 14
ADX_P, CHOP_P = 14, 14
ADX_TR, CHOP_LO, CHOP_HI = 25.0, 38.0, 61.0
MIN_STOP_PCT = 0.005
WARMUP = 400

SERIES = [
    ("MNQ", 2.0, [("15m", "MNQ_cont_15mins.csv"), ("30m", "MNQ_cont_30mins.csv"), ("1h", "MNQ_cont_1hour.csv")]),
    ("MES", 5.0, [("15m", "MES_cont_15mins.csv"), ("30m", "MES_cont_30mins.csv"), ("1h", "MES_cont_1hour.csv")]),
]
MODES = ["PURE_ST", "ALL_MOM", "REGIME_FILT", "REGIME_ASIDE"]

OUT = []
def emit(s=""):
    print(s); OUT.append(s)


def load(path):
    b = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            v = float(r["volume"] or 0)
            if v <= 0:
                continue
            b.append({"ts": datetime.fromisoformat(r["date"]), "open": float(r["open"]),
                      "high": float(r["high"]), "low": float(r["low"]), "close": float(r["close"])})
    b.sort(key=lambda x: x["ts"]); return b


def _rma(v, n):
    out=[None]*len(v)
    if not v: return out
    p=v[0]; out[0]=p; a=1.0/n
    for i in range(1,len(v)):
        x=v[i] if v[i] is not None else p; p=p+a*(x-p); out[i]=p
    return out

def _ema(v, n):
    out=[None]*len(v)
    if not v: return out
    a=2.0/(n+1.0); p=v[0]; out[0]=p
    for i in range(1,len(v)):
        p=(v[i]-p)*a+p; out[i]=p
    return out

def _dema(v,n):
    e1=_ema(v,n); e2=_ema(e1,n)
    return [(2*e1[i]-e2[i]) if (e1[i] is not None and e2[i] is not None) else None for i in range(len(v))]

def _tr(h,l,c):
    tr=[h[0]-l[0]]
    for i in range(1,len(c)):
        tr.append(max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1])))
    return tr

def supertrend(h,l,c,ap=10,m=3.0):
    n=len(c); a=_rma(_tr(h,l,c),ap)
    up=[0.0]*n; dn=[0.0]*n; tr=[1]*n; line=[0.0]*n
    for i in range(n):
        hl2=(h[i]+l[i])/2.0; bu=hl2-m*(a[i] or 0.0); bd=hl2+m*(a[i] or 0.0)
        if i==0: up[i]=bu; dn[i]=bd; tr[i]=1; line[i]=bu; continue
        pc=c[i-1]
        up[i]=bu if (bu>up[i-1] or pc<up[i-1]) else up[i-1]
        dn[i]=bd if (bd<dn[i-1] or pc>dn[i-1]) else dn[i-1]
        pt=tr[i-1]
        tr[i]=1 if (pt==-1 and c[i]>dn[i]) else (-1 if (pt==1 and c[i]<up[i]) else pt)
        line[i]=up[i] if tr[i]==1 else dn[i]
    return tr,line

def rsi(c,n=14):
    g=[0.0]; ls=[0.0]
    for i in range(1,len(c)):
        d=c[i]-c[i-1]; g.append(max(d,0.0)); ls.append(max(-d,0.0))
    ag=_rma(g,n); al=_rma(ls,n); out=[None]*len(c)
    for i in range(len(c)):
        if al[i] is None: out[i]=None
        elif al[i]==0: out[i]=100.0 if (ag[i] and ag[i]>0) else 50.0
        else: out[i]=100.0-100.0/(1.0+ag[i]/al[i])
    return out

def macd_hist(c,f=12,s=26,sig=9):
    ef=_ema(c,f); es=_ema(c,s); line=[ef[i]-es[i] for i in range(len(c))]; sl=_ema(line,sig)
    return [line[i]-sl[i] for i in range(len(c))]

def adx_series(h,l,c,period=14):
    n=len(c); ax=[None]*n
    if n<period+1: return ax
    tr=[0.0]*n; pdm=[0.0]*n; mdm=[0.0]*n
    for i in range(1,n):
        up=h[i]-h[i-1]; dnm=l[i-1]-l[i]
        pdm[i]=up if (up>dnm and up>0) else 0.0
        mdm[i]=dnm if (dnm>up and dnm>0) else 0.0
        tr[i]=max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1]))
    s_tr=[None]*n; s_p=[None]*n; s_m=[None]*n
    s_tr[period]=sum(tr[1:period+1]); s_p[period]=sum(pdm[1:period+1]); s_m[period]=sum(mdm[1:period+1])
    for i in range(period+1,n):
        s_tr[i]=s_tr[i-1]-s_tr[i-1]/period+tr[i]
        s_p[i]=s_p[i-1]-s_p[i-1]/period+pdm[i]
        s_m[i]=s_m[i-1]-s_m[i-1]/period+mdm[i]
    dx=[None]*n
    for i in range(period,n):
        rng=s_tr[i]
        if rng:
            pdi=100.0*s_p[i]/rng; mdi=100.0*s_m[i]/rng; den=pdi+mdi
            dx[i]=100.0*abs(pdi-mdi)/den if den else 0.0
    first=period*2-1
    if first<n:
        seed=[dx[j] for j in range(period,first+1) if dx[j] is not None]
        if len(seed)==period:
            ax[first]=sum(seed)/period
            for i in range(first+1,n):
                if dx[i] is not None and ax[i-1] is not None:
                    ax[i]=(ax[i-1]*(period-1)+dx[i])/period
    return ax

def choppiness(h,l,c,n=14):
    tr=_tr(h,l,c); out=[None]*len(c); ln=math.log10(n)
    for i in range(len(c)):
        if i<n: continue
        sumtr=sum(tr[i-n+1:i+1]); hh=max(h[i-n+1:i+1]); ll=min(l[i-n+1:i+1]); rng=hh-ll
        if rng>0 and sumtr>0:
            out[i]=100.0*math.log10(sumtr/rng)/ln
    return out

def regimes(adx,chop):
    reg=[None]*len(adx); cur="CHOP"
    for i in range(len(adx)):
        a=adx[i]; ch=chop[i]
        if a is not None and ch is not None:
            if ch<CHOP_LO and a>ADX_TR: cur="TREND"
            elif ch>CHOP_HI: cur="CHOP"
        reg[i]=cur
    return reg


def run(bars, mult, mode):
    n=len(bars)
    h=[b["high"] for b in bars]; l=[b["low"] for b in bars]; c=[b["close"] for b in bars]; o=[b["open"] for b in bars]
    trend,line=supertrend(h,l,c,ATR_P,ST_MULT); bull=[t==1 for t in trend]
    dema=_dema(c,DEMA_P); rs=rsi(c,RSI_P); mh=macd_hist(c)
    adx=adx_series(h,l,c,ADX_P); chop=choppiness(h,l,c,CHOP_P); reg=regimes(adx,chop)
    trades=[]; side=None; entry=stop=0.0
    def close_t(px,why):
        pnl=(px-entry)*mult if side=="LONG" else (entry-px)*mult
        trades.append({"side":side,"pnl":pnl,"why":why})
    def allowed(des,j):
        if dema[j] is None: return False
        if des=="LONG" and not c[j]>dema[j]: return False
        if des=="SHORT" and not c[j]<dema[j]: return False
        r=reg[j]
        need_mom=False; aside=False
        if mode=="ALL_MOM": need_mom=True
        elif mode=="REGIME_FILT": need_mom=(r=="CHOP")
        elif mode=="REGIME_ASIDE": aside=(r=="CHOP")
        if aside: return False
        if need_mom:
            if rs[j] is None or mh[j] is None: return False
            if des=="LONG" and not (rs[j]>50 and mh[j]>0): return False
            if des=="SHORT" and not (rs[j]<50 and mh[j]<0): return False
        return True
    def opn(des,j):
        if not allowed(des,j): return None
        e=o[j+1]; s=(min(line[j],c[j]*(1-MIN_STOP_PCT)) if des=="LONG" else max(line[j],c[j]*(1+MIN_STOP_PCT)))
        if des=="LONG" and s>=e: return None
        if des=="SHORT" and s<=e: return None
        return (des,e,s)
    for j in range(WARMUP,n):
        if side is not None:
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
    # regime exposure
    tr_ct=sum(1 for i in range(WARMUP,n) if reg[i]=="TREND"); tot=n-WARMUP
    return trades, (tr_ct/tot*100 if tot else 0)


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
    emit("Tier-1 REGIME GATE validation — Choppiness+ADX classify TREND/CHOP, switch momentum filters")
    emit(f"long_short, continuous futures, DEMA200 base gate. TREND: CHOP<{CHOP_LO:.0f}&ADX>{ADX_TR:.0f}; CHOP>{CHOP_HI:.0f}. MNQ $2/pt, MES $5/pt.")
    rows=[]
    for sym,mult,tfs in SERIES:
        for tf,fname in tfs:
            bars=load(os.path.join(D,fname))
            period=f"{bars[WARMUP]['ts'].date()}..{bars[-1]['ts'].date()}"
            res={}; trend_pct=0
            for m in MODES:
                t,tp=run(bars,mult,m); res[m]=summ(t); trend_pct=tp
            emit(f"\n{'='*86}")
            emit(f"{sym} {tf}   {len(bars):,} bars   {period}   (regime: {trend_pct:.0f}% TREND / {100-trend_pct:.0f}% CHOP)")
            emit(f"  {'mode':<14}{'Trades':>7}{'Win%':>7}{'PF':>6}{'NetP/L$':>12}{'MaxDD$':>11}")
            for m in MODES:
                r=res[m]
                emit(f"  {m:<14}{r['n']:>7}{r['win']:>7.1f}{r['pf']:>6.2f}{r['net']:>+12,.0f}{r['mdd']:>+11,.0f}")
            best=max(MODES,key=lambda m:res[m]['net'])
            emit(f"  -> best net: {best}  (${res[best]['net']:+,.0f}, PF {res[best]['pf']:.2f})")
            rows.append((f"{sym} {tf}",res,best))
    emit(f"\n{'='*86}")
    emit("SUMMARY — Net P/L $ (PF) by mode")
    emit("-"*86)
    emit(f"{'Series':<9}" + "".join(f"{m:>18}" for m in MODES) + f"{'BEST':>13}")
    emit("-"*86)
    for name,res,best in rows:
        cells="".join(f"{res[m]['net']:>+11,.0f}({res[m]['pf']:>4.2f})"[:18].rjust(18) for m in MODES)
        emit(f"{name:<9}{cells}{best:>13}")
    emit("="*86)
    # scoreboard: how often each mode wins / beats ALL_MOM (current live)
    wins={m:0 for m in MODES}; beat_all=0
    for _,res,best in rows: wins[best]+=1
    for _,res,_ in rows:
        if max(res["REGIME_FILT"]["net"],res["REGIME_ASIDE"]["net"]) > res["ALL_MOM"]["net"]: beat_all+=1
    emit("Best-mode tally: " + ", ".join(f"{m}:{wins[m]}" for m in MODES))
    emit(f"Regime gate beats current ALL_MOM (always RSI+MACD) in {beat_all}/{len(rows)} series.")
    with open(os.path.join(D,"mnq_mes_regime_gate.txt"),"w") as f:
        f.write("\n".join(OUT))
    print("\nSaved -> mnq_mes_regime_gate.txt")


if __name__ == "__main__":
    main()
