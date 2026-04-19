"""Market data feed. Uses yfinance for both live 15m bars and historical.

yfinance limits intraday ranges (e.g. 15m is ~60 days). For the 5-year
backtest we fetch daily bars and also pull as much intraday as Yahoo allows
into a local parquet cache under ./data/cache.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable

import pandas as pd
import yfinance as yf

log = logging.getLogger(__name__)

CACHE_DIR = Path(os.getenv("DATA_CACHE", "./data/cache"))
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _normalise(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.rename(
        columns={
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Adj Close": "adj_close",
            "Volume": "volume",
        }
    )
    keep = [c for c in ["open", "high", "low", "close", "volume"] if c in df.columns]
    df = df[keep].copy()
    df = df.dropna()
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    return df


def fetch_intraday(symbol: str, interval: str = "15m", period: str = "60d") -> pd.DataFrame:
    """Latest intraday bars for a single symbol (live scanning)."""
    try:
        df = yf.download(
            symbol,
            interval=interval,
            period=period,
            auto_adjust=False,
            progress=False,
            threads=False,
        )
    except Exception as e:  # noqa: BLE001
        log.warning("yfinance fetch failed for %s: %s", symbol, e)
        return pd.DataFrame()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return _normalise(df)


def fetch_batch(symbols: Iterable[str], interval: str = "15m", period: str = "60d") -> Dict[str, pd.DataFrame]:
    """Batch download for the scanner. Returns {symbol: df}."""
    syms = list(symbols)
    if not syms:
        return {}
    try:
        raw = yf.download(
            tickers=" ".join(syms),
            interval=interval,
            period=period,
            auto_adjust=False,
            progress=False,
            threads=True,
            group_by="ticker",
        )
    except Exception as e:  # noqa: BLE001
        log.warning("Batch fetch failed: %s", e)
        return {}

    out: Dict[str, pd.DataFrame] = {}
    if isinstance(raw.columns, pd.MultiIndex):
        for sym in syms:
            if sym in raw.columns.get_level_values(0):
                out[sym] = _normalise(raw[sym])
    else:
        out[syms[0]] = _normalise(raw)
    return out


def fetch_history(symbol: str, start: datetime, end: datetime, interval: str = "1d") -> pd.DataFrame:
    """Long-range history for backtesting. Cached on disk as parquet."""
    cache_key = CACHE_DIR / f"{symbol}_{interval}_{start.date()}_{end.date()}.parquet"
    if cache_key.exists():
        try:
            return pd.read_parquet(cache_key)
        except Exception:  # noqa: BLE001
            cache_key.unlink(missing_ok=True)
    try:
        df = yf.download(
            symbol,
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            interval=interval,
            auto_adjust=False,
            progress=False,
            threads=False,
        )
    except Exception as e:  # noqa: BLE001
        log.warning("History fetch failed for %s: %s", symbol, e)
        return pd.DataFrame()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = _normalise(df)
    if not df.empty:
        try:
            df.to_parquet(cache_key)
        except Exception as e:  # noqa: BLE001
            log.debug("Cache write failed for %s: %s", symbol, e)
    return df
