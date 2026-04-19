"""8-factor momentum scoring engine.

Factors (each worth 1 point, max 8):
    1. EMA stack: 5 > 13 > 34
    2. Trend filter: close > 50 EMA
    3. VWAP crossover: close > VWAP (and crossed up recently)
    4. MACD histogram cross: hist flips negative -> positive
    5. RSI: 50 < RSI < 82 (block hard above 82)
    6. ADX >= 25 (trend strength, no chop)
    7. Volume surge: last bar volume >= 2x 20-bar avg
    8. Bollinger squeeze breakout: width was in lowest quantile recently
       and close breaks above upper band.

Entry requires score >= STRATEGY.min_score_to_enter AND RSI < rsi_block.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

import numpy as np
import pandas as pd

from config import STRATEGY
from . import indicators as ind


@dataclass
class Signal:
    symbol: str
    timestamp: pd.Timestamp
    score: int
    factors: Dict[str, bool]
    price: float
    atr: float
    rsi: float
    adx: float
    enter: bool


def _enrich(df: pd.DataFrame) -> pd.DataFrame:
    """Attach all indicator columns to the dataframe."""
    out = df.copy()
    out["ema_fast"] = ind.ema(out["close"], STRATEGY.ema_fast)
    out["ema_mid"] = ind.ema(out["close"], STRATEGY.ema_mid)
    out["ema_slow"] = ind.ema(out["close"], STRATEGY.ema_slow)
    out["ema_trend"] = ind.ema(out["close"], STRATEGY.ema_trend)
    out["vwap"] = ind.vwap(out)
    macd_df = ind.macd(out["close"], STRATEGY.macd_fast, STRATEGY.macd_slow, STRATEGY.macd_signal)
    out["macd_hist"] = macd_df["hist"]
    out["rsi"] = ind.rsi(out["close"], STRATEGY.rsi_period)
    out["adx"] = ind.adx(out, STRATEGY.adx_period)
    out["atr"] = ind.atr(out, STRATEGY.atr_period)
    out["vol_sma"] = ind.volume_sma(out["volume"], STRATEGY.vol_lookback)
    bb = ind.bollinger(out["close"], STRATEGY.bb_period, STRATEGY.bb_std)
    out["bb_upper"] = bb["upper"]
    out["bb_width"] = bb["width"]
    out["bb_squeeze"] = (
        out["bb_width"]
        <= out["bb_width"]
        .rolling(STRATEGY.bb_squeeze_lookback, min_periods=STRATEGY.bb_squeeze_lookback // 2)
        .quantile(0.25)
    )
    return out


def evaluate(symbol: str, df: pd.DataFrame) -> Signal | None:
    """Score the latest bar for ``symbol``. Returns None if data insufficient."""
    if df is None or len(df) < max(
        STRATEGY.ema_trend, STRATEGY.bb_squeeze_lookback, STRATEGY.adx_period * 3
    ):
        return None

    e = _enrich(df)
    last = e.iloc[-1]
    prev = e.iloc[-2]

    if last[["ema_fast", "ema_mid", "ema_slow", "ema_trend", "rsi", "adx", "atr"]].isna().any():
        return None

    factors: Dict[str, bool] = {
        "ema_stack": bool(last["ema_fast"] > last["ema_mid"] > last["ema_slow"]),
        "trend": bool(last["close"] > last["ema_trend"]),
        "vwap_cross": bool(last["close"] > last["vwap"] and prev["close"] <= prev["vwap"])
        or bool(last["close"] > last["vwap"] and last["ema_fast"] > last["vwap"]),
        "macd_hist_cross": bool(last["macd_hist"] > 0 and prev["macd_hist"] <= 0),
        "rsi_ok": bool(50.0 < last["rsi"] < STRATEGY.rsi_block),
        "adx_trending": bool(last["adx"] >= STRATEGY.adx_min),
        "volume_surge": bool(
            not np.isnan(last["vol_sma"])
            and last["volume"] >= STRATEGY.vol_surge_mult * last["vol_sma"]
        ),
        "bb_squeeze_break": bool(
            bool(prev["bb_squeeze"]) and last["close"] > last["bb_upper"]
        ),
    }

    score = sum(1 for v in factors.values() if v)
    hard_block = last["rsi"] >= STRATEGY.rsi_block or last["close"] < 0
    enter = (score >= STRATEGY.min_score_to_enter) and not hard_block

    return Signal(
        symbol=symbol,
        timestamp=last.name,
        score=score,
        factors=factors,
        price=float(last["close"]),
        atr=float(last["atr"]),
        rsi=float(last["rsi"]),
        adx=float(last["adx"]),
        enter=bool(enter),
    )
