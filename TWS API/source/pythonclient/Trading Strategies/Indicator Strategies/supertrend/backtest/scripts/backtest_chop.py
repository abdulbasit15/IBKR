"""Supertrend + RSI / MACD momentum filters — CHOPPY window vs TRENDING window.
MNQ & MES, 15m/30m/1h, long_short, continuous futures (vol>0 filtered), 1 contract.

Filters gate entries (incl. the reverse leg of a flip), momentum must AGREE with the
Supertrend direction:
  RSI(14): LONG needs RSI>50, SHORT needs RSI<50
  MACD(12,26,9): LONG needs hist>0 (macd>signal), SHORT needs hist<0
Combos: NONE / +RSI / +MACD / +RSI+MACD.

Indicators warm up on ~500 bars before each window; trades counted only inside the window.
ST(10,3), 24H, stop=Supertrend line trailed (min_stop 0.5%). MNQ $2/pt, MES $5/pt.
"""
import csv, os
from datetime import datetime

D = r"C:\Users\abdbasit\Downloads\Personal\Trade"
START_CAPITAL = 100_000.0
ATR_PERIOD, MULT_ST = 10, 3.0
MIN_STOP_PCT = 0.005
WARMUP = 500
COMMISSION_RT = 1.04

WINDOWS = [
    ("CHOPPY (Nov25-Mar26)", "2025-11-01", "2026-04-01"),
    ("TREND (Apr-Jul26)",     "2026-04-01", "2026-07-18"),
]
SERIES = [
    ("MNQ", 2.0, [("15m", "MNQ_cont_15mins.csv"), ("30m", "MNQ_cont_30mins.csv"), ("1h", "MNQ_cont_1hour.csv")]),
    ("MES", 5.0, [("15m", "MES_cont_15mins.csv"), ("30m", "MES_cont_30mins.csv"), ("1h", "MES_cont_1hour.csv")]),
]
COMBOS = [("NONE", False, False), ("+RSI", True, False), ("+MACD", False, True), ("+RSI+MACD", True, True)]

OUT = []
def emit(s=""):
    print(s); OUT.append(s)


def load(path):
    bars = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            v = float(r["volume"] or 0)
            if v <= 0:
                continue
            bars.append({"ts": datetime.fromisoformat(r["date"]), "open": float(r["open"]),
                         "high": float(r["high"]), "low": float(r["low"]), "close": float(r["close"])})
    bars.sort(key=lambda b: b["ts"]); return bars


def _rma(v, n):
    out = [None]*len(v)
    if not v: return out
    prev = v[0]; out[0] = prev; a = 1.0/n
    for i in range(1, len(v)):
        x = v[i] if v[i] is not None else prev
        prev = prev + a*(x-prev); out[i] = prev
    return out

def _ema(v, n):
    out = [None]*len(v)
    if not v: return out
    a = 2.0/(n+1.0); prev = v[0]; out[0] = prev
    for i in range(1, len(v)):
        prev = (v[i]-prev)*a + prev; out[i] = prev
    return out

def _tr(h, l, c):
    tr = [h[0]-l[0]]
    for i in range(1, len(c)):
        tr.append(max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1])))
    return tr

def supertrend(h, l, c, ap=10, m=3.0):
    n = len(c); a = _rma(_tr(h, l, c), ap)
    up = [0.0]*n; dn = [0.0]*n; tr = [1]*n; line = [0.0]*n
    for i in range(n):
        hl2 = (h[i]+l[i])/2.0; bu = hl2 - m*(a[i] or 0.0); bd = hl2 + m*(a[i] or 0.0)
        if i == 0:
            up[i]=bu; dn[i]=bd; tr[i]=1; line[i]=bu; continue
        pc = c[i-1]
        up[i] = bu if (bu>up[i-1] or pc<up[i-1]) else up[i-1]
        dn[i] = bd if (bd<dn[i-1] or pc>dn[i-1]) else dn[i-1]
        pt = tr[i-1]
        tr[i] = 1 if (pt==-1 and c[i]>dn[i]) else (-1 if (pt==1 and c[i]<up[i]) else pt)
        line[i] = up[i] if tr[i]==1 else dn[i]
    return tr, line

def rsi(c, n=14):
    gains=[0.0]; losses=[0.0]
    for i in range(1, len(c)):
        d = c[i]-c[i-1]; gains.append(max(d,0.0)); losses.append(max(-d,0.0))
    ag=_rma(gains,n); al=_rma(losses,n); out=[None]*len(c)
    for i in range(len(c)):
        if al[i] is None: out[i]=None
        elif al[i]==0: out[i]=100.0 if (ag[i] and ag[i]>0) else 50.0
        else:
            rs=ag[i]/al[i]; out[i]=100.0-100.0/(1.0+rs)
    return out

def macd_hist(c, fast=12, slow=26, sig=9):
    ef=_ema(c,fast); es=_ema(c,slow)
    line=[ef[i]-es[i] for i in range(len(c))]
    s=_ema(line,sig)
    return [line[i]-s[i] for i in range(len(c))]


def resolve_stop(side, ref, line):
    return min(line, ref*(1-MIN_STOP_PCT)) if side=="LONG" else max(line, ref*(1+MIN_STOP_PCT))


