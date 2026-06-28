import numpy as np
import pandas as pd
from backtest import run_backtest
from strategies.keltner_breakout import KeltnerBreakout
from strategies.regime_filter import RegimeFilter
from strategies.zscore_reversion import ZScoreReversion

STATS_KEYS = ["Return [%]", "Sharpe Ratio", "Max. Drawdown [%]", "# Trades"]


def _trending(n=600):
    """추세성 있는 사인파: Keltner 상단 밴드 돌파 유발."""
    idx = pd.date_range("2020-01-01", periods=n, freq="1h", tz="UTC")
    # 완만한 우상향 추세 + 큰 진폭의 사인파 → EMA 위로 강하게 돌파하는 구간 발생
    t = np.linspace(0, 6 * np.pi, n)
    close = pd.Series(200 + 0.1 * np.arange(n) + 60 * np.sin(t), index=idx)
    return pd.DataFrame({
        "Open": close,
        "High": close * 1.015,
        "Low": close * 0.985,
        "Close": close,
        "Volume": 1000.0,
    }, index=idx)


def _regime(n=800):
    """SMA200 기준 위/아래를 왕복하는 사인파: RegimeFilter 진입·청산 반복 유발."""
    idx = pd.date_range("2020-01-01", periods=n, freq="1h", tz="UTC")
    # 기준선 200, 진폭 80 → 가격이 200 위아래를 충분히 오감
    t = np.linspace(0, 8 * np.pi, n)
    close = pd.Series(200 + 80 * np.sin(t), index=idx)
    return pd.DataFrame({
        "Open": close,
        "High": close * 1.005,
        "Low": close * 0.995,
        "Close": close,
        "Volume": 1000.0,
    }, index=idx)


def _mean_reverting(n=600):
    """z < -2 진입 구간이 여러 번 발생하는 사인파: ZScoreReversion 유발."""
    idx = pd.date_range("2020-01-01", periods=n, freq="1h", tz="UTC")
    # 진폭 클수록 z-score 극단 더 자주 발생 — 윈도우 20 기준 -2σ 돌파 필요
    t = np.linspace(0, 10 * np.pi, n)
    close = pd.Series(100 + 30 * np.sin(t), index=idx)
    return pd.DataFrame({
        "Open": close,
        "High": close * 1.01,
        "Low": close * 0.99,
        "Close": close,
        "Volume": 1000.0,
    }, index=idx)


# ──────────────── KeltnerBreakout ────────────────

def test_keltner_trades_and_stats():
    _, stats = run_backtest(_trending(), KeltnerBreakout)
    assert stats["# Trades"] > 0
    for k in STATS_KEYS:
        assert k in stats.index


def test_keltner_has_stop_loss_param():
    assert hasattr(KeltnerBreakout, "stop_loss_pct")


# ──────────────── RegimeFilter ────────────────

def test_regime_trades_and_stats():
    _, stats = run_backtest(_regime(), RegimeFilter)
    assert stats["# Trades"] > 0
    for k in STATS_KEYS:
        assert k in stats.index


def test_regime_has_stop_loss_param():
    assert hasattr(RegimeFilter, "stop_loss_pct")


# ──────────────── ZScoreReversion ────────────────

def test_zscore_trades_and_stats():
    _, stats = run_backtest(_mean_reverting(), ZScoreReversion)
    assert stats["# Trades"] > 0
    for k in STATS_KEYS:
        assert k in stats.index


def test_zscore_has_stop_loss_param():
    assert hasattr(ZScoreReversion, "stop_loss_pct")
