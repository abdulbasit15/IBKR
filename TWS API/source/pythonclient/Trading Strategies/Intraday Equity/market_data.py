"""Market data utilities for the Intraday Equity bots.

This module provides a simple rate limiter for IB historical and contract
requests, a file-backed daily cache for shared values, and a placeholder
auto-detection helper for volume scaling.
"""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Any


class RateLimiter:
    def __init__(self, min_interval: float = 2.0):
        self.min_interval = float(min_interval)
        self._lock = threading.Lock()
        self._last: float = 0.0

    def acquire(self) -> None:
        with self._lock:
            now = time.monotonic()
            delta = self.min_interval - (now - self._last)
            if delta > 0:
                time.sleep(delta)
            self._last = time.monotonic()


class DailyCache:
    def __init__(self, path: str, stamp: str):
        self.path = path
        self.stamp = stamp
        self._lock = threading.Lock()
        self._data: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                self._data = data
        except Exception:
            self._data = {}

    def _save(self) -> None:
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._data.get(key, default)

    def put(self, key: str, value: Any) -> None:
        with self._lock:
            self._data[key] = value
            self._save()


def detect_volume_scale(ib) -> int:
    """Detect whether historical bar volume values need a scale factor.

    This function currently returns 1 by default. It is designed to be a
    lightweight hook for future auto-detection of IB volume units.
    """
    try:
        return 1
    except Exception:
        return 1
