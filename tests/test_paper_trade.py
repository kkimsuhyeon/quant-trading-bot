import numpy as np
import pandas as pd
from paper_trade import _to_live_df, desired_position, _params_repr, STRATEGIES
from strategies.regime_filter import RegimeFilter


def _raw_rows(n=400):
    # ccxt 형식 raw rows: [ts_ms, o, h, l, c, v]. 마지막 200봉 상승(끝 롱 유발).
    closes = np.concatenate([np.linspace(100, 80, 200), np.linspace(80, 160, 200)])
    base = 1_600_000_000_000
    return [[base + i * 4 * 3600 * 1000, c, c * 1.01, c * 0.99, c, 1000.0]
            for i, c in enumerate(closes[:n])]


def test_to_live_df_drops_incomplete_and_formats():
    rows = _raw_rows(10)
    out = _to_live_df(rows)
    assert len(out) == 9                      # 마지막 미완성봉 제거
    assert {"Open", "High", "Low", "Close", "Volume"} <= set(out.columns)


def test_desired_position_long_when_uptrend_end():
    df = _to_live_df(_raw_rows(400))          # 끝이 상승 → SMA200 위 → 롱
    assert desired_position(df, RegimeFilter) == 1


def test_desired_position_flat_when_downtrend_end():
    closes = np.linspace(200, 80, 400)        # 단조 하락 → 끝 현금
    base = 1_600_000_000_000
    rows = [[base + i * 4 * 3600 * 1000, c, c * 1.01, c * 0.99, c, 1000.0]
            for i, c in enumerate(closes)]
    df = _to_live_df(rows)
    assert desired_position(df, RegimeFilter) == 0


def test_params_repr_excludes_sentiment():
    r = _params_repr(RegimeFilter)
    assert "sma_n=200" in r
    assert "use_sentiment" not in r


def test_strategies_has_four():
    assert set(STRATEGIES) == {"keltner", "regime", "donchian", "sma_stop"}
