import os
import sys
import fcntl
import pandas as pd
import ccxt
from backtest import run_backtest, _to_backtesting_format
from fetch import clean_ohlcv
from strategies.keltner_breakout import KeltnerBreakout
from strategies.regime_filter import RegimeFilter
from strategies.donchian_breakout import DonchianBreakout
from strategies.sma_cross_stop import SmaCrossWithStop

STRATEGIES = {
    "keltner": KeltnerBreakout,
    "regime": RegimeFilter,
    "donchian": DonchianBreakout,
    "sma_stop": SmaCrossWithStop,
}
SIGNALS_CSV = "paper/signals.csv"
LOCK_PATH = "paper/.lock"
COLUMNS = ["run_at", "symbol", "timeframe", "strategy", "signal_bar_time",
           "signal_bar_close", "desired_position", "source_rows", "lookback_bars", "strategy_params"]


def _to_live_df(rows):
    df = clean_ohlcv(rows)              # index=timestamp, ohlcv(+sentiment)
    if len(df) > 0:
        df = df.iloc[:-1]              # 마지막 미완성봉 제거 (fetch.py 규칙)
    return _to_backtesting_format(df)


def fetch_live(symbol="BTC/USDT", timeframe="4h", limit=1000, exchange=None):
    exchange = exchange or ccxt.binance()
    rows = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
    return _to_live_df(rows)


def desired_position(df, strategy):
    _, stats = run_backtest(df, strategy)
    return int(stats._strategy.position.size > 0)


def _params_repr(strategy):
    items = {k: v for k, v in vars(strategy).items()
             if not k.startswith("_") and isinstance(v, (int, float)) and not isinstance(v, bool)}
    return ",".join(f"{k}={v}" for k, v in sorted(items.items()))
