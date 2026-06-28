import numpy as np
import pandas as pd
from robustness import train_test_split, time_segments, buy_hold, evaluate, param_sweep, walk_forward, METRIC_KEYS
from strategies.donchian_breakout import DonchianBreakout


def _price_df(n=100):
    idx = pd.date_range("2020-01-01", periods=n, freq="4h", tz="UTC")
    close = pd.Series(np.linspace(100, 200, n), index=idx)   # 단조 상승
    return pd.DataFrame({"Open": close, "High": close * 1.01, "Low": close * 0.99,
                         "Close": close, "Volume": 1000.0}, index=idx)


def test_train_test_split_ratio_and_order():
    df = _price_df(100)
    train, test = train_test_split(df, train_frac=0.7)
    assert len(train) == 70
    assert len(test) == 30
    assert len(train) + len(test) == len(df)        # 행 보존
    assert train.index[-1] < test.index[0]          # 시간순(누수 없음)


def test_time_segments_contiguous_cover():
    df = _price_df(100)
    segs = time_segments(df, k=5)
    assert len(segs) == 5
    assert sum(len(s) for s in segs) == len(df)     # 전부 커버, 중복 없음
    for a, b in zip(segs, segs[1:]):
        assert a.index[-1] < b.index[0]             # 연속


def test_buy_hold_return_and_mdd_monotone():
    df = _price_df(100)                              # 100 -> 200
    bh = buy_hold(df)
    assert round(bh["Return [%]"], 2) == 100.0
    assert round(bh["Max. Drawdown [%]"], 4) == 0.0


def test_buy_hold_drawdown_on_dip():
    idx = pd.date_range("2020-01-01", periods=3, freq="4h", tz="UTC")
    close = pd.Series([100.0, 50.0, 75.0], index=idx)   # 최저점 -50%
    df = pd.DataFrame({"Open": close, "High": close, "Low": close,
                       "Close": close, "Volume": 1000.0}, index=idx)
    assert round(buy_hold(df)["Max. Drawdown [%]"], 2) == -50.0


def test_metric_keys_exact():
    assert METRIC_KEYS == ["Return [%]", "Buy & Hold Return [%]", "Sharpe Ratio",
                           "Max. Drawdown [%]", "Win Rate [%]", "# Trades"]


def _oscillating(n=600):
    idx = pd.date_range("2020-01-01", periods=n, freq="4h", tz="UTC")
    close = pd.Series(120 + 40 * np.sin(np.linspace(0, 8 * np.pi, n)), index=idx)
    return pd.DataFrame({"Open": close, "High": close * 1.01, "Low": close * 0.99,
                         "Close": close, "Volume": 1000.0}, index=idx)


def test_evaluate_returns_metric_keys():
    m = evaluate(_oscillating(), DonchianBreakout)
    assert set(METRIC_KEYS) <= set(m)
    assert isinstance(m["Return [%]"], float)


def test_param_sweep_covers_grid():
    grid = {"entry_n": [10, 20], "exit_n": [5, 10]}
    out = param_sweep(_oscillating(), DonchianBreakout, grid)
    assert len(out) == 4                              # 2x2 데카르트곱
    assert {"entry_n", "exit_n"} <= set(out.columns)
    assert "Return [%]" in out.columns


def test_walk_forward_segments():
    out = walk_forward(_oscillating(), DonchianBreakout, k=3)
    assert len(out) == 3
    assert list(out["segment"]) == [0, 1, 2]
    assert {"start", "end"} <= set(out.columns)
    assert out["start"].iloc[0] < out["end"].iloc[-1]