def run(bars, mult, start_i, use_rsi, use_macd):
    """Trade from index start_i (window start; indicators warmed on prior bars)."""
    n=len(bars)
    h=[b["high"] for b in bars]; l=[b["low"] for b in bars]; c=[b["close"] for b in bars]
    o=[b["open"] for b in bars]
    trend,line = supertrend(h,l,c,ATR_PERIOD,MULT_ST); bull=[t==1 for t in trend]
    rs = rsi(c,14) if use_rsi else None
    mh = macd_hist(c) if use_macd else None
    trades=[]; side=None; entry=stop=0.0
    def close_t(px, why):
        pnl=(px-entry)*mult if side=="LONG" else (entry-px)*mult
        trades.append({"side":side,"pnl":pnl,"why":why})
    def ok(des, j):
        if use_rsi:
            if rs[j] is None: return False
            if des=="LONG" and not rs[j]>50: return False
            if des=="SHORT" and not rs[j]<50: return False
        if use_macd:
            if mh[j] is None: return False
            if des=="LONG" and not mh[j]>0: return False
            if des=="SHORT" and not mh[j]<0: return False
        return True
    def opn(des, j):
        if not ok(des,j): return None
        e=o[j+1]; s=resolve_stop(des,c[j],line[j])
        if des=="LONG" and s>=e: return None
        if des=="SHORT" and s<=e: return None
        return (des,e,s)
    for j in range(start_i, n):
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
                ns=min(line[j], c[j]*(1-1e-4))
                if ns>stop: stop=ns
            else:
                ns=max(line[j], c[j]*(1+1e-4))
                if ns<stop: stop=ns
    if side is not None: close_t(c[-1],"END")
    return trades


def summ(trades):
    if not trades:
        return {"n":0,"win":0,"pf":0,"net":0,"mdd":0,"nl":0,"ns":0,"lp":0,"sp":0}
    n=len(trades); wins=[t for t in trades if t["pnl"]>0]; loss=[t for t in trades if t["pnl"]<=0]
    gw=sum(t["pnl"] for t in wins); gl=abs(sum(t["pnl"] for t in loss)) or 1e-9
    net=sum(t["pnl"] for t in trades)
    eq=[0.0]; acc=0.0
    for t in trades: acc+=t["pnl"]; eq.append(acc)
    peak=eq[0]; mdd=0.0
    for e in eq:
        peak=max(peak,e); mdd=min(mdd, e-peak)
    lo=[t for t in trades if t["side"]=="LONG"]; sh=[t for t in trades if t["side"]=="SHORT"]
    return {"n":n,"win":len(wins)/n*100,"pf":gw/gl,"net":net,"mdd":mdd,
            "nl":len(lo),"ns":len(sh),"lp":sum(t["pnl"] for t in lo),"sp":sum(t["pnl"] for t in sh)}


def idx_at(bars, datestr):
    dt=datetime.fromisoformat(datestr)
    for i,b in enumerate(bars):
        if b["ts"].replace(tzinfo=None) >= dt:
            return i
    return len(bars)


def main():
    emit("Supertrend + RSI / MACD momentum filters — long_short, CHOPPY vs TREND window")
    emit("Continuous futures (vol>0). ST(10,3), 24H, 1 contract. RSI>50/<50, MACD hist>0/<0 agree with ST.")
    grand=[]
    for wname, wstart, wend in WINDOWS:
        emit("\n" + "#"*94)
        emit(f"# WINDOW: {wname}   {wstart} -> {wend}")
        emit("#"*94)
        for sym, mult, tfs in SERIES:
            for tf, fname in tfs:
                bars=load(os.path.join(D,fname))
                si=idx_at(bars,wstart); ei=idx_at(bars,wend)
                if si < WARMUP:
                    si2 = si  # not enough warmup; use available
                # slice so warmup precedes window; trade from window start to window end
                sub=bars[max(0,si-WARMUP):ei]
                start_i = min(WARMUP, si)  # index within sub where window begins
                # recompute exact start index within sub
                start_i = si - max(0, si-WARMUP)
                res={}
                for cn,ur,um in COMBOS:
                    t=run(sub, mult, start_i, ur, um); res[cn]=summ(t)
                wtag = "CHOP" if wname.startswith("CHOP") else "TREND"
                emit(f"\n{sym} {tf}  [{wtag}]  window bars={ei-si}  ({bars[si]['ts'].date()}..{bars[min(ei,len(bars)-1)]['ts'].date()})")
                emit(f"  {'combo':<11}{'Trades':>7}{'Win%':>7}{'PF':>6}{'NetP/L$':>11}{'MaxDD$':>10}{'long/short':>12}")
                for cn,_,_ in COMBOS:
                    r=res[cn]
                    emit(f"  {cn:<11}{r['n']:>7}{r['win']:>7.1f}{r['pf']:>6.2f}{r['net']:>+11,.0f}"
                         f"{r['mdd']:>+10,.0f}{(str(r['nl'])+'/'+str(r['ns'])):>12}")
                best=max(COMBOS,key=lambda cc:res[cc[0]]['net'])
                grand.append((wtag,f"{sym} {tf}",res,best[0]))

    emit("\n" + "="*94)
    emit("SUMMARY — best filter by window  (Net P/L $, PF)")
    emit("-"*94)
    emit(f"{'Window':<7}{'Series':<9}" + "".join(f"{cn:>18}" for cn,_,_ in COMBOS) + f"{'BEST':>11}")
    emit("-"*94)
    for wtag,name,res,best in grand:
        cells="".join(f"{res[cn]['net']:>+11,.0f}({res[cn]['pf']:>4.2f})"[:18].rjust(18) for cn,_,_ in COMBOS)
        emit(f"{wtag:<7}{name:<9}{cells}{best:>11}")
    emit("="*94)
    emit("Filters gate entries; momentum must agree with Supertrend direction. MaxDD in $ (trade equity).")
    with open(os.path.join(D,"mnq_mes_rsi_macd_chop_vs_trend.txt"),"w") as f:
        f.write("\n".join(OUT))
    print("\nSaved -> mnq_mes_rsi_macd_chop_vs_trend.txt")


if __name__ == "__main__":
    main()
