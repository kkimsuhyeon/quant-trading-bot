import pandas as pd
from backtest import run_backtest


def equity_curve(df, strategy, **params):
    _, stats = run_backtest(df, strategy, **params)
    return stats["_equity_curve"]["Equity"]


def per_coin_equity(data_by_symbol, strategy, **params):
    cols = {sym: equity_curve(df, strategy, **params) for sym, df in data_by_symbol.items()}
    return pd.DataFrame(cols)
