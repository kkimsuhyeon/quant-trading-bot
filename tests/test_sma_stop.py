import numpy as np
import pandas as pd
from backtest import run_backtest
from strategies.sma_cross_stop import SmaCrossWithStop
from strategies.sma_cross import SmaCross

STATS_KEYS = ["Return [%]", "Sharpe Ratio", "Max. Drawdown [%]", "# Trades"]


def _oscillating(n=500):
    idx = pd.date_range("2020-01-01", periods=n, freq="4h", tz="UTC")
    close = pd.Series(120 + 40 * np.sin(np.linspace(0, 8 * np.pi, n)), index=idx)
    return pd.DataFrame({"Open": close, "High": close * 1.01, "Low": close * 0.99,
                         "Close": close, "Volume": 1000.0}, index=idx)


def _crash_after_cross(n=120):
    # 하락→상승(골든크로스 유발)→급락(손절 발동)
    idx = pd.date_range("2020-01-01", periods=n, freq="4h", tz="UTC")
    close = pd.Series(
        np.concatenate([np.linspace(100, 90, 60),   # fast가 slow 아래로
                        np.linspace(90, 140, 30),    # 골든크로스 → 진입
                        np.linspace(140, 70, 30)]),  # 급락 → 손절 터짐
        index=idx)
    return pd.DataFrame({"Open": close, "High": close * 1.01, "Low": close * 0.99,
                         "Close": close, "Volume": 1000.0}, index=idx)


def test_sma_stop_trades_and_stats():
    _, stats = run_backtest(_oscillating(), SmaCrossWithStop)
    assert stats["# Trades"] > 0
    for k in STATS_KEYS:
        assert k in stats.index


def test_sma_stop_has_stop_loss_param():
    assert SmaCrossWithStop.stop_loss_pct == 0.05


def test_stop_limits_loss_vs_no_stop():
    data = _crash_after_cross()
    _, s_stop = run_backtest(data, SmaCrossWithStop)
    _, s_nostop = run_backtest(data, SmaCross)
    # 손절 있는 쪽 낙폭이 더 얕아야(덜 음수) = 손절이 실제로 손실을 막았다
    assert s_stop["Max. Drawdown [%]"] > s_nostop["Max. Drawdown [%]"]
