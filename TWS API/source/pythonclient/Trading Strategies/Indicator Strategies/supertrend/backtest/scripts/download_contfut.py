"""Download CONTINUOUS futures (back-adjusted) for MNQ & MES from IB Gateway (port 4002).
Continuous series give years of liquid history (incl. choppy periods), unlike a single
far-dated contract. 24H (useRTH=False), TRADES. Writes MNQ_cont_<slug>.csv / MES_cont_<slug>.csv.
"""
import csv, time
from datetime import datetime, timedelta, timezone
from ib_async import IB, ContFuture

HOST, PORT, CLIENT_ID = "127.0.0.1", 4002, 91
OUT_DIR = r"C:\Users\abdbasit\Downloads\Personal\Trade"
# continuous futures: NO endDateTime allowed -> one request per bar size, big duration.
# Try progressively smaller durations until IBKR returns data (it caps by bar size).
PLAN = {
    "15 mins": (["1 Y", "6 M", "3 M"], "15mins"),
    "30 mins": (["2 Y", "1 Y", "6 M"], "30mins"),
    "1 hour":  (["3 Y", "2 Y", "1 Y"], "1hour"),
}
SYMS = [("MNQ", "CME"), ("MES", "CME")]


def fetch_single(ib, contract, bar_size, durations):
    for dur in durations:
        try:
            bars = ib.reqHistoricalData(contract, endDateTime="", durationStr=dur,
                barSizeSetting=bar_size, whatToShow="TRADES", useRTH=False,
                formatDate=1, timeout=300) or []
        except Exception as e:
            print(f"  duration {dur} error: {e}"); time.sleep(3); continue
        if bars:
            print(f"  duration {dur}: {len(bars)} bars")
            return bars
        print(f"  duration {dur}: no data, trying smaller")
        time.sleep(2)
    return []


def save(bars, sym, slug):
    path = rf"{OUT_DIR}\{sym}_cont_{slug}.csv"
    with open(path, "w", newline="") as f:
        w = csv.writer(f); w.writerow(["date", "open", "high", "low", "close", "volume"])
        for b in bars:
            w.writerow([b.date, b.open, b.high, b.low, b.close, b.volume])
    print(f"  -> {path} ({len(bars)} bars, {bars[0].date} .. {bars[-1].date})")


def main():
    ib = IB(); ib.connect(HOST, PORT, clientId=CLIENT_ID); ib.reqMarketDataType(3)
    # Wait for the HMDS (historical data) farm to connect, else the first requests return empty.
    print("waiting for HMDS data farm...")
    for _ in range(15):
        ib.sleep(1)
    for sym, exch in SYMS:
        c = ContFuture(symbol=sym, exchange=exch, currency="USD")
        ib.qualifyContracts(c)
        # throwaway warm-up pull so the farm is definitely serving before the big requests
        try:
            ib.reqHistoricalData(c, endDateTime="", durationStr="2 D", barSizeSetting="15 mins",
                                 whatToShow="TRADES", useRTH=False, formatDate=1, timeout=30)
        except Exception:
            pass
        print(f"\n### {sym} continuous: {getattr(c,'localSymbol','') or sym} conId={c.conId}")
        for bar_size, (durations, slug) in PLAN.items():
            print(f"\n=== {sym} {bar_size} (try {durations}) ===")
            bars = fetch_single(ib, c, bar_size, durations)
            if bars:
                save(bars, sym, slug)
            else:
                print(f"  NO DATA for {sym} {bar_size}")
            time.sleep(3)
    ib.disconnect(); print("\nDone.")


if __name__ == "__main__":
    main()
