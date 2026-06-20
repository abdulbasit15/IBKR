"""Download SOXL historical intraday bars for the last 2 years."""

import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
from ib_insync import IB, Stock, util

SYMBOL = "SOXL"
EXCHANGE = "SMART"
CURRENCY = "USD"
YEARS = 2
BAR_SIZES = ["15 mins", "30 mins", "1 hour"]
OUTPUT_DIR = Path(__file__).parent / "data"
HOST = "127.0.0.1"
PORT = 7497
CLIENT_ID = 11
REQUEST_TIMEOUT = 300
MAX_RETRIES = 3
PACING_SEC = 3

# IB max duration per request varies by bar size; smaller chunks are more reliable.
CHUNK_BY_BAR_SIZE = {
    "15 mins": "6 M",
    "30 mins": "6 M",
    "1 hour": "1 Y",
}


def to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def request_bars(ib: IB, contract, bar_size: str, end_dt: datetime, duration: str) -> list:
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            bars = ib.reqHistoricalData(
                contract,
                endDateTime=to_utc(end_dt).strftime("%Y%m%d %H:%M:%S"),
                durationStr=duration,
                barSizeSetting=bar_size,
                whatToShow="TRADES",
                useRTH=True,
                formatDate=1,
                timeout=REQUEST_TIMEOUT,
            )
            if bars:
                return bars
        except Exception as exc:
            print(f"    attempt {attempt} failed: {exc}")
        ib.sleep(PACING_SEC * attempt)
    return []


def fetch_bars_chunked(ib: IB, contract, bar_size: str) -> list:
    """Fetch multi-year intraday bars in IB-compliant chunks."""
    all_bars = []
    end_dt = datetime.now(timezone.utc)
    cutoff = end_dt - timedelta(days=365 * YEARS)
    seen_dates = set()
    chunk_duration = CHUNK_BY_BAR_SIZE[bar_size]
    chunk_num = 0

    while end_dt > cutoff:
        chunk_num += 1
        print(f"    chunk {chunk_num}: ending {to_utc(end_dt).strftime('%Y-%m-%d %H:%M:%S')} UTC")
        bars = request_bars(ib, contract, bar_size, end_dt, chunk_duration)
        if not bars:
            print(f"    chunk {chunk_num}: no data, stopping")
            break

        added = 0
        for bar in bars:
            if bar.date not in seen_dates:
                seen_dates.add(bar.date)
                all_bars.append(bar)
                added += 1

        oldest = min(to_utc(bar.date) for bar in bars)
        print(f"    chunk {chunk_num}: received {len(bars)} bars ({added} new), oldest={oldest.date()}")

        if oldest <= cutoff:
            break

        end_dt = oldest - timedelta(seconds=1)
        ib.sleep(PACING_SEC)

    all_bars.sort(key=lambda b: b.date)
    return all_bars


def update_csv(ib: IB, contract, bar_size: str, end_dt: datetime) -> Path | None:
    """Append bars newer than the last row in an existing CSV."""
    slug = bar_size.replace(" ", "")
    path = OUTPUT_DIR / f"{SYMBOL}_{slug}_2y.csv"
    if not path.exists():
        print(f"  {path.name} not found, skipping update")
        return None

    existing = pd.read_csv(path)
    last_ts = pd.Timestamp(existing["date"].iloc[-1])

    bars = request_bars(ib, contract, bar_size, end_dt, "1 M")
    if not bars:
        print(f"  No data returned for {bar_size}")
        return None

    new_bars = [b for b in bars if pd.Timestamp(b.date) > last_ts]
    if not new_bars:
        print(f"  {bar_size}: already up to date (last={last_ts})")
        return path

    new_df = util.df(new_bars)
    combined = pd.concat([existing, new_df], ignore_index=True)
    combined.to_csv(path, index=False)
    print(
        f"  {bar_size}: appended {len(new_df)} bars "
        f"({new_df['date'].iloc[0]} to {new_df['date'].iloc[-1]})"
    )
    return path


def save_bars(bars: list, bar_size: str) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    slug = bar_size.replace(" ", "")
    path = OUTPUT_DIR / f"{SYMBOL}_{slug}_2y.csv"
    df = util.df(bars)
    df.to_csv(path, index=False)
    return path


def main(update_only: bool = False, end_date: str | None = None):
    ib = IB()
    ib.connect(HOST, PORT, clientId=CLIENT_ID)
    ib.RequestTimeout = REQUEST_TIMEOUT

    contract = Stock(SYMBOL, EXCHANGE, CURRENCY)
    ib.qualifyContracts(contract)
    print(f"Contract: {contract}")

    end_dt = (
        datetime.strptime(end_date, "%Y-%m-%d").replace(
            hour=23, minute=59, second=59, tzinfo=timezone.utc
        )
        if end_date
        else datetime.now(timezone.utc)
    )

    for bar_size in BAR_SIZES:
        if update_only:
            print(f"\nUpdating {bar_size} bars through {end_dt.date()}...")
            path = update_csv(ib, contract, bar_size, end_dt)
        else:
            print(f"\nDownloading {bar_size} bars...")
            bars = fetch_bars_chunked(ib, contract, bar_size)
            if not bars:
                print(f"  No data returned for {bar_size}")
                continue
            path = save_bars(bars, bar_size)

        if path:
            df = pd.read_csv(path)
            print(f"  Total {len(df)} bars -> {path}")
            print(f"  Range: {df['date'].iloc[0]} to {df['date'].iloc[-1]}")
        time.sleep(PACING_SEC)

    ib.disconnect()
    print("\nDone.")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Download or update SOXL historical bars")
    parser.add_argument(
        "--update",
        action="store_true",
        help="Append new bars to existing CSVs instead of full re-download",
    )
    parser.add_argument(
        "--end-date",
        type=str,
        default=None,
        help="End date for update (YYYY-MM-DD), defaults to now",
    )
    args = parser.parse_args()
    main(update_only=args.update, end_date=args.end_date)
