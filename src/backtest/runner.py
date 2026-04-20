"""Event-driven 5-year backtester.

Because yfinance caps 15m intraday to ~60 days, the historical backtest
defaults to daily bars (with all the same indicators). This gives a reliable
5-year signal, then paper trading takes over on 15m candles for the
live-simulated portion. Set `interval="15m"` to force intraday if you have an
alternate data source.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional

import numpy as np
import pandas as pd

from config import RISK, STRATEGY, UNIVERSE
from src.broker.paper import PaperBroker
from src.data import feed
from src.engine.regime import RegimeFilter
from src.risk.manager import RiskManager
from src.strategy import scoring


_BAR_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "60m": 60, "1h": 60, "1d": 1440, "1wk": 10080}

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
    wins: int
    losses: int
    wl_ratio: float
    total_cost: float
    total_sale: float
    total_pnl: float
    equity_curve: pd.Series
    trades: List[dict] = field(default_factory=list)

    def summary(self) -> Dict[str, str]:
        """Human-readable one-line-per-metric summary for the dashboard grid."""
        wl = f"{self.wl_ratio:.2f}" if self.losses else ("∞" if self.wins else "0.00")
        return {
            "Trades Entered": f"{self.num_trades}",
            "Wins/Losses": f"{self.wins}/{self.losses}",
            "W/L Ratio": wl,
            "Win Rate": f"{self.win_rate * 100:.1f}%",
            "Total Cost": f"${self.total_cost:,.2f}",
            "Total Sale": f"${self.total_sale:,.2f}",
            "Total PnL": f"${self.total_pnl:,.2f}",
            "Total Return": f"{self.total_return_pct * 100:.2f}%",
            "CAGR": f"{self.cagr_pct * 100:.2f}%",
            "Max DD": f"{self.max_drawdown_pct * 100:.2f}%",
            "Sharpe": f"{self.sharpe:.2f}",
            "Ending Equity": f"${self.ending_equity:,.2f}",
        }


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
    progress_cb: Optional[Callable[[str], None]] = None,
) -> BacktestResult:
    def _emit(msg: str) -> None:
        log.info(msg)
        if progress_cb is not None:
            try:
                progress_cb(msg)
            except Exception:  # noqa: BLE001
                pass

    universe = universe or UNIVERSE
    end = datetime.utcnow()
    start = end - timedelta(days=years * 365 + 30)

    _emit(f"Fetching {len(universe)} symbols from {start.date()} to {end.date()} ({interval})")
    raw: Dict[str, pd.DataFrame] = {}
    fetch_failures: List[str] = []
    t0 = time.time()
    for i, sym in enumerate(universe, 1):
        try:
            df = feed.fetch_history(sym, start, end, interval=interval)
        except Exception as exc:  # noqa: BLE001
            fetch_failures.append(f"{sym}: {exc}")
            continue
        if not df.empty and len(df) > STRATEGY.ema_trend + 20:
            raw[sym] = df
        if i % 10 == 0 or i == len(universe):
            _emit(f"  fetched {i}/{len(universe)} ({len(raw)} usable, {len(fetch_failures)} errors)")

    if fetch_failures:
        _emit(f"Fetch errors on {len(fetch_failures)} symbols (first: {fetch_failures[0]})")
    if not raw:
        raise RuntimeError(
            f"No historical data loaded — all {len(universe)} fetches failed "
            f"(first error: {fetch_failures[0] if fetch_failures else 'empty frames'})"
        )

    _emit(f"Pre-computing indicators for {len(raw)} symbols…")
    enriched: Dict[str, pd.DataFrame] = {}
    for sym, df in raw.items():
        try:
            enriched[sym] = scoring._enrich(df)
        except Exception as exc:  # noqa: BLE001
            _emit(f"  enrich failed for {sym}: {exc}")
    if not enriched:
        raise RuntimeError("Indicator pre-compute produced no usable frames")

    # Regime filter — fetch SPY on daily bars regardless of backtest interval,
    # so the 200-day SMA is always meaningful.
    regime_df = pd.DataFrame()
    try:
        regime_df = feed.fetch_history(RISK.regime_symbol, start, end, interval="1d")
    except Exception as exc:  # noqa: BLE001
        _emit(f"  regime fetch failed ({RISK.regime_symbol}: {exc}) — running without regime filter")
    regime = RegimeFilter(regime_df)
    _emit(
        f"Regime: {RISK.regime_symbol} {RISK.regime_sma_period}D SMA "
        f"({'loaded' if regime.has_data() else 'disabled — no data'})"
    )
    bar_minutes = _BAR_MINUTES.get(interval, 1440)

    calendar = sorted({ts for df in enriched.values() for ts in df.index})
    _emit(
        f"Simulating {len(calendar):,} bars across {len(enriched)} symbols "
        f"(fetch+enrich took {time.time() - t0:.1f}s)"
    )

    broker = PaperBroker(starting_equity)
    risk = RiskManager(starting_equity)

    total_bars = len(calendar)
    checkpoint = max(total_bars // 20, 1)  # ~5% progress pings
    t_sim = time.time()

    for bar_idx, ts in enumerate(calendar):
        if bar_idx and bar_idx % checkpoint == 0:
            elapsed = time.time() - t_sim
            pct = 100 * bar_idx / total_bars
            rate = bar_idx / elapsed if elapsed else 0
            eta = (total_bars - bar_idx) / rate if rate else 0
            _emit(
                f"  sim {bar_idx:,}/{total_bars:,} bars ({pct:.0f}%) — "
                f"eq=${broker.equity():,.0f} trades={broker.resolved_trade_count()} "
                f"eta {eta:.0f}s"
            )

        today_prices: Dict[str, float] = {}
        for sym, df in enriched.items():
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
            elif RiskManager.is_dead(
                pos.entry_time, ts, pos.entry_price, price, bar_minutes=bar_minutes
            ):
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

        # --- regime overlay: block new entries when SPY < 200D ---
        if not regime.is_bull(ts):
            continue

        # --- scan entries ---
        slots = RISK.max_concurrent_positions - len(broker.positions())
        if slots <= 0:
            continue

        candidates = []
        for sym, df in enriched.items():
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
    losses = sum(1 for t in trades if t.pnl <= 0)
    win_rate = wins / len(trades) if trades else 0.0
    wl_ratio = (wins / losses) if losses else float(wins)
    total_cost = float(sum(t.entry_price * t.qty for t in trades))
    total_sale = float(sum(t.exit_price * t.qty for t in trades))
    total_pnl = float(sum(t.pnl for t in trades))

    return BacktestResult(
        starting_equity=starting_equity,
        ending_equity=broker.equity(),
        total_return_pct=total_ret,
        cagr_pct=float(cagr),
        max_drawdown_pct=_max_drawdown(curve),
        sharpe=_annualised_sharpe(curve),
        win_rate=win_rate,
        num_trades=len(trades),
        wins=wins,
        losses=losses,
        wl_ratio=wl_ratio,
        total_cost=total_cost,
        total_sale=total_sale,
        total_pnl=total_pnl,
        equity_curve=curve,
        trades=[t.as_row() for t in trades],
    )
