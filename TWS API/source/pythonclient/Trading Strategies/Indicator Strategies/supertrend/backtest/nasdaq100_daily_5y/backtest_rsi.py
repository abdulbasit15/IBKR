"""RSI mean-reversion long-only daily backtest over the Nasdaq-100.

Rules (per user):
  * LONG-only.
  * ENTER long when RSI(14) < 30 (oversold).
  * EXIT when RSI(14) > 70 (overbought).
RSI math is copied verbatim from Trading Strategies/Indicators/momentum/rsi.py (Wilder, matches
TradingView ta.rsi). Signals on each COMPLETED daily bar, executed at the NEXT bar's open (no
look-ahead). Frictionless. $10,000 start/stock, all-in compounding, so per-stock results compare
directly with the supertrend+DEMA run.
"""
from __future__ import annotations
import csv, json, os

HD = r"C:\Users\abdbasit\Downloads\Personal\Trade\IBKR\TWS API\source\pythonclient\Trading Strategies\Historical Data"
DATA = os.path.join(HD, "Nasdaq100", "data")
OUTDIR = r"C:\Users\abdbasit\Downloads\Personal\Trade\IBKR\TWS API\source\pythonclient\Trading Strategies\Indicator Strategies\supertrend\backtest\nasdaq100_daily_5y"
os.makedirs(OUTDIR, exist_ok=True)

RSI_PERIOD, OVERSOLD, OVERBOUGHT, START_CAP = 14, 30.0, 70.0, 10000.0

# ---- RSI (verbatim from Indicators/momentum/rsi.py) ----
def rsi(closes, period=14):
    period=int(period); n=len(closes); out=[None]*n
    if period<=0 or n<period+1: return out
    gains=[0.0]*n; losses=[0.0]*n
    for i in range(1,n):
        ch=closes[i]-closes[i-1]
        gains[i]=ch if ch>0 else 0.0; losses[i]=-ch if ch<0 else 0.0
    def to_rsi(ag,al):
        if al==0: return 100.0 if ag>0 else 50.0
        rs=ag/al; return 100.0-100.0/(1.0+rs)
    avg_gain=sum(gains[1:period+1])/period; avg_loss=sum(losses[1:period+1])/period
    out[period]=to_rsi(avg_gain,avg_loss); alpha=1.0/period
    for i in range(period+1,n):
        avg_gain=avg_gain+alpha*(gains[i]-avg_gain); avg_loss=avg_loss+alpha*(losses[i]-avg_loss)
        out[i]=to_rsi(avg_gain,avg_loss)
    return out

def load(sym):
    rows=[]
    with open(os.path.join(DATA,f"{sym}.csv"),newline="") as f:
        for r in csv.DictReader(f):
            rows.append((r["date"],float(r["open"]),float(r["high"]),float(r["low"]),float(r["close"])))
    return rows

def backtest(sym):
    bars=load(sym)
    if len(bars)<RSI_PERIOD+30: return None
    dates=[b[0] for b in bars]; O=[b[1] for b in bars]; C=[b[4] for b in bars]
    R=rsi(C,RSI_PERIOD)
    cash=START_CAP; shares=0.0; entry_px=None; entry_date=None
    trades=[]; equity=[]
    warmup=RSI_PERIOD+1
    for i in range(len(bars)):
        equity.append(cash+shares*C[i])
        if i<warmup or R[i] is None: continue
        if i+1>=len(bars): break
        px_next=O[i+1]
        if shares==0.0:
            if R[i]<OVERSOLD:
                shares=cash/px_next; cash=0.0; entry_px=px_next; entry_date=dates[i+1]
        else:
            if R[i]>OVERBOUGHT:
                cash=shares*px_next
                trades.append({"entry":entry_date,"exit":dates[i+1],"entry_px":entry_px,
                               "exit_px":px_next,"ret":px_next/entry_px-1.0})
                shares=0.0; entry_px=None
    if shares>0.0:
        last=C[-1]; cash=shares*last
        trades.append({"entry":entry_date,"exit":dates[-1],"entry_px":entry_px,
                       "exit_px":last,"ret":last/entry_px-1.0,"open":True})
        shares=0.0
    equity[-1]=cash

    end_eq=cash; net_ret=end_eq/START_CAP-1.0; yrs=len(bars)/252.0
    cagr=(end_eq/START_CAP)**(1/yrs)-1 if yrs>0 and end_eq>0 else float('nan')
    wins=[t for t in trades if t["ret"]>0]; losses=[t for t in trades if t["ret"]<=0]
    gp=sum(t["ret"] for t in wins); gl=-sum(t["ret"] for t in losses)
    pf=(gp/gl) if gl>0 else (float('inf') if gp>0 else 0.0)
    win_rate=100.0*len(wins)/len(trades) if trades else 0.0
    peak=-1e18; mdd=0.0
    for e in equity:
        peak=max(peak,e); dd=(e/peak-1.0) if peak>0 else 0.0; mdd=min(mdd,dd)
    bh_start=C[warmup] if warmup<len(C) else C[0]; bh=C[-1]/bh_start-1.0
    avg_win=(sum(t["ret"] for t in wins)/len(wins)*100) if wins else 0.0
    avg_loss=(sum(t["ret"] for t in losses)/len(losses)*100) if losses else 0.0
    strat_curve=equity[warmup:] or equity[-1:]
    bh_curve=[START_CAP*C[i]/bh_start for i in range(warmup,len(C))] or [START_CAP]
    def _ds(a,n=120):
        if len(a)<=n: return [round(x,1) for x in a]
        step=(len(a)-1)/(n-1); return [round(a[int(round(k*step))],1) for k in range(n)]
    curves={"strat":_ds(strat_curve),"bh":_ds(bh_curve)}
    return {"symbol":sym,"start":dates[0],"end":dates[-1],"bars":len(bars),
            "trades":len(trades),"win_rate":win_rate,"pf":pf,"net_ret":net_ret*100,
            "cagr":cagr*100,"max_dd":mdd*100,"avg_win":avg_win,"avg_loss":avg_loss,
            "buyhold":bh*100,"end_equity":end_eq,"_trades":trades,"_curves":curves}

