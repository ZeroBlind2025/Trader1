"""Main live/paper trading loop.

Every ``STRATEGY.scan_interval_minutes`` minutes:
    1. Fetch fresh 15m candles for the universe.
    2. Mark open positions, update trailing stops.
    3. Exit rules: stop hit, take-profit, time-stop, or drawdown halt.
    4. If slots available and not halted, scan for new entries, rank by score.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import pandas as pd
import pytz

from config import RISK, RUNTIME, STRATEGY, UNIVERSE
from src.broker.base import Broker
from src.data import feed
from src.engine.market_hours import is_market_open, next_open
from src.engine.regime import RegimeFilter
from src.risk.manager import RiskManager
from src.strategy import scoring
from src.strategy.scoring import Signal


def _bar_minutes(interval: str) -> int:
    """Translate a yfinance-style interval string to minutes."""
    mapping = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "60m": 60, "1h": 60, "1d": 1440}
    return mapping.get(interval, 15)

log = logging.getLogger(__name__)


class Trader:
    def __init__(self, broker: Broker, risk: RiskManager, dashboard_state=None):
        self.broker = broker
        self.risk = risk
        self.state = dashboard_state  # optional shared dashboard state
        self._bar_minutes = _bar_minutes(STRATEGY.candle_interval)
        self._regime: RegimeFilter = RegimeFilter()  # primed on first tick
        self._regime_refreshed_at: Optional[datetime] = None
        self._last_regime_bull: Optional[bool] = None

    # -- regime ------------------------------------------------------------
    def _refresh_regime(self, force: bool = False) -> None:
        """Reload SPY daily history if we've never loaded or it's >12h stale."""
        now = self._now()
        if (
            not force
            and self._regime_refreshed_at is not None
            and now - self._regime_refreshed_at < timedelta(hours=12)
        ):
            return
        end = datetime.utcnow()
        start = end - timedelta(days=RISK.regime_sma_period * 2)
        try:
            df = feed.fetch_history(RISK.regime_symbol, start, end, interval="1d")
        except Exception as exc:  # noqa: BLE001
            self._log(f"Regime fetch failed ({RISK.regime_symbol}: {exc})", "WARNING")
            return
        self._regime = RegimeFilter(df)
        self._regime_refreshed_at = now
        snap = self._regime.snapshot()
        if snap.get("bull") is False:
            self._log(
                f"Regime: BEARISH — {RISK.regime_symbol} {snap['spot']:.2f} < "
                f"{RISK.regime_sma_period}D SMA {snap['sma']:.2f}; entries blocked",
                "WARNING",
            )
        elif self._regime.has_data():
            self._log(
                f"Regime: BULLISH — {RISK.regime_symbol} {snap['spot']:.2f} >= "
                f"{RISK.regime_sma_period}D SMA {snap['sma']:.2f}"
            )

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
            if price > pos.high_since_entry:
                pos.high_since_entry = price
            atr_val = pos.atr_at_entry
            pos.stop_price = RiskManager.update_trailing_stop(
                pos.stop_price, pos.high_since_entry, atr_val, pos.trail_mult
            )
            if price <= pos.stop_price:
                to_close.append((sym, price, "stop/trail"))
            elif price >= pos.take_profit:
                to_close.append((sym, price, "take-profit"))
            elif RiskManager.is_dead(
                pos.entry_time, now, pos.entry_price, price, bar_minutes=self._bar_minutes
            ):
                to_close.append((sym, price, "time-stop"))

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
        if not is_market_open(now):
            nxt = next_open(now)
            self._log(
                f"Market closed ({now:%a %H:%M %Z}); next open {nxt:%a %Y-%m-%d %H:%M %Z}. "
                "Skipping scan.",
                "INFO",
            )
            self._push_state()
            return

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

        # Regime gate: block new entries in bearish regime but keep managing exits.
        self._refresh_regime()
        bull = self._regime.is_bull()
        if bull != self._last_regime_bull and self._regime.has_data():
            # Log on flip only.
            snap = self._regime.snapshot()
            self._log(
                f"Regime flip -> {'BULL' if bull else 'BEAR'} "
                f"(spot={snap.get('spot', 0):.2f}, sma={snap.get('sma', 0):.2f})",
                "INFO" if bull else "WARNING",
            )
        self._last_regime_bull = bull
        if not bull:
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
