"""Thread-safe shared state consumed by the Dash UI."""
from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Deque, Dict, List

from config import UNIVERSE


@dataclass
class LogLine:
    ts: datetime
    level: str
    msg: str


class DashboardState:
    def __init__(self, universe_size: int = len(UNIVERSE), log_capacity: int = 500):
        self._lock = threading.Lock()
        self.universe_size = universe_size
        self.equity = 0.0
        self.starting_equity = 0.0
        self.day_start_equity = 0.0
        self.total_pnl = 0.0
        self.day_pnl = 0.0
        self.open_positions: List[Dict] = []
        self.trade_history: List[Dict] = []
        self.equity_curve: List[Dict] = []   # {ts, equity}
        self.halted = False
        self.halt_reason: str | None = None
        self._logs: Deque[LogLine] = deque(maxlen=log_capacity)

    def add_log(self, ts: datetime, level: str, msg: str) -> None:
        with self._lock:
            self._logs.append(LogLine(ts, level, msg))

    def logs(self) -> List[LogLine]:
        with self._lock:
            return list(self._logs)[::-1]  # newest first

    def set_day_start(self, equity: float) -> None:
        with self._lock:
            self.day_start_equity = equity

    def update_broker_snapshot(self, broker, risk) -> None:
        with self._lock:
            equity = broker.equity()
            self.equity = equity
            if self.starting_equity == 0.0:
                self.starting_equity = getattr(broker, "_starting_equity", equity)
            if self.day_start_equity == 0.0:
                self.day_start_equity = equity
            self.total_pnl = equity - self.starting_equity
            self.day_pnl = equity - self.day_start_equity
            self.halted = risk.halted
            self.halt_reason = risk.halt_reason

            self.open_positions = [
                {
                    "symbol": p.symbol,
                    "qty": p.qty,
                    "entry": round(p.entry_price, 2),
                    "current": round(p.last_price, 2),
                    "pnl_usd": round(p.unrealised_pnl, 2),
                    "pnl_pct": round(p.unrealised_pnl_pct * 100, 2),
                }
                for p in broker.positions().values()
            ]
            self.trade_history = [t.as_row() for t in broker.trade_history()[-200:]][::-1]
            if hasattr(broker, "equity_curve"):
                self.equity_curve = [
                    {"ts": ts, "equity": eq} for ts, eq in broker.equity_curve()[-5000:]
                ]

    def header(self) -> Dict:
        with self._lock:
            return {
                "equity": self.equity,
                "day_pnl": self.day_pnl,
                "total_pnl": self.total_pnl,
                "open": len(self.open_positions),
                "resolved": len(self.trade_history),
                "universe": self.universe_size,
                "halted": self.halted,
                "halt_reason": self.halt_reason,
            }
