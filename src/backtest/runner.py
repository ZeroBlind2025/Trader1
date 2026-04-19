"""Event-driven 5-year backtester.

Because yfinance caps 15m intraday to ~60 days, the historical backtest
defaults to daily bars (with all the same indicators). This gives a reliable
5-year signal, then paper trading takes over on 15m candles for the
live-simulated portion. Set `interval="15m"` to force intraday if you have an
alternate data source.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List

import numpy as np
import pandas as pd

from config import RISK, STRATEGY, UNIVERSE
from src.broker.paper import PaperBroker
from src.data import feed
from src.risk.manager import RiskManager
from src.strategy import scoring

log = logging.getLogger(__name__)


@dataclass
class BacktestResult:
    starting_equity: float
    ending_equity: float
    total_return_pct: float
    cagr_pct: float
    max_drawdown_pct: float
    sharpe: float
    win_rate: float
    num_trades: int
    equity_curve: pd.Series
    trades: List[dict] = field(default_factory=list)


def _annualised_sharpe(equity: pd.Series) -> float:
    rets = equity.pct_change().dropna()
    if rets.empty or rets.std() == 0:
        return 0.0
    # Assume ~252 bars/yr for daily data
    return float(np.sqrt(252) * rets.mean() / rets.std())


def _max_drawdown(equity: pd.Series) -> float:
    running_max = equity.cummax()
    dd = (equity - running_max) / running_max
    return float(dd.min()) if not dd.empty else 0.0


def run_backtest(
    starting_equity: float = 100_000.0,
    years: int = 5,
    interval: str = "1d",
    universe: List[str] | None = None,
) -> BacktestResult:
    universe = universe or UNIVERSE
    end = datetime.utcnow()
    start = end - timedelta(days=years * 365 + 30)

    log.info("Loading %d symbols from %s to %s (%s)", len(universe), start.date(), end.date(), interval)
    raw: Dict[str, pd.DataFrame] = {}
    for sym in universe:
        df = feed.fetch_history(sym, start, end, interval=interval)
        if not df.empty and len(df) > STRATEGY.ema_trend + 20:
            raw[sym] = df

    if not raw:
        raise RuntimeError("No historical data loaded — check network / yfinance access")

    # Build a master calendar from the union of indexes
    calendar = sorted({ts for df in raw.values() for ts in df.index})

    broker = PaperBroker(starting_equity)
    risk = RiskManager(starting_equity)

    for ts in calendar:
        today_prices: Dict[str, float] = {}
        for sym, df in raw.items():
            if ts in df.index:
                px = float(df.loc[ts, "close"])
                if pd.notna(px):
                    today_prices[sym] = px
        if not today_prices:
            continue

        # --- manage exits ---
        broker.mark(today_prices, timestamp=ts)
        for sym, pos in list(broker.positions().items()):
            price = today_prices.get(sym)
            if price is None:
                continue
            pos.stop_price = RiskManager.update_trailing_stop(
                pos.stop_price, pos.high_since_entry, pos.atr_at_entry, pos.trail_mult
            )
            reason = None
            if price <= pos.stop_price:
                reason = "stop/trail"
            elif price >= pos.take_profit:
                reason = "take-profit"
            elif RiskManager.is_dead(pos.entry_time, ts, pos.entry_price, price):
                reason = "time-stop"
            if reason:
                broker.sell(sym, price, reason, timestamp=ts)

        risk.update_equity(broker.equity())
        if risk.halted:
            for sym in list(broker.positions().keys()):
                broker.sell(sym, today_prices.get(sym, broker.positions()[sym].last_price),
                            "halt", timestamp=ts)
            risk.halted = False
            risk.peak_equity = broker.equity()
            continue

        # --- scan entries ---
        slots = RISK.max_concurrent_positions - len(broker.positions())
        if slots <= 0:
            continue

        candidates = []
        for sym, df in raw.items():
            if sym in broker.positions():
                continue
            sub = df.loc[:ts]
            if len(sub) < STRATEGY.ema_trend + 10:
                continue
            if float(sub["close"].iloc[-1]) < STRATEGY.min_price:
                continue
            sig = scoring.evaluate(sym, sub)
            if sig and sig.enter:
                candidates.append(sig)

        candidates.sort(key=lambda s: (s.score, s.adx), reverse=True)
        for sig in candidates[:slots]:
            sizing = risk.size_position(broker.equity(), sig.price, sig.atr)
            if sizing is None:
                continue
            broker.buy(
                sig.symbol,
                sizing.qty,
                sig.price,
                timestamp=ts,
                stop_price=sizing.stop_price,
                take_profit=sizing.take_profit,
                trail_mult=sizing.trail_mult,
                atr=sig.atr,
            )

    # --- metrics ---
    curve_df = pd.DataFrame(broker.equity_curve(), columns=["ts", "equity"]).set_index("ts")
    curve = curve_df["equity"] if not curve_df.empty else pd.Series([starting_equity])
    total_ret = broker.total_pnl_pct
    years_actual = max((curve.index[-1] - curve.index[0]).days / 365.0, 1e-9) if len(curve) > 1 else years
    cagr = (curve.iloc[-1] / starting_equity) ** (1 / years_actual) - 1 if starting_equity else 0
    trades = broker.trade_history()
    wins = sum(1 for t in trades if t.pnl > 0)
    win_rate = wins / len(trades) if trades else 0.0

    return BacktestResult(
        starting_equity=starting_equity,
        ending_equity=broker.equity(),
        total_return_pct=total_ret,
        cagr_pct=float(cagr),
        max_drawdown_pct=_max_drawdown(curve),
        sharpe=_annualised_sharpe(curve),
        win_rate=win_rate,
        num_trades=len(trades),
        equity_curve=curve,
        trades=[t.as_row() for t in trades],
    )
