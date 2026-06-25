import pandas as pd
from backtest import _to_backtesting_format


def test_to_backtesting_format_renames_and_keeps_sentiment():
    df = pd.DataFrame({
        "open": [1.0], "high": [2.0], "low": [0.5], "close": [1.5],
        "volume": [100.0], "sentiment": [pd.NA],
    })
    out = _to_backtesting_format(df)
    assert {"Open", "High", "Low", "Close", "Volume"} <= set(out.columns)
    assert not ({"open", "high", "low", "close", "volume"} & set(out.columns))
    assert "sentiment" in out.columns
