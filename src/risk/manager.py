"""Risk manager: position sizing, stops, drawdown circuit breaker, time-stops."""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

from config import RISK


@dataclass
class SizingResult:
    qty: int
    stop_price: float
    take_profit: float
    trail_mult: float
    risk_dollars: float


class RiskManager:
    def __init__(self, starting_equity: float):
        self.starting_equity = starting_equity
        self.peak_equity = starting_equity
        self.halted = False
        self.halt_reason: str | None = None

    # --- Drawdown circuit breaker ------------------------------------------
    def update_equity(self, equity: float) -> None:
        if equity > self.peak_equity:
            self.peak_equity = equity
        dd = (self.peak_equity - equity) / self.peak_equity if self.peak_equity else 0.0
        if dd >= RISK.max_drawdown_pct and not self.halted:
            self.halted = True
            self.halt_reason = f"Drawdown {dd:.2%} exceeded {RISK.max_drawdown_pct:.0%}"

    def can_trade(self, open_positions: int) -> bool:
        if self.halted:
            return False
        return open_positions < RISK.max_concurrent_positions

    # --- Sizing ------------------------------------------------------------
    def size_position(self, equity: float, price: float, atr: float) -> SizingResult | None:
        """Vol-target sizing: each position contributes ~equal $-vol per ATR.

        Primary sizer is ``target_vol_pct`` (dollar volatility budget per unit
        ATR). Three caps ride on top: portfolio_risk_pct (disaster stop loss
        ceiling), max_position_notional_pct (concentration cap), and cash.
        """
        if atr <= 0 or price <= 0:
            return None

        # Primary: vol-target — size so stop-distance move = target_vol_pct of equity
        # independent of trade count, letting low-ATR names take larger notional.
        target_vol_dollars = equity * RISK.target_vol_pct
        qty_by_vol = math.floor(target_vol_dollars / atr)

        # Cap 1: hard loss ceiling if stopped at atr_stop_mult * ATR
        stop_distance = RISK.atr_stop_mult * atr
        risk_dollars = equity * RISK.portfolio_risk_pct
        qty_by_risk = math.floor(risk_dollars / stop_distance)

        # Cap 2: notional concentration per name
        notional_cap = equity * RISK.max_position_notional_pct
        qty_by_notional = math.floor(notional_cap / price)

        # Cap 3: cash on hand (no margin)
        qty_by_cash = math.floor(equity / price)

        qty = min(qty_by_vol, qty_by_risk, qty_by_notional, qty_by_cash)
        if qty <= 0:
            return None

        atr_pct = atr / price
        trail_mult = (
            RISK.trail_mult_high_vol if atr_pct >= RISK.vol_regime_atr_pct else RISK.trail_mult_low_vol
        )

        return SizingResult(
            qty=qty,
            stop_price=round(price - stop_distance, 4),
            take_profit=round(price + RISK.take_profit_mult * atr, 4),
            trail_mult=trail_mult,
            risk_dollars=round(qty * stop_distance, 2),
        )

    # --- Trailing stop -----------------------------------------------------
    @staticmethod
    def update_trailing_stop(
        current_stop: float, high_since_entry: float, atr: float, trail_mult: float
    ) -> float:
        candidate = high_since_entry - trail_mult * atr
        return max(current_stop, candidate)

    # --- Time-stop ---------------------------------------------------------
    @staticmethod
    def is_dead(
        entry_time: datetime,
        now: datetime,
        entry_price: float,
        current_price: float,
        bar_minutes: int = 15,
    ) -> bool:
        """Kill a position that's gone nowhere after time_stop_bars bars.

        ``bar_minutes`` scales the window to the caller's timeframe — live
        trader passes 15 (15m bars), backtester passes 1440 for daily bars,
        so the rule stays meaningful across timeframes.
        """
        window = timedelta(minutes=RISK.time_stop_bars * bar_minutes)
        if now - entry_time < window:
            return False
        move = abs(current_price - entry_price) / entry_price if entry_price else 0.0
        return move < RISK.time_stop_min_move_pct
