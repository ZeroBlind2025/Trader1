"""Broker interface + shared order/position dataclasses."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional


@dataclass
class Position:
    symbol: str
    qty: int
    entry_price: float
    entry_time: datetime
    stop_price: float
    take_profit: float
    trail_mult: float
    atr_at_entry: float
    high_since_entry: float = 0.0
    last_price: float = 0.0

    @property
    def market_value(self) -> float:
        return self.qty * self.last_price

    @property
    def unrealised_pnl(self) -> float:
        return (self.last_price - self.entry_price) * self.qty

    @property
    def unrealised_pnl_pct(self) -> float:
        if self.entry_price == 0:
            return 0.0
        return (self.last_price - self.entry_price) / self.entry_price


@dataclass
class Trade:
    symbol: str
    qty: int
    entry_time: datetime
    entry_price: float
    exit_time: datetime
    exit_price: float
    pnl: float
    pnl_pct: float
    reason: str

    def as_row(self) -> Dict:
        return {
            "symbol": self.symbol,
            "qty": self.qty,
            "entry_time": self.entry_time.strftime("%Y-%m-%d %H:%M"),
            "entry": round(self.entry_price, 2),
            "exit_time": self.exit_time.strftime("%Y-%m-%d %H:%M"),
            "exit": round(self.exit_price, 2),
            "pnl_usd": round(self.pnl, 2),
            "pnl_pct": round(self.pnl_pct * 100, 2),
            "reason": self.reason,
        }


class Broker(ABC):
    """Abstract broker. Implementations can be paper, Robinhood, etc."""

    @abstractmethod
    def cash(self) -> float: ...

    @abstractmethod
    def equity(self) -> float: ...

    @abstractmethod
    def positions(self) -> Dict[str, Position]: ...

    @abstractmethod
    def trade_history(self) -> List[Trade]: ...

    @abstractmethod
    def buy(self, symbol: str, qty: int, price: float, **kwargs) -> Optional[Position]: ...

    @abstractmethod
    def sell(self, symbol: str, price: float, reason: str) -> Optional[Trade]: ...

    @abstractmethod
    def mark(self, prices: Dict[str, float], timestamp: Optional[datetime] = None) -> None:
        """Update last_price on open positions. Optionally record equity curve."""
