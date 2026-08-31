"""Download MNQ front-month futures bars from IB Gateway (port 4002) for backtesting.
24H session (useRTH=False), TRADES, multiple bar sizes. Chunked to respect IB limits.
Writes CSVs to the Trade root: MNQ_<slug>_bt.csv
"""
import csv
import time
from datetime import datetime, timedelta, timezone

from ib_async import IB, Future

HOST, PORT, CLIENT_ID = "127.0.0.1", 4002, 88
OUT_DIR = r"C:\Users\abdbasit\Downloads\Personal\Trade"

# bar_size -> (single-request chunk duration, target calendar-day lookback, slug)
PLAN = {
    "1 min":   ("2 D",  20,  "1min"),
    "5 mins":  ("2 W",  60,  "5mins"),
    "15 mins": ("1 M",  120, "15mins"),
    "30 mins": ("1 M",  240, "30mins"),
    "1 hour":  ("2 M",  365, "1hour"),
}


def qualify_front_month(ib: IB) -> Future:
    base = Future(symbol="MNQ", exchange="CME", currency="USD")
    cds = list(ib.reqContractDetails(base) or [])
    today = datetime.now().strftime("%Y%m%d")

    def expkey(cd):
        e = str(getattr(cd.contract, "lastTradeDateOrContractMonth", "") or "")
        return e if len(e) >= 8 else (e + "31")[:8]

    live = [cd for cd in cds if expkey(cd) >= today]
    chosen = min(live or cds, key=expkey)
    c = chosen.contract
    print(f"MNQ front month: {c.localSymbol} exp {expkey(chosen)} x{c.multiplier} tick {chosen.minTick}")
    return c


def fetch_chunked(ib, contract, bar_size, chunk_dur, target_days):
    end_dt = datetime.now(timezone.utc)
    cutoff = end_dt - timedelta(days=target_days)
    seen = {}
    chunk = 0
    while end_dt > cutoff and chunk < 200:
        chunk += 1
        try:
            bars = ib.reqHistoricalData(
                contract, endDateTime=end_dt.strftime("%Y%m%d %H:%M:%S"),
                durationStr=chunk_dur, barSizeSetting=bar_size, whatToShow="TRADES",
                useRTH=False, formatDate=1, timeout=120) or []
        except Exception as e:
            print(f"  chunk {chunk} error: {e}")
            time.sleep(3)
            continue
        if not bars:
            print(f"  chunk {chunk}: no data, stop")
            break
        for b in bars:
            seen[b.date] = b
        oldest = min(b.date for b in bars)
        od = oldest if isinstance(oldest, datetime) else datetime.combine(oldest, datetime.min.time())
        if od.tzinfo is None:
            od = od.replace(tzinfo=timezone.utc)
        print(f"  chunk {chunk}: {len(bars)} bars, oldest={od.date()}, total={len(seen)}")
        if od <= cutoff:
            break
        end_dt = od.astimezone(timezone.utc) - timedelta(seconds=1)
        time.sleep(2)
    return [seen[k] for k in sorted(seen)]


def save(bars, slug):
    path = rf"{OUT_DIR}\MNQ_{slug}_bt.csv"
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "open", "high", "low", "close", "volume"])
        for b in bars:
            w.writerow([b.date, b.open, b.high, b.low, b.close, b.volume])
    print(f"  -> {path} ({len(bars)} bars, {bars[0].date} .. {bars[-1].date})")


def main():
    ib = IB()
    ib.connect(HOST, PORT, clientId=CLIENT_ID)
    ib.reqMarketDataType(3)
    c = qualify_front_month(ib)
    for bar_size, (chunk_dur, target_days, slug) in PLAN.items():
        print(f"\n=== {bar_size} (target {target_days}d, chunk {chunk_dur}) ===")
        bars = fetch_chunked(ib, c, bar_size, chunk_dur, target_days)
        if bars:
            save(bars, slug)
        else:
            print(f"  NO DATA for {bar_size}")
        time.sleep(3)
    ib.disconnect()
    print("\nDone.")


if __name__ == "__main__":
    main()
