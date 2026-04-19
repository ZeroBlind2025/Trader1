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
    portfolio_risk_pct: float = 0.06           # 6% per trade
    atr_stop_mult: float = 1.0                 # initial stop = 1x ATR
    trail_mult_low_vol: float = 1.8            # tight trail in calm tape
    trail_mult_high_vol: float = 2.5           # wide trail when ATR% elevated
    vol_regime_atr_pct: float = 0.03           # >3% ATR/price => high vol
    take_profit_mult: float = 3.0              # 3x ATR target
    max_concurrent_positions: int = 3
    max_drawdown_pct: float = 0.15             # 15% circuit breaker
    time_stop_minutes: int = 90                # kill dead positions


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
