"""Main live/paper trading loop.

Every ``STRATEGY.scan_interval_minutes`` minutes:
    1. Fetch fresh 15m candles for the universe.
    2. Mark open positions, update trailing stops.
    3. Exit rules: stop hit, take-profit, time-stop, or drawdown halt.
    4. If slots available and not halted, scan for new entries, rank by score.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Dict, List

import pandas as pd
import pytz

from config import RISK, RUNTIME, STRATEGY, UNIVERSE
from src.broker.base import Broker
from src.data import feed
from src.risk.manager import RiskManager
from src.strategy import scoring
from src.strategy.scoring import Signal

log = logging.getLogger(__name__)


class Trader:
    def __init__(self, broker: Broker, risk: RiskManager, dashboard_state=None):
        self.broker = broker
        self.risk = risk
        self.state = dashboard_state  # optional shared dashboard state

    # -- helpers -----------------------------------------------------------
    def _now(self) -> datetime:
        return datetime.now(pytz.timezone(RUNTIME.tz))

    def _log(self, msg: str, level: str = "INFO") -> None:
        log.log(getattr(logging, level), msg)
        if self.state is not None:
            self.state.add_log(self._now(), level, msg)

    # -- exit management ---------------------------------------------------
    def _manage_exits(self, data: Dict[str, pd.DataFrame]) -> None:
        now = self._now()
        to_close: List[tuple[str, float, str]] = []
        prices: Dict[str, float] = {}

        for sym, pos in list(self.broker.positions().items()):
            df = data.get(sym)
            if df is None or df.empty:
                continue
            last = df.iloc[-1]
            price = float(last["close"])
            prices[sym] = price
            # Update high since entry first
            if price > pos.high_since_entry:
                pos.high_since_entry = price
            # ATR approximation from recent ATR, fall back to entry ATR
            atr_val = pos.atr_at_entry
            # Trail
            pos.stop_price = RiskManager.update_trailing_stop(
                pos.stop_price, pos.high_since_entry, atr_val, pos.trail_mult
            )
            # Exit checks
            if price <= pos.stop_price:
                to_close.append((sym, price, "stop/trail"))
            elif price >= pos.take_profit:
                to_close.append((sym, price, "take-profit"))
            elif RiskManager.is_dead(pos.entry_time, now, pos.entry_price, price):
                to_close.append((sym, price, "time-stop"))

        # Mark-to-market everything before closing
        self.broker.mark(prices, timestamp=now)

        for sym, px, reason in to_close:
            trade = self.broker.sell(sym, px, reason, timestamp=now)
            if trade:
                self._log(
                    f"CLOSE {sym} qty={trade.qty} @ {px:.2f} pnl=${trade.pnl:.2f} "
                    f"({trade.pnl_pct*100:.2f}%) [{reason}]"
                )

    # -- entry scanning ----------------------------------------------------
    def _scan_for_entries(self, data: Dict[str, pd.DataFrame]) -> List[Signal]:
        signals: List[Signal] = []
        for sym, df in data.items():
            if sym in self.broker.positions():
                continue
            if df is None or df.empty:
                continue
            if float(df["close"].iloc[-1]) < STRATEGY.min_price:
                continue
            sig = scoring.evaluate(sym, df)
            if sig and sig.enter:
                signals.append(sig)
        # Rank by score desc, ADX as tie-breaker
        signals.sort(key=lambda s: (s.score, s.adx), reverse=True)
        return signals

    def _enter(self, sig: Signal) -> None:
        now = self._now()
        equity = self.broker.equity()
        sizing = self.risk.size_position(equity, sig.price, sig.atr)
        if sizing is None:
            return
        pos = self.broker.buy(
            sig.symbol,
            sizing.qty,
            sig.price,
            timestamp=now,
            stop_price=sizing.stop_price,
            take_profit=sizing.take_profit,
            trail_mult=sizing.trail_mult,
            atr=sig.atr,
        )
        if pos:
            self._log(
                f"OPEN  {sig.symbol} qty={sizing.qty} @ {sig.price:.2f} "
                f"stop={sizing.stop_price:.2f} tp={sizing.take_profit:.2f} "
                f"score={sig.score}/8 risk=${sizing.risk_dollars:.0f}"
            )

    # -- public tick -------------------------------------------------------
    def tick(self) -> None:
        now = self._now()
        self._log(f"Scan tick @ {now:%H:%M:%S} equity=${self.broker.equity():,.2f}")

        data = feed.fetch_batch(UNIVERSE, interval=STRATEGY.candle_interval, period="60d")
        if not data:
            self._log("No data returned from feed", "WARNING")
            return

        self._manage_exits(data)
        self.risk.update_equity(self.broker.equity())

        if self.risk.halted:
            self._log(f"HALTED: {self.risk.halt_reason}", "WARNING")
            self._push_state()
            return

        open_count = len(self.broker.positions())
        if not self.risk.can_trade(open_count):
            self._push_state()
            return

        slots = RISK.max_concurrent_positions - open_count
        signals = self._scan_for_entries(data)
        for sig in signals[:slots]:
            self._enter(sig)

        self._push_state()

    def _push_state(self) -> None:
        if self.state is None:
            return
        self.state.update_broker_snapshot(self.broker, self.risk)
