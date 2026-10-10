"""Download 5-min RTH (useRTH=True, TRADES) bars for liquid stocks/ETFs from IB Gateway, in 1-year chunks.
Output: ../../Historical Data/data/equity_rth/{SYM}_5m_rth.csv  (date UTC, open, high, low, close, volume)

  python download_stocks_5m_rth.py --years 2 --client-id 65 SPY QQQ AAPL
"""
import argparse
import csv
import os
import time
from datetime import datetime, timedelta, timezone
from ib_async import IB, Stock

OUT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "Historical Data", "data", "equity_rth"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("symbols", nargs="+")
    ap.add_argument("--years", type=int, default=2)
    ap.add_argument("--client-id", type=int, default=65)
    ap.add_argument("--port", type=int, default=4002)
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    ib = IB()
    ib.connect("127.0.0.1", a.port, clientId=a.client_id, timeout=20)
    for sym in a.symbols:
        c = Stock(sym, "SMART", "USD", primaryExchange="ARCA" if sym in ("SPY", "IWM", "DIA") else "")
        if not ib.qualifyContracts(c):
            print(sym, "did not qualify", flush=True)
            continue
        rows = {}
        end = ""
        for k in range(a.years):
            t = time.time()
            bars = ib.reqHistoricalData(c, end, "1 Y", "5 mins", "TRADES", True, 2, timeout=300) or []
            for b in bars:
                rows[b.date] = (b.open, b.high, b.low, b.close, b.volume)
            print(f"{sym} chunk {k + 1}/{a.years}: {len(bars)} bars "
                  f"{bars[0].date if bars else '-'} .. {bars[-1].date if bars else '-'} ({time.time() - t:.0f}s)", flush=True)
            if not bars:
                break
            end = (bars[0].date - timedelta(minutes=5)).astimezone(timezone.utc).strftime("%Y%m%d-%H:%M:%S")
            time.sleep(2)
        path = os.path.join(OUT, f"{sym}_5m_rth.csv")
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["date", "open", "high", "low", "close", "volume"])
            for d in sorted(rows):
                w.writerow([d.isoformat(), *rows[d]])
        print(f"{sym}: {len(rows)} bars -> {path}", flush=True)
    ib.disconnect()


if __name__ == "__main__":
    main()
