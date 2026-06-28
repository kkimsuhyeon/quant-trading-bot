import pandas as pd

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
