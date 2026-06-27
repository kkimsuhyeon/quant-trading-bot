import numpy as np
import pandas as pd
from backtest import run_backtest
from strategies.donchian_breakout import DonchianBreakout, DONCHIAN_HIGH, DONCHIAN_LOW

STATS_KEYS = ["Return [%]", "Sharpe Ratio", "Max. Drawdown [%]", "# Trades"]


def _oscillating(n=500):
    """진폭 큰 사인파: 추세/모멘텀 전략의 진입·청산을 반복 유발."""
    idx = pd.date_range("2020-01-01", periods=n, freq="1h", tz="UTC")
    close = pd.Series(120 + 40 * np.sin(np.linspace(0, 8 * np.pi, n)), index=idx)
    return pd.DataFrame({"Open": close, "High": close * 1.01, "Low": close * 0.99,
                         "Close": close, "Volume": 1000.0}, index=idx)


def test_donchian_trades_and_stats():
    _, stats = run_backtest(_oscillating(), DonchianBreakout)
    assert stats["# Trades"] > 0
    for k in STATS_KEYS:
        assert k in stats.index


def test_donchian_channels_exclude_current_bar():
    # 룩어헤드 가드: 채널은 현재 봉을 제외한 과거 n봉으로 계산되어야 한다.
    high = [10, 11, 12, 100]
    low = [10, 9, 8, 1]
    assert DONCHIAN_HIGH(high, 3)[-1] == 12   # 현재 봉의 100이 섞이면 안 됨
    assert DONCHIAN_LOW(low, 3)[-1] == 8      # 현재 봉의 1이 섞이면 안 됨
