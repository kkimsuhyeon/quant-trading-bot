import numpy as np
import pandas as pd
from backtest import _to_backtesting_format, run_backtest
from strategies.sma_cross import SmaCross


def test_to_backtesting_format_renames_and_keeps_sentiment():
    df = pd.DataFrame({
        "open": [1.0], "high": [2.0], "low": [0.5], "close": [1.5],
        "volume": [100.0], "sentiment": [pd.NA],
    })
    out = _to_backtesting_format(df)
    assert {"Open", "High", "Low", "Close", "Volume"} <= set(out.columns)
    assert not ({"open", "high", "low", "close", "volume"} & set(out.columns))
    assert "sentiment" in out.columns


def _synthetic(n=500):
    idx = pd.date_range("2020-01-01", periods=n, freq="1h", tz="UTC")
    # 사인파로 여러 번 교차 유발 (fast=20, slow=50 SMA가 교차하려면 충분한 사이클 필요)
    t = np.linspace(0, 6 * np.pi, n)
    close = pd.Series(150 + 50 * np.sin(t), index=idx)
    return pd.DataFrame({
        "Open": close, "High": close * 1.01, "Low": close * 0.99,
        "Close": close, "Volume": 1000.0,
    }, index=idx)


def test_sma_cross_produces_trades():
    _, stats = run_backtest(_synthetic(), SmaCross)
    assert stats["# Trades"] > 0


def test_run_backtest_exposes_expected_stats():
    _, stats = run_backtest(_synthetic(), SmaCross)
    for key in ["Return [%]", "Sharpe Ratio", "Max. Drawdown [%]", "Win Rate [%]", "# Trades"]:
        assert key in stats.index
