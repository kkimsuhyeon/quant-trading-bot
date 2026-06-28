import numpy as np
import pandas as pd
from backtest import run_backtest
from strategies.sma_cross_stop import SmaCrossWithStop

STATS_KEYS = ["Return [%]", "Sharpe Ratio", "Max. Drawdown [%]", "# Trades"]


def _oscillating(n=500):
    idx = pd.date_range("2020-01-01", periods=n, freq="4h", tz="UTC")
    close = pd.Series(120 + 40 * np.sin(np.linspace(0, 8 * np.pi, n)), index=idx)
    return pd.DataFrame({"Open": close, "High": close * 1.01, "Low": close * 0.99,
                         "Close": close, "Volume": 1000.0}, index=idx)


def test_sma_stop_trades_and_stats():
    _, stats = run_backtest(_oscillating(), SmaCrossWithStop)
    assert stats["# Trades"] > 0
    for k in STATS_KEYS:
        assert k in stats.index


def test_sma_stop_has_stop_loss_param():
    assert SmaCrossWithStop.stop_loss_pct == 0.05
