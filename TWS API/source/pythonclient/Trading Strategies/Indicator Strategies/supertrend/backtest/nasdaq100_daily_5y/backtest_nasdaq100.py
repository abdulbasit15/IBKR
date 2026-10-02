"""Supertrend + 200-DEMA long-only daily backtest over the Nasdaq-100.

Rules (per user):
  * LONG-only.
  * ENTER long when: Supertrend trend is bullish (+1)  AND  close > DEMA(200).
  * EXIT when:        Supertrend flips bearish (-1)     OR   close < DEMA(200).
Indicator math is copied verbatim from Trading Strategies/Indicators (supertrend.py, dema.py,
moving_average.ema) so it matches the live bot. Signals are evaluated on each COMPLETED daily bar
and executed at the NEXT bar's open (no look-ahead). Frictionless (IBKR equity commissions ~ $0).

Params: ATR=10, multiplier=3, DEMA=200 (the live supertrend.json defaults). $10,000 start per stock,
all-in each trade (compounding), so per-stock results are directly comparable.
"""
from __future__ import annotations
import csv, json, os, math

HD = r"C:\Users\abdbasit\Downloads\Personal\Trade\IBKR\TWS API\source\pythonclient\Trading Strategies\Historical Data"
DATA = os.path.join(HD, "Nasdaq100", "data")
OUTDIR = r"C:\Users\abdbasit\Downloads\Personal\Trade\IBKR\TWS API\source\pythonclient\Trading Strategies\Indicator Strategies\supertrend\backtest\nasdaq100_daily_5y"
os.makedirs(OUTDIR, exist_ok=True)

ATR_PERIOD, MULT, DEMA_PERIOD, START_CAP = 10, 3.0, 200, 10000.0

# ---- indicator math (verbatim from Indicators/) ----
def ema(values, period):
    out=[None]*len(values)
    if not values: return out
    k=2.0/(period+1.0); prev=values[0]; out[0]=prev
    for i in range(1,len(values)):
        v=values[i] if values[i] is not None else prev
        prev=v*k+prev*(1-k); out[i]=prev
    return out

def dema(values, period):
    e1=ema(values,period); e2=ema(e1,period)
    out=[None]*len(values)
    for i in range(len(values)):
        if e1[i] is not None and e2[i] is not None:
            out[i]=2.0*e1[i]-e2[i]
    return out

def _rma(values,n):
    out=[None]*len(values)
    if not values: return out
    prev=values[0]; out[0]=prev; a=1.0/n
    for i in range(1,len(values)):
        v=values[i] if values[i] is not None else prev
        prev=prev+a*(v-prev); out[i]=prev
    return out

def _true_range(highs,lows,closes):
    tr=[highs[0]-lows[0]]
    for i in range(1,len(closes)):
        tr.append(max(highs[i]-lows[i],abs(highs[i]-closes[i-1]),abs(lows[i]-closes[i-1])))
    return tr

def supertrend(highs,lows,closes,atr_period=10,mult=3.0):
    n=len(closes); a=_rma(_true_range(highs,lows,closes),atr_period)
    up=[0.0]*n; dn=[0.0]*n; trend=[1]*n; line=[0.0]*n
    for i in range(n):
        hl2=(highs[i]+lows[i])/2.0
        bu=hl2-mult*(a[i] or 0.0); bd=hl2+mult*(a[i] or 0.0)
        if i==0:
            up[i]=bu; dn[i]=bd; trend[i]=1; line[i]=bu; continue
        pc=closes[i-1]
        up[i]=bu if (bu>up[i-1] or pc<up[i-1]) else up[i-1]
        dn[i]=bd if (bd<dn[i-1] or pc>dn[i-1]) else dn[i-1]
        pt=trend[i-1]
        if pt==-1 and closes[i]>dn[i]: trend[i]=1
        elif pt==1 and closes[i]<up[i]: trend[i]=-1
        else: trend[i]=pt
        line[i]=up[i] if trend[i]==1 else dn[i]
    return trend,line

# ---- data ----
def load(sym):
    rows=[]
    with open(os.path.join(DATA,f"{sym}.csv"),newline="") as f:
        for r in csv.DictReader(f):
            rows.append((r["date"],float(r["open"]),float(r["high"]),float(r["low"]),float(r["close"])))
    return rows

