"""Thread-safe portfolio risk manager shared across every strategy thread.

Enforces (adversarial-review must-fixes):
* per-trade 1% RISK-AT-STOP (sizing happens in the base; this caps the book),
* AGGREGATE open risk-at-stop cap (so 5 x 1% can't silently become 5% when the stated
  small-account aggregate is 3%),
* max concurrent positions, max per GICS sector,
* same-symbol cross-strategy lock (two bots must not both go long the same name),
* one-trade-per-symbol-per-day,
* daily-loss HALT on REALIZED + UNREALIZED PnL vs a once-snapshotted start-of-day equity,
* on-disk persistence of realized PnL + traded-today for restart/reconnect recovery.
"""
from __future__ import annotations
import json
import os
import threading


class SymbolLock:
    """Cross-strategy lock so two strategies never hold the SAME symbol at once
    (shared across every per-strategy PortfolioRiskManager)."""

    def __init__(self):
        self._lock = threading.Lock()
        self._open: set[str] = set()

    def is_open(self, symbol: str) -> bool:
        with self._lock:
            return symbol in self._open

    def add(self, symbol: str) -> None:
        with self._lock:
            self._open.add(symbol)

    def remove(self, symbol: str) -> None:
        with self._lock:
            self._open.discard(symbol)


class PortfolioRiskManager:
    """One instance PER STRATEGY (its own book). start_equity is the STRATEGY capital
    (e.g. 100,000), so the aggregate-risk and daily-loss limits are per strategy."""

    def __init__(self, start_equity: float, cfg: dict, state_path: str | None = None,
                 symbol_lock: "SymbolLock | None" = None):
        self._lock = threading.RLock()
        self.start_equity = float(start_equity)   # per-strategy capital
        self.symbol_lock = symbol_lock
        self.max_concurrent = int(cfg.get("max_concurrent_tickers",
                                          cfg.get("max_concurrent_positions", 5)))
        self.max_per_sector = int(cfg.get("max_positions_per_sector", 2))
        self.daily_loss_limit_pct = float(cfg.get("daily_loss_limit_pct", 0.03))
        self.aggregate_open_risk_pct = float(
            cfg.get("aggregate_open_risk_pct", cfg.get("daily_loss_limit_pct", 0.03))
        )
        self._state_path = state_path
        self._open: dict[str, dict] = {}   # order_ref -> position dict
        self._realized = 0.0
        self._unrealized_by: dict[str, float] = {}   # per-strategy unrealized (summed)
        self._traded_today: set[str] = set()
        self._load()

    # ---------------- persistence ----------------
    def _load(self) -> None:
        if not self._state_path:
            return
        try:
            with open(self._state_path, "r", encoding="utf-8") as f:
                b = json.load(f)
            self._realized = float(b.get("realized", 0.0))
            self._traded_today = set(b.get("traded_today", []))
        except (OSError, ValueError):
            pass

    def _flush(self) -> None:
        if not self._state_path:
            return
        try:
            tmp = self._state_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(
                    {"realized": self._realized, "traded_today": sorted(self._traded_today)}, f
                )
            os.replace(tmp, self._state_path)
        except OSError:
            pass

    # ---------------- queries ----------------
    def open_risk(self) -> float:
        with self._lock:
            return sum(p["risk"] for p in list(self._open.values()))

    def sector_count(self, sector: str) -> int:
        with self._lock:
            return sum(1 for p in list(self._open.values()) if p["sector"] == sector)

    def is_open_symbol(self, symbol: str) -> bool:
        with self._lock:
            return any(p["symbol"] == symbol for p in list(self._open.values()))

    def traded_today(self, symbol: str) -> bool:
        with self._lock:
            return symbol in self._traded_today

    def mark_unrealized(self, owner: str, total_unrealized: float) -> None:
        with self._lock:
            self._unrealized_by[owner] = total_unrealized

    def is_halted(self) -> bool:
        with self._lock:
            drawdown = self._realized + sum(self._unrealized_by.values())
            return drawdown <= -abs(self.daily_loss_limit_pct) * self.start_equity

    # ---------------- gate ----------------
    def can_open(self, symbol: str, sector: str, risk_dollars: float,
                 one_trade_per_symbol: bool = True) -> tuple[bool, str]:
        with self._lock:
            if self.is_halted():
                return False, "daily-loss halt"
            if len(self._open) >= self.max_concurrent:
                return False, "max concurrent tickers"
            if self.symbol_lock is not None and self.symbol_lock.is_open(symbol):
                return False, "symbol held by another strategy"
            if self.is_open_symbol(symbol):
                return False, "symbol already open"
            if one_trade_per_symbol and self.traded_today(symbol):
                return False, "already traded today"
            if sector and self.sector_count(sector) >= self.max_per_sector:
                return False, f"sector cap reached ({sector})"
            if self.open_risk() + risk_dollars > self.aggregate_open_risk_pct * self.start_equity:
                return False, "aggregate open-risk cap"
            return True, "ok"

    # ---------------- mutations ----------------
    def register_open(self, order_ref: str, symbol: str, sector: str,
                      risk_dollars: float, qty: int, entry: float, stop: float) -> None:
        with self._lock:
            self._open[order_ref] = {
                "symbol": symbol, "sector": sector, "risk": risk_dollars,
                "qty": qty, "entry": entry, "stop": stop,
            }
            self._traded_today.add(symbol)
            if self.symbol_lock is not None:
                self.symbol_lock.add(symbol)
            self._flush()

    def register_close(self, order_ref: str, realized_pnl: float) -> None:
        with self._lock:
            pos = self._open.pop(order_ref, None)
            if pos and self.symbol_lock is not None:
                self.symbol_lock.remove(pos["symbol"])
            self._realized += realized_pnl
            self._flush()

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "open_positions": len(self._open),
                "open_risk": round(self.open_risk(), 2),
                "realized": round(self._realized, 2),
                "unrealized": round(sum(self._unrealized_by.values()), 2),
                "halted": self.is_halted(),
            }
