"""Central configuration for the Momentum Scalper Bot.

All strategy parameters, risk limits, and runtime knobs live here.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List

from dotenv import load_dotenv

load_dotenv()


UNIVERSE: List[str] = [
    # Crypto-adjacent / brokers
    "MSTR", "COIN", "HOOD", "RIOT", "MARA", "HUT",
    # Semis / mega-caps
    "NVDA", "AMD", "SMCI", "AVGO", "ARM", "QCOM", "MU", "INTC", "MRVL",
    # High-beta tech leaders
    "TSLA", "PLTR", "SNOW", "NET", "DDOG", "CRWD", "ZS", "GTLB", "PATH",
    # AI small/mid-caps
    "AI", "BBAI", "SOUN",
    # EV / clean energy
    "RIVN", "LCID", "NIO", "XPEV", "CHPT", "PLUG", "FSLR",
    # Space / eVTOL
    "RKLB", "LUNR", "ASTS", "ACHR", "JOBY",
    # Quantum
    "IONQ", "RGTI", "QUBT",
    # Biotech
    "RXRX", "BEAM", "EDIT", "NTLA",
    # Fintech / consumer
    "SOFI", "AFRM", "UPST", "NU",
    # Meme / retail favorites
    "GME", "AMC", "BBBY",
    # Mega caps
    "META", "AMZN", "GOOG", "NFLX", "SHOP", "PYPL",
    # Leveraged ETFs for volatility plays
    "TQQQ", "SOXL", "LABU", "FNGU", "UVXY",
]


@dataclass(frozen=True)
class StrategyConfig:
    # Timeframe
    candle_interval: str = "15m"
    scan_interval_minutes: int = 5

    # EMA stack
    ema_fast: int = 5
    ema_mid: int = 13
    ema_slow: int = 34
    ema_trend: int = 50

    # MACD
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9

    # RSI
    rsi_period: int = 14
    rsi_block: float = 82.0

    # ADX
    adx_period: int = 14
    adx_min: float = 25.0

    # Volume surge
    vol_lookback: int = 20
    vol_surge_mult: float = 2.0

    # Bollinger
    bb_period: int = 20
    bb_std: float = 2.0
    bb_squeeze_lookback: int = 50  # squeeze quantile window

    # ATR / stops
    atr_period: int = 14

    # Filters
    min_price: float = 5.0

    # Scoring
    min_score_to_enter: int = 6  # out of 8


@dataclass(frozen=True)
class RiskConfig:
    # Sizing
    target_vol_pct: float = 0.01               # target $vol per ATR = 1% of equity
    portfolio_risk_pct: float = 0.08           # hard loss ceiling per trade
    atr_stop_mult: float = 1.5                 # initial stop = 1.5x ATR (give room)
    # Trailing stop — widened so winners breathe
    trail_mult_low_vol: float = 2.5            # was 1.8
    trail_mult_high_vol: float = 3.5           # was 2.5
    vol_regime_atr_pct: float = 0.03           # >3% ATR/price => high vol
    take_profit_mult: float = 3.5              # 3.5x ATR target (was 3.0)
    max_concurrent_positions: int = 3
    max_position_notional_pct: float = 0.33    # <= equity / max_positions per name
    max_drawdown_pct: float = 0.15             # 15% circuit breaker
    # Time-stop — bar-aware so daily backtests don't fire every bar
    time_stop_bars: int = 8                    # check inactivity after N bars
    time_stop_min_move_pct: float = 0.015      # kill if move < 1.5% after window
    # Regime overlay: block new entries when SPY < 200D SMA
    regime_symbol: str = "SPY"
    regime_sma_period: int = 200


@dataclass(frozen=True)
class RuntimeConfig:
    mode: str = field(default_factory=lambda: os.getenv("MODE", "paper"))
    starting_equity: float = field(
        default_factory=lambda: float(os.getenv("STARTING_EQUITY", "100000"))
    )
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))
    dashboard_port: int = field(
        default_factory=lambda: int(os.getenv("DASHBOARD_PORT", "8050"))
    )
    tz: str = "America/New_York"


STRATEGY = StrategyConfig()
RISK = RiskConfig()
RUNTIME = RuntimeConfig()