def main():
    syms=sorted(f[:-4] for f in os.listdir(DATA) if f.endswith(".csv"))
    results=[]; all_trades=[]; curves={}
    for s in syms:
        r=backtest(s)
        if r:
            all_trades.extend({**t,"symbol":s} for t in r.pop("_trades"))
            curves[s]=r.pop("_curves"); results.append(r)
    results.sort(key=lambda x:x["net_ret"],reverse=True)
    with open(os.path.join(OUTDIR,"equity_curves_rsi.json"),"w") as f: json.dump(curves,f)

    cols=["symbol","start","end","bars","trades","win_rate","pf","net_ret","cagr","max_dd",
          "avg_win","avg_loss","buyhold","end_equity"]
    with open(os.path.join(OUTDIR,"summary_rsi.csv"),"w",newline="") as f:
        w=csv.writer(f); w.writerow(cols)
        for r in results:
            w.writerow([r["symbol"],r["start"],r["end"],r["bars"],r["trades"],
                        f'{r["win_rate"]:.1f}',("inf" if r["pf"]==float("inf") else f'{r["pf"]:.2f}'),
                        f'{r["net_ret"]:.1f}',f'{r["cagr"]:.1f}',f'{r["max_dd"]:.1f}',
                        f'{r["avg_win"]:.2f}',f'{r["avg_loss"]:.2f}',f'{r["buyhold"]:.1f}',
                        f'{r["end_equity"]:.0f}'])
    with open(os.path.join(OUTDIR,"trades_rsi.csv"),"w",newline="") as f:
        w=csv.writer(f); w.writerow(["symbol","entry","exit","entry_px","exit_px","ret_pct","open_at_end"])
        for t in all_trades:
            w.writerow([t["symbol"],t["entry"],t["exit"],f'{t["entry_px"]:.2f}',
                        f'{t["exit_px"]:.2f}',f'{t["ret"]*100:.2f}',t.get("open",False)])

    n=len(results); avg_net=sum(r["net_ret"] for r in results)/n
    med_net=sorted(r["net_ret"] for r in results)[n//2]
    avg_bh=sum(r["buyhold"] for r in results)/n
    beat=sum(1 for r in results if r["net_ret"]>r["buyhold"])
    prof=sum(1 for r in results if r["net_ret"]>0)
    tot_trades=sum(r["trades"] for r in results)
    all_win=sum(r["win_rate"]*r["trades"] for r in results)/tot_trades if tot_trades else 0
    agg={"symbols":n,"avg_net_ret":avg_net,"median_net_ret":med_net,"avg_buyhold":avg_bh,
         "beat_buyhold":beat,"profitable":prof,"total_trades":tot_trades,"agg_win_rate":all_win}
    with open(os.path.join(OUTDIR,"aggregate_rsi.json"),"w") as f: json.dump(agg,f,indent=2)
    print(f"RSI(14) <30 buy / >70 sell  |  symbols {n}  avg_net {avg_net:.1f}%  median {med_net:.1f}%  "
          f"profitable {prof}/{n}  beat_bh {beat}/{n}  trades {tot_trades}  win {all_win:.1f}%")

if __name__=="__main__":
    main()
