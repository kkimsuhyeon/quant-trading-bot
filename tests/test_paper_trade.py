import os
from datetime import timedelta
import numpy as np
import pandas as pd
from paper_trade import _to_live_df, desired_position, _params_repr, STRATEGIES
from paper_trade import _is_stale, _append_signals
from paper_trade import COLUMNS as COLUMNS_EXPECTED
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


def test_is_stale():
    now = pd.Timestamp("2026-01-02 00:00:00", tz="UTC")
    assert _is_stale(pd.Timestamp("2026-01-01 00:00:00", tz="UTC"), now) is True    # 24h 전 = stale
    assert _is_stale(pd.Timestamp("2026-01-01 20:00:00", tz="UTC"), now) is False   # 4h 전 = 정상


def test_append_signals_schema_and_idempotency(tmp_path):
    df = _to_live_df(_raw_rows(400))
    # df 마지막봉을 now 근처로 맞춰 stale 회피: now를 df 마지막봉 +4h로 설정
    now = df.index[-1] + timedelta(hours=4)
    csv = str(tmp_path / "signals.csv")
    rows1 = _append_signals(df, csv_path=csv, now=now)
    assert len(rows1) == 4                                  # 4전략
    saved = pd.read_csv(csv)
    assert list(saved.columns) == COLUMNS_EXPECTED
    assert set(saved["strategy"]) == {"keltner", "regime", "donchian", "sma_stop"}
    rows2 = _append_signals(df, csv_path=csv, now=now)      # 같은 봉 재실행
    assert rows2 == []                                      # 멱등: 중복 skip
    assert len(pd.read_csv(csv)) == 4                       # 행 수 그대로


def test_append_signals_dry_run_writes_nothing(tmp_path):
    df = _to_live_df(_raw_rows(400))
    now = df.index[-1] + timedelta(hours=4)
    csv = str(tmp_path / "signals.csv")
    rows = _append_signals(df, csv_path=csv, now=now, dry_run=True)
    assert len(rows) == 4
    assert not os.path.exists(csv)


def test_append_signals_stale_skips(tmp_path):
    df = _to_live_df(_raw_rows(400))
    now = df.index[-1] + timedelta(days=5)              # 너무 오래됨
    csv = str(tmp_path / "signals.csv")
    assert _append_signals(df, csv_path=csv, now=now) == []
    assert not os.path.exists(csv)
