# Momentum Scalper Bot

A Python momentum scalper for US equities scanning a 64-symbol universe every
5 minutes on 15-minute candles. Ships with an event-driven 5-year backtester,
a live-simulated paper trader, a Robinhood live-trading adapter, and a real-time
Plotly/Dash dashboard.

## Strategy — 8-factor score (≥6/8 to enter)

| # | Factor                    | Check                                            |
|---|---------------------------|--------------------------------------------------|
| 1 | EMA stack                 | 5 EMA > 13 EMA > 34 EMA                          |
| 2 | Trend filter              | Close > 50 EMA                                   |
| 3 | VWAP crossover            | Close crossed / stays above session VWAP         |
| 4 | MACD histogram cross      | Histogram flipped negative → positive            |
| 5 | RSI                       | 50 < RSI < 82 (hard block above 82)              |
| 6 | ADX                       | ADX ≥ 25 (no chop)                               |
| 7 | Volume surge              | Last bar volume ≥ 2× 20-bar average              |
| 8 | Bollinger squeeze breakout| Width in bottom quartile → close > upper band    |

## Risk management

- 6% portfolio risk per trade (position sized from 1× ATR stop distance)
- ATR-based initial stop (1× ATR)
- Dynamic trailing stop: 1.8× ATR in calm tape, 2.5× ATR when ATR/price ≥ 3%
- Take-profit at 3× ATR
- Max 3 concurrent positions
- 15% drawdown circuit breaker (liquidates, pauses, resets peak)
- 90-minute time-stop if a position hasn't moved ≥ 0.5%
- Minimum $5 price filter

## Install

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env     # fill in Robinhood creds only for live mode
```

## Run

```bash
# Step 1 — 5-year backtest (daily bars, prints metrics)
python main.py backtest

# Step 2 — paper trading with $100k, dashboard on http://localhost:8050
python main.py paper

# Live Robinhood trading (requires RH_* env vars)
python main.py live
```

## Dashboard layout

```
┌ Equity │ Day PnL │ Total PnL │ Positions (open/resolved) │ Status ┐
├──────────────────────────────────┬───────────────────────────────┤
│  Equity Curve (time series)      │  Open Positions               │
│                                  │  ticker, qty, entry, current, │
│                                  │  PnL $ and %                  │
├──────────────────────────────────┼───────────────────────────────┤
│  Trade History                   │  Log Feed                     │
│  timestamps in/out, qty,         │  time-stamped scanner +       │
│  entry, exit, PnL $ and %        │  order messages               │
└──────────────────────────────────┴───────────────────────────────┘
```

## Layout

```
config.py                  # strategy + risk + runtime params
main.py                    # entry point (paper | live | backtest)
src/
  strategy/indicators.py   # EMA, VWAP, MACD, RSI, ADX, BB, ATR
  strategy/scoring.py      # 8-factor signal engine
  risk/manager.py          # sizing, stops, drawdown, time-stop
  broker/base.py           # broker interface + Position/Trade
  broker/paper.py          # in-memory paper broker (also powers backtest)
  broker/robinhood.py      # robin_stocks live wrapper
  data/feed.py             # yfinance intraday + cached history
  engine/trader.py         # scheduler tick: exits → entries
  backtest/runner.py       # event-driven 5-year backtest
  dashboard/app.py         # Dash UI
  dashboard/state.py       # thread-safe shared state
```

## Notes

- Historical intraday (15m) data is capped at ~60 days by Yahoo. The 5-year
  backtest therefore runs on daily bars by default — swap to an alternate
  data source and call `run_backtest(interval="15m")` for true-to-live replay.
- The dashboard auto-refreshes every 2 seconds; the scanner ticks every
  5 minutes per the strategy spec.
