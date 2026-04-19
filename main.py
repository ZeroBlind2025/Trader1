"""Entry point for the Momentum Scalper Bot.

Usage:
    python main.py paper        # live-simulated paper trading + dashboard
    python main.py live         # Robinhood live trading + dashboard
    python main.py backtest     # 5-year daily backtest (no dashboard)
    python main.py dashboard    # dashboard only (reads shared state)
"""
from __future__ import annotations

import argparse
import logging
import sys
import threading
import time

from apscheduler.schedulers.background import BackgroundScheduler

from config import RUNTIME, STRATEGY
from src.broker.paper import PaperBroker
from src.dashboard.app import build_app
from src.dashboard.state import DashboardState
from src.engine.trader import Trader
from src.risk.manager import RiskManager


def _setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _make_broker(mode: str, equity: float):
    if mode == "live":
        from src.broker.robinhood import RobinhoodBroker
        return RobinhoodBroker(equity)
    return PaperBroker(equity)


def run_trading(mode: str) -> None:
    _setup_logging(RUNTIME.log_level)
    log = logging.getLogger("main")

    state = DashboardState()
    broker = _make_broker(mode, RUNTIME.starting_equity)
    risk = RiskManager(RUNTIME.starting_equity)
    trader = Trader(broker, risk, dashboard_state=state)

    state.set_day_start(broker.equity())
    trader._log(f"Bot starting in {mode.upper()} mode; equity=${broker.equity():,.2f}")

    scheduler = BackgroundScheduler(timezone=RUNTIME.tz)
    scheduler.add_job(trader.tick, "interval", minutes=STRATEGY.scan_interval_minutes, id="scan")
    scheduler.start()

    # Run an immediate tick so the dashboard is populated on boot.
    def _kickstart():
        try:
            trader.tick()
        except Exception as e:  # noqa: BLE001
            log.exception("Initial tick failed: %s", e)

    threading.Thread(target=_kickstart, daemon=True).start()

    app = build_app(state)
    try:
        app.run(host="0.0.0.0", port=RUNTIME.dashboard_port, debug=False)
    finally:
        scheduler.shutdown(wait=False)


def run_backtest() -> None:
    _setup_logging(RUNTIME.log_level)
    from src.backtest.runner import run_backtest as _bt

    result = _bt(starting_equity=RUNTIME.starting_equity, years=5, interval="1d")
    print("\n==== 5-Year Backtest Results ====")
    print(f"Starting equity : ${result.starting_equity:,.0f}")
    print(f"Ending equity   : ${result.ending_equity:,.0f}")
    print(f"Total return    : {result.total_return_pct*100:.2f}%")
    print(f"CAGR            : {result.cagr_pct*100:.2f}%")
    print(f"Max drawdown    : {result.max_drawdown_pct*100:.2f}%")
    print(f"Sharpe (ann)    : {result.sharpe:.2f}")
    print(f"Trades          : {result.num_trades} (win rate {result.win_rate*100:.1f}%)")
    print("=================================\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Momentum Scalper Bot")
    parser.add_argument(
        "mode",
        nargs="?",
        default=RUNTIME.mode,
        choices=["paper", "live", "backtest"],
        help="Runtime mode (default from MODE env var)",
    )
    args = parser.parse_args()

    if args.mode == "backtest":
        run_backtest()
    else:
        run_trading(args.mode)


if __name__ == "__main__":
    main()
