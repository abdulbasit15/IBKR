"""Shared market-data utilities used by every strategy thread:

* RateLimiter   - global token-bucket so large nightly/pre-market scans never trip IB's
                  ~60-historical-requests-per-10-minutes pacing limit.
* DailyCache    - per-ET-day JSON cache (RVOL baselines, PDH, ADV, ATR, sector, minTick)
                  so a same-day restart/reconnect reuses expensive lookups.
* detect_volume_scale - empirically decides whether reqHistoricalData STK volume is in
                  shares or round-lots instead of hard-coding *100 (a real footgun).

(Addresses adversarial-review must-fixes: pacing limiter + on-disk cache + volume scale.)
"""
from __future__ import annotations
import json
import os
import threading
import time as _time


class RateLimiter:
    """Process-wide historical-data pacer. Holds a lock while spacing requests so all
    strategy threads share one budget. Defaults: >=2s between requests, <=55 / 10 min."""

    def __init__(self, min_interval: float = 2.0, window_cap: int = 55):
        self._min_interval = min_interval
        self._window_cap = window_cap
        self._lock = threading.Lock()
        self._times: list[float] = []

    def acquire(self) -> None:
        # Reserve a slot under the lock, then sleep OUTSIDE the lock so a long pacing
        # wait does not block every other strategy thread.
        sleep_for = 0.0
        with self._lock:
            now = _time.monotonic()
            self._times = [t for t in self._times if now - t < 600]
            if self._times:
                wait = self._min_interval - (now - self._times[-1])
                if wait > 0:
                    sleep_for = wait
            projected = now + sleep_for
            recent = [t for t in self._times if projected - t < 600]
            if len(recent) >= self._window_cap:
                sleep_for = max(sleep_for, 600 - (projected - recent[0]) + 1)
                projected = now + sleep_for
            self._times.append(projected)   # reserve at the projected time so peers space out
        if sleep_for > 0:
            _time.sleep(sleep_for)


class DailyCache:
    """Per-day JSON cache keyed by ET date. Atomically flushed on every put."""

    def __init__(self, path: str, date_key: str):
        self._path = path
        self._date = date_key
        self._lock = threading.Lock()
        self._data: dict = {}
        self._load()

    def _load(self) -> None:
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                blob = json.load(f)
            if blob.get("date") == self._date:
                self._data = blob.get("data", {})
        except (OSError, ValueError):
            self._data = {}

    def get(self, key: str, default=None):
        with self._lock:
            return self._data.get(key, default)

    def put(self, key: str, value) -> None:
        with self._lock:
            self._data[key] = value
            self._flush()

    def _flush(self) -> None:
        tmp = self._path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"date": self._date, "data": self._data}, f)
            os.replace(tmp, self._path)
        except OSError:
            pass


def detect_volume_scale(ib, probe_symbol: str = "AAPL", expected_adv: float = 40_000_000) -> int:
    """Return the multiplier to convert reqHistoricalData STK volume into actual shares.
    Some TWS builds report round-lots (value/100). We compare a known liquid name's
    daily volume against its rough expected ADV and pick 1 or 100."""
    try:
        from ib_async import Stock
        c = Stock(probe_symbol, "SMART", "USD")
        ib.qualifyContracts(c)
        bars = ib.reqHistoricalData(c, "", "10 D", "1 day", "TRADES", True, 1)
        vols = [float(b.volume) for b in (bars or []) if b.volume and b.volume > 0]
        if not vols:
            return 1
        avg = sum(vols) / len(vols)
        # If multiplying by 100 lands much closer to the expected ADV, volume is in lots.
        if avg < expected_adv / 10 and abs(avg * 100 - expected_adv) < abs(avg - expected_adv):
            return 100
        return 1
    except Exception:
        return 1