def backtest(sym):
    bars=load(sym)
    if len(bars)<DEMA_PERIOD+30: return None
    dates=[b[0] for b in bars]; O=[b[1] for b in bars]; H=[b[2] for b in bars]
    L=[b[3] for b in bars]; C=[b[4] for b in bars]
    trend,_=supertrend(H,L,C,ATR_PERIOD,MULT)
    dma=dema(C,DEMA_PERIOD)

    cash=START_CAP; shares=0.0; entry_px=None; entry_date=None
    trades=[]; equity=[]  # equity curve at each bar close
    warmup=DEMA_PERIOD*2  # DEMA needs ~2x period to settle
    for i in range(len(bars)):
        # mark-to-market equity at close i
        equity.append(cash + shares*C[i])
        if i<warmup or dma[i] is None: continue
        # execute decisions made on bar i at open of i+1
        if i+1>=len(bars): break
        px_next=O[i+1]
        long_ok = trend[i]==1 and C[i]>dma[i]
        exit_sig = trend[i]==-1 or C[i]<dma[i]
        if shares==0.0:
            if long_ok:
                shares=cash/px_next; cash=0.0; entry_px=px_next; entry_date=dates[i+1]
        else:
            if exit_sig:
                cash=shares*px_next; ret=(px_next/entry_px-1.0)
                trades.append({"entry":entry_date,"exit":dates[i+1],"entry_px":entry_px,
                               "exit_px":px_next,"ret":ret})
                shares=0.0; entry_px=None
    # close any open position at last close
    if shares>0.0:
        last=C[-1]; cash=shares*last
        trades.append({"entry":entry_date,"exit":dates[-1],"entry_px":entry_px,
                       "exit_px":last,"ret":last/entry_px-1.0,"open":True})
        shares=0.0
    equity[-1]=cash

    # metrics
    end_eq=cash
    net_ret=end_eq/START_CAP-1.0
    yrs=len(bars)/252.0
    cagr=(end_eq/START_CAP)**(1/yrs)-1 if yrs>0 and end_eq>0 else float('nan')
    wins=[t for t in trades if t["ret"]>0]; losses=[t for t in trades if t["ret"]<=0]
    gp=sum(t["ret"] for t in wins); gl=-sum(t["ret"] for t in losses)
    pf=(gp/gl) if gl>0 else (float('inf') if gp>0 else 0.0)
    win_rate=100.0*len(wins)/len(trades) if trades else 0.0
    # max drawdown on strategy equity curve
    peak=-1e18; mdd=0.0
    for e in equity:
        peak=max(peak,e); dd=(e/peak-1.0) if peak>0 else 0.0; mdd=min(mdd,dd)
    # time in market
    days_in=sum(1 for t in trades for _ in [0])  # placeholder; compute below
    # buy & hold over the traded window (first bar after warmup -> last)
    bh_start=C[warmup] if warmup<len(C) else C[0]
    bh=C[-1]/bh_start-1.0
    avg_win=(sum(t["ret"] for t in wins)/len(wins)*100) if wins else 0.0
    avg_loss=(sum(t["ret"] for t in losses)/len(losses)*100) if losses else 0.0
    # equity curves from the point trading begins (growth of $10k), downsampled for the html
    strat_curve=equity[warmup:] or equity[-1:]
    bh_curve=[START_CAP*C[i]/bh_start for i in range(warmup,len(C))] or [START_CAP]
    curve_dates=dates[warmup:] or dates[-1:]
    def _ds(a,n=120):
        if len(a)<=n: return [round(x,1) for x in a]
        step=(len(a)-1)/(n-1); return [round(a[int(round(k*step))],1) for k in range(n)]
    curves={"strat":_ds(strat_curve),"bh":_ds(bh_curve),
            "d0":curve_dates[0],"d1":curve_dates[-1]}
    return {"symbol":sym,"start":dates[0],"end":dates[-1],"bars":len(bars),
            "trades":len(trades),"win_rate":win_rate,"pf":pf,"net_ret":net_ret*100,
            "cagr":cagr*100,"max_dd":mdd*100,"avg_win":avg_win,"avg_loss":avg_loss,
            "buyhold":bh*100,"end_equity":end_eq,"_trades":trades,"_curves":curves}

