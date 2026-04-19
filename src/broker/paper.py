"""In-memory paper-trading broker.

Used for both `mode=paper` live simulation and the backtester.
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from .base import Broker, Position, Trade


class PaperBroker(Broker):
    def __init__(self, starting_equity: float = 100_000.0):
        self._cash = float(starting_equity)
        self._starting_equity = float(starting_equity)
        self._positions: Dict[str, Position] = {}
        self._trades: List[Trade] = []
        self._equity_curve: List[tuple] = []  # (timestamp, equity)

    # --- Read -------------------------------------------------------------
    def cash(self) -> float:
        return self._cash

    def equity(self) -> float:
        return self._cash + sum(p.market_value for p in self._positions.values())

    def positions(self) -> Dict[str, Position]:
        return self._positions

    def trade_history(self) -> List[Trade]:
        return self._trades

    def equity_curve(self) -> List[tuple]:
        return self._equity_curve

    # --- Mutation ---------------------------------------------------------
    def buy(
        self,
        symbol: str,
        qty: int,
        price: float,
        *,
        timestamp: Optional[datetime] = None,
        stop_price: float = 0.0,
        take_profit: float = 0.0,
        trail_mult: float = 2.0,
        atr: float = 0.0,
    ) -> Optional[Position]:
        if symbol in self._positions or qty <= 0:
            return None
        cost = qty * price
        if cost > self._cash:
            return None
        self._cash -= cost
        now = timestamp or datetime.utcnow()
        pos = Position(
            symbol=symbol,
            qty=qty,
            entry_price=price,
            entry_time=now,
            stop_price=stop_price,
            take_profit=take_profit,
            trail_mult=trail_mult,
            atr_at_entry=atr,
            high_since_entry=price,
            last_price=price,
        )
        self._positions[symbol] = pos
        return pos

    def sell(
        self,
        symbol: str,
        price: float,
        reason: str,
        *,
        timestamp: Optional[datetime] = None,
    ) -> Optional[Trade]:
        pos = self._positions.pop(symbol, None)
        if pos is None:
            return None
        proceeds = pos.qty * price
        self._cash += proceeds
        pnl = (price - pos.entry_price) * pos.qty
        pnl_pct = (price - pos.entry_price) / pos.entry_price if pos.entry_price else 0.0
        trade = Trade(
            symbol=symbol,
            qty=pos.qty,
            entry_time=pos.entry_time,
            entry_price=pos.entry_price,
            exit_time=timestamp or datetime.utcnow(),
            exit_price=price,
            pnl=pnl,
            pnl_pct=pnl_pct,
            reason=reason,
        )
        self._trades.append(trade)
        return trade

    def mark(self, prices: Dict[str, float], timestamp: Optional[datetime] = None) -> None:
        for sym, px in prices.items():
            if sym in self._positions:
                p = self._positions[sym]
                p.last_price = px
                if px > p.high_since_entry:
                    p.high_since_entry = px
        if timestamp is not None:
            self._equity_curve.append((timestamp, self.equity()))

    # --- Helpers ----------------------------------------------------------
    @property
    def total_pnl(self) -> float:
        return self.equity() - self._starting_equity

    @property
    def total_pnl_pct(self) -> float:
        return self.total_pnl / self._starting_equity if self._starting_equity else 0.0

    def resolved_trade_count(self) -> int:
        return len(self._trades)
