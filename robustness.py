import itertools

import pandas as pd

from backtest import run_backtest

METRIC_KEYS = ["Return [%]", "Buy & Hold Return [%]", "Sharpe Ratio",
               "Max. Drawdown [%]", "Win Rate [%]", "# Trades"]


def train_test_split(df, train_frac=0.7):
    n = int(len(df) * train_frac)
    return df.iloc[:n], df.iloc[n:]


def time_segments(df, k=5):
    bounds = [len(df) * i // k for i in range(k + 1)]
    return [df.iloc[bounds[i]:bounds[i + 1]] for i in range(k)]


def buy_hold(df):
    close = df["Close"]
    ret = (close.iloc[-1] / close.iloc[0] - 1) * 100
    mdd = (close / close.cummax() - 1).min() * 100
    return {"Return [%]": ret, "Max. Drawdown [%]": mdd}


def evaluate(df, strategy, metric_keys=METRIC_KEYS, **params):
    _, stats = run_backtest(df, strategy, **params)
    return {k: stats[k] for k in metric_keys}


def param_sweep(df, strategy, param_grid, metric_keys=METRIC_KEYS, **fixed):
    keys = list(param_grid)
    rows = []
    for combo in itertools.product(*(param_grid[k] for k in keys)):
        params = dict(zip(keys, combo))
        rows.append({**params, **evaluate(df, strategy, metric_keys, **{**fixed, **params})})
    return pd.DataFrame(rows)


def walk_forward(df, strategy, k=5, metric_keys=METRIC_KEYS, **params):
    rows = []
    for i, seg in enumerate(time_segments(df, k)):
        m = evaluate(seg, strategy, metric_keys, **params)
        rows.append({"segment": i, "start": seg.index[0], "end": seg.index[-1], **m})
    return pd.DataFrame(rows)