def main():
    syms=sorted(f[:-4] for f in os.listdir(DATA) if f.endswith(".csv"))
    results=[]
    all_trades=[]
    curves={}
    for s in syms:
        r=backtest(s)
        if r:
            all_trades.extend({**t,"symbol":s} for t in r.pop("_trades"))
            curves[s]=r.pop("_curves")
            results.append(r)
    results.sort(key=lambda x:x["net_ret"],reverse=True)
    with open(os.path.join(OUTDIR,"equity_curves.json"),"w") as f: json.dump(curves,f)

    # summary csv
    cols=["symbol","start","end","bars","trades","win_rate","pf","net_ret","cagr","max_dd",
          "avg_win","avg_loss","buyhold","end_equity"]
    with open(os.path.join(OUTDIR,"summary.csv"),"w",newline="") as f:
        w=csv.writer(f); w.writerow(cols)
        for r in results:
            w.writerow([r["symbol"],r["start"],r["end"],r["bars"],r["trades"],
                        f'{r["win_rate"]:.1f}',("inf" if r["pf"]==float("inf") else f'{r["pf"]:.2f}'),
                        f'{r["net_ret"]:.1f}',f'{r["cagr"]:.1f}',f'{r["max_dd"]:.1f}',
                        f'{r["avg_win"]:.2f}',f'{r["avg_loss"]:.2f}',f'{r["buyhold"]:.1f}',
                        f'{r["end_equity"]:.0f}'])
    # trades csv
    with open(os.path.join(OUTDIR,"trades.csv"),"w",newline="") as f:
        w=csv.writer(f); w.writerow(["symbol","entry","exit","entry_px","exit_px","ret_pct","open_at_end"])
        for t in all_trades:
            w.writerow([t["symbol"],t["entry"],t["exit"],f'{t["entry_px"]:.2f}',
                        f'{t["exit_px"]:.2f}',f'{t["ret"]*100:.2f}',t.get("open",False)])

    # aggregate
    n=len(results)
    avg_net=sum(r["net_ret"] for r in results)/n
    med_net=sorted(r["net_ret"] for r in results)[n//2]
    avg_bh=sum(r["buyhold"] for r in results)/n
    beat=sum(1 for r in results if r["net_ret"]>r["buyhold"])
    prof=sum(1 for r in results if r["net_ret"]>0)
    tot_trades=sum(r["trades"] for r in results)
    all_win=sum(r["win_rate"]*r["trades"] for r in results)/tot_trades if tot_trades else 0
    agg={"symbols":n,"avg_net_ret":avg_net,"median_net_ret":med_net,"avg_buyhold":avg_bh,
         "beat_buyhold":beat,"profitable":prof,"total_trades":tot_trades,"agg_win_rate":all_win}
    with open(os.path.join(OUTDIR,"aggregate.json"),"w") as f: json.dump(agg,f,indent=2)

    # console report
    print(f"{'SYM':<6}{'net%':>8}{'cagr%':>7}{'B&H%':>8}{'trds':>5}{'win%':>6}{'PF':>6}{'mDD%':>7}  window")
    for r in results:
        pf="inf" if r["pf"]==float("inf") else f'{r["pf"]:.2f}'
        print(f'{r["symbol"]:<6}{r["net_ret"]:>8.1f}{r["cagr"]:>7.1f}{r["buyhold"]:>8.1f}'
              f'{r["trades"]:>5}{r["win_rate"]:>6.1f}{pf:>6}{r["max_dd"]:>7.1f}  {r["start"]}..{r["end"]}')
    print("\n=== AGGREGATE ===")
    print(f"symbols tested        : {n}")
    print(f"avg net return        : {avg_net:.1f}%")
    print(f"median net return     : {med_net:.1f}%")
    print(f"avg buy&hold          : {avg_bh:.1f}%")
    print(f"beat buy&hold         : {beat}/{n}")
    print(f"profitable strategies : {prof}/{n}")
    print(f"total trades          : {tot_trades}")
    print(f"aggregate win rate    : {all_win:.1f}%")
    print(f"\noutputs -> {OUTDIR}")

if __name__=="__main__":
    main()
