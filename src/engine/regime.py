"""Regime filter: block new entries when the broad market is below trend.

Uses SPY vs its 200-day SMA by default. When SPY < SMA we stay flat-to-cash
(existing positions are still managed and can be stopped out) — this kills
the worst drawdowns without thinning the signal set.

Permissive fallback: if SPY data is unavailable or the history isn't deep
enough to form a 200-day SMA, is_bull() returns True so the system doesn't
freeze in the absence of data.
"""
from __future__ import annotations

import logging
from typing import Optional

import pandas as pd

from config import RISK

log = logging.getLogger(__name__)


class RegimeFilter:
    def __init__(self, spy_df: Optional[pd.DataFrame] = None, sma_period: Optional[int] = None):
        period = sma_period or RISK.regime_sma_period
        self._period = period
        if spy_df is None or spy_df.empty or "close" not in spy_df.columns:
            self._close = pd.Series(dtype=float)
            self._sma = pd.Series(dtype=float)
        else:
            close = spy_df["close"].astype(float).sort_index()
            self._close = close
            self._sma = close.rolling(period, min_periods=period).mean()

    def has_data(self) -> bool:
        return not self._close.empty

    def is_bull(self, ts: Optional[pd.Timestamp] = None) -> bool:
        """True if SPY is at or above its N-day SMA at (or before) ``ts``."""
        if self._close.empty:
            return True  # no data -> permissive
        if ts is None:
            spot = float(self._close.iloc[-1])
            sma = float(self._sma.iloc[-1]) if not self._sma.empty else float("nan")
        else:
            close_slice = self._close.loc[:ts]
            sma_slice = self._sma.loc[:ts]
            if close_slice.empty:
                return True
            spot = float(close_slice.iloc[-1])
            sma = float(sma_slice.iloc[-1]) if not sma_slice.empty else float("nan")
        if pd.isna(sma):
            return True  # not enough history yet
        return spot >= sma

    def snapshot(self, ts: Optional[pd.Timestamp] = None) -> dict:
        """Structured state for logging."""
        if self._close.empty:
            return {"bull": True, "reason": "no-data"}
        bull = self.is_bull(ts)
        if ts is None:
            spot = float(self._close.iloc[-1])
            sma = float(self._sma.iloc[-1]) if not self._sma.empty else float("nan")
        else:
            spot = float(self._close.loc[:ts].iloc[-1])
            sma_slice = self._sma.loc[:ts]
            sma = float(sma_slice.iloc[-1]) if not sma_slice.empty else float("nan")
        return {"bull": bull, "spot": spot, "sma": sma, "period": self._period}
