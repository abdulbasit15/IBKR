"""Read-only connectivity + scanner + data test against IB Gateway/TWS.

Places NO orders. Works any time of day. Verifies, against your paper gateway:
  1) connection + account equity,
  2) IBKR native market scanner (reqScannerData),
  3) historical bars (reqHistoricalData) - the thing the bots' watchlist scan needs,
  4) (delayed) real-time quotes + session VWAP (tick 233).

Run:  python scanner_test.py
"""
from __future__ import annotations
import asyncio

from ib_async import IB, Stock, ScannerSubscription

PORTS = [4002, 7497, 4001]
PROBES = ["AAPL", "AMD", "NVDA"]


def main():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    ib = IB()
    for port in PORTS:
        try:
            ib.connect("127.0.0.1", port, clientId=88, readonly=True)
            print(f"[OK] connected on port {port}")
            break
        except Exception as e:
            print(f"[..] port {port} failed: {e}")
    else:
        print("[FAIL] could not connect on any port. Is the API enabled and the port right?")
        return

    try:
        # request delayed data so unsubscribed accounts still get something
        ib.reqMarketDataType(3)
        print("[OK] requested delayed market data (type 3)")

        acct = ib.managedAccounts()
        nlv = next((v.value for v in ib.accountValues() if v.tag == "NetLiquidation"), "?")
        print(f"[OK] accounts={acct} NetLiquidation={nlv}")

        # ---- 1) IBKR native scanner ----
        print("\n--- SCANNER (reqScannerData) ---")
        for scan_code in ("TOP_PERC_GAIN", "MOST_ACTIVE", "HOT_BY_VOLUME"):
            try:
                sub = ScannerSubscription(instrument="STK", locationCode="STK.US.MAJOR",
                                          scanCode=scan_code, abovePrice=5)
                rows = ib.reqScannerData(sub)
                syms = [r.contractDetails.contract.symbol for r in rows][:12]
                print(f"  {scan_code:14} -> {len(rows)} hits: {syms}")
            except Exception as e:
                print(f"  {scan_code:14} -> ERROR: {e}")
            ib.sleep(1)

        # ---- 2) historical bars (what the watchlist scan needs) ----
        print("\n--- HISTORICAL DATA (reqHistoricalData 5-min, 1D) ---")
        for sym in PROBES:
            c = Stock(sym, "SMART", "USD")
            try:
                ib.qualifyContracts(c)
                bars = ib.reqHistoricalData(c, "", "1 D", "5 mins", "TRADES", True, 1)
                if bars:
                    print(f"  {sym:5} -> {len(bars)} bars  last_close={bars[-1].close}")
                else:
                    print(f"  {sym:5} -> NO BARS (entitlement/timeout)")
            except Exception as e:
                print(f"  {sym:5} -> ERROR: {e}")
            ib.sleep(0.5)

        # ---- 3) quotes + VWAP (tick 233) ----
        print("\n--- QUOTES (reqMktData '233' -> last / vwap) ---")
        for sym in PROBES:
            c = Stock(sym, "SMART", "USD")
            try:
                ib.qualifyContracts(c)
                tk = ib.reqMktData(c, "233", False, False)
                ib.sleep(3)
                mp = tk.marketPrice()
                vw = getattr(tk, "vwap", None)
                print(f"  {sym:5} -> price={mp} last={tk.last} close={tk.close} vwap={vw}")
                ib.cancelMktData(c)
            except Exception as e:
                print(f"  {sym:5} -> ERROR: {e}")

        print("\n--- VERDICT ---")
        print("  If SCANNER returned hits      -> the IBKR scanner works.")
        print("  If HISTORICAL returned bars   -> watchlist scan will work (bots can run).")
        print("  If HISTORICAL = NO BARS       -> market-data entitlement missing (share live sub).")
        print("  vwap=nan/None on delayed data -> set require_vwap:false for a delayed smoke test.")
    finally:
        ib.disconnect()
        print("\ndisconnected.")


if __name__ == "__main__":
    main()
