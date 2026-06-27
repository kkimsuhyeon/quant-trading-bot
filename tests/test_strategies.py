import numpy as np
import pandas as pd
from backtest import run_backtest
from strategies.rsi_reversion import RsiReversion
from strategies.bollinger_reversion import BollingerReversion


def _dip_recover(n=150):
    """저변동 → 급락(과매도/밴드돌파) → 회복. 평균회귀 진입/청산을 유발."""
    idx = pd.date_range("2020-01-01", periods=n, freq="1h", tz="UTC")
    seg = np.concatenate([
        np.linspace(100, 102, 50),   # 완만 상승 (저변동 → 좁은 밴드)
        np.linspace(102, 72, 30),    # 급락 (RSI<30, 볼린저 하단 돌파)
        np.linspace(72, 108, 70),    # 회복 (RSI>50, 종가>중심선 → 청산)
    ])
    close = pd.Series(seg, index=idx)
    return pd.DataFrame({"Open": close, "High": close, "Low": close,
                         "Close": close, "Volume": 1000.0}, index=idx)


def test_rsi_reversion_trades_and_stats():
    _, stats = run_backtest(_dip_recover(), RsiReversion)
    assert stats["# Trades"] > 0
    for key in ["Return [%]", "Sharpe Ratio", "Max. Drawdown [%]", "# Trades"]:
        assert key in stats.index


def test_bollinger_reversion_trades_and_stats():
    _, stats = run_backtest(_dip_recover(), BollingerReversion)
    assert stats["# Trades"] > 0
    for key in ["Return [%]", "Sharpe Ratio", "Max. Drawdown [%]", "# Trades"]:
        assert key in stats.index
