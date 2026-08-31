"""SOXL evolution backtest (equity, mult=1, Q=100 shares), reusing the same engine as the
MNQ/MES real backtest. PLAIN_ST | PREVIOUS(ST+DEMA+regime) | CURRENT(+partial_tp 50%@2R),
long_short. Data = existing SOXL RTH CSVs (2023-12..2026-06-18; fresh pull blocked by IB
error 162 data-line contention). FULL history + calendar sub-windows.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backtest_regime as R
import backtest_final as F

D=R.D; MULT=1.0; QTY=100
SERIES=[("15m","SOXL_15mins_2y.csv"),("30m","SOXL_30mins_2y.csv"),("1h","SOXL_1hour_2y.csv")]
OUT=[]
def emit(s=""):
    print(s); OUT.append(s)
def bt(bars,mode,ws,we):
    si=F.idx_at(bars,ws); ei=F.idx_at(bars,we) if we else len(bars)
    sub=bars[max(0,si-F.WARM):ei]; start_i=si-max(0,si-F.WARM)
    t,tr=F.run(sub,MULT,mode,start_i,q=QTY); r=F.summ(t); r["trims"]=tr; return r

def main():
    emit("SOXL evolution backtest — long_short, equity, Q=100 shares (mult=1)")
    emit("PLAIN_ST | PREVIOUS(ST+DEMA+regime stand-aside) | CURRENT(+partial_tp 50%@2R). SOXL RTH data.")
    tot={m:0.0 for m in F.MODES}
    for tf,fname in SERIES:
        bars=R.load(os.path.join(D,fname))
        emit(f"\n{'='*80}\nSOXL {tf}   FULL {bars[F.WARM]['ts'].date()}..{bars[-1]['ts'].date()}  ({len(bars):,} bars)")
        emit(f"  {'mode':<10}{'Entries':>8}{'PF':>6}{'NetP/L$':>12}{'MaxDD$':>11}{'trims':>7}")
        for m in F.MODES:
            r=bt(bars,m,None,None); tot[m]+=r["net"]
            emit(f"  {m:<10}{r['n']:>8}{r['pf']:>6.2f}{r['net']:>+12,.0f}{r['mdd']:>+11,.0f}{r['trims']:>7}")
        for label,ws,we in [("  Nov25-Mar26","2025-11-01","2026-04-01"),("  Apr-Jun26","2026-04-01","2026-06-19")]:
            cells=[f"{m[:4]} {bt(bars,m,ws,we)['net']:+,.0f}" for m in F.MODES]
            emit(f"{label:<14} " + " | ".join(cells))
    emit(f"\n{'='*80}")
    emit("SOXL TOTALS across 15m+30m+1h (Net P/L $, Q=100 shares):")
    for m in F.MODES: emit(f"  {m:<10}{tot[m]:>+14,.0f}")
    emit(f"  CURRENT vs PREVIOUS: {tot['CURRENT']-tot['PREVIOUS']:+,.0f}")
    emit(f"  PREVIOUS vs PLAIN_ST: {tot['PREVIOUS']-tot['PLAIN_ST']:+,.0f}")
    emit("="*80)
    with open(os.path.join(D,"soxl_real_backtest_evolution.txt"),"w") as f:
        f.write("\n".join(OUT))
    print("\nSaved -> soxl_real_backtest_evolution.txt")

if __name__=="__main__":
    main()
