"""Thin wrapper around robin_stocks for live trading.

Kept intentionally minimal — the paper broker is the source of truth for
backtesting and dashboard state. This class submits real market orders and
mirrors fills back into a local PaperBroker-like state container so the rest
of the system stays identical.

Credentials come from the environment (.env). MFA code must be live.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Dict, List, Optional

try:
    import robin_stocks.robinhood as rh
except ImportError:  # allow import without the library installed
    rh = None  # type: ignore

from .base import Broker, Position, Trade

log = logging.getLogger(__name__)


class RobinhoodBroker(Broker):
    def __init__(self, starting_equity: float):
        if rh is None:
            raise RuntimeError("robin_stocks is not installed; `pip install robin_stocks`")
        user = os.getenv("RH_USERNAME")
        pw = os.getenv("RH_PASSWORD")
        mfa = os.getenv("RH_MFA_CODE") or None
        if not (user and pw):
            raise RuntimeError("RH_USERNAME / RH_PASSWORD must be set for live mode")
        rh.login(username=user, password=pw, mfa_code=mfa, store_session=True)
        self._starting_equity = starting_equity
        self._positions: Dict[str, Position] = {}
        self._trades: List[Trade] = []

    def _portfolio_value(self) -> float:
        try:
            profile = rh.profiles.load_portfolio_profile()
            return float(profile.get("equity", self._starting_equity))
        except Exception as e:  # noqa: BLE001
            log.warning("RH portfolio fetch failed: %s", e)
            return self._starting_equity

    def cash(self) -> float:
        try:
            profile = rh.profiles.load_account_profile()
            return float(profile.get("cash", 0.0))
        except Exception as e:  # noqa: BLE001
            log.warning("RH cash fetch failed: %s", e)
            return 0.0

    def equity(self) -> float:
        return self._portfolio_value()

    def positions(self) -> Dict[str, Position]:
        return self._positions

    def trade_history(self) -> List[Trade]:
        return self._trades

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
        try:
            order = rh.orders.order_buy_market(symbol, qty, timeInForce="gfd")
            fill_price = float(order.get("price") or price)
        except Exception as e:  # noqa: BLE001
            log.error("RH buy failed for %s: %s", symbol, e)
            return None
        pos = Position(
            symbol=symbol,
            qty=qty,
            entry_price=fill_price,
            entry_time=timestamp or datetime.utcnow(),
            stop_price=stop_price,
            take_profit=take_profit,
            trail_mult=trail_mult,
            atr_at_entry=atr,
            high_since_entry=fill_price,
            last_price=fill_price,
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
        pos = self._positions.get(symbol)
        if pos is None:
            return None
        try:
            order = rh.orders.order_sell_market(symbol, pos.qty, timeInForce="gfd")
            fill_price = float(order.get("price") or price)
        except Exception as e:  # noqa: BLE001
            log.error("RH sell failed for %s: %s", symbol, e)
            return None
        del self._positions[symbol]
        pnl = (fill_price - pos.entry_price) * pos.qty
        pnl_pct = (fill_price - pos.entry_price) / pos.entry_price if pos.entry_price else 0.0
        trade = Trade(
            symbol=symbol,
            qty=pos.qty,
            entry_time=pos.entry_time,
            entry_price=pos.entry_price,
            exit_time=timestamp or datetime.utcnow(),
            exit_price=fill_price,
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
