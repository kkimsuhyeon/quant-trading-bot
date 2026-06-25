import pandas as pd
from fetch import clean_ohlcv


def _rows(ts_list):
    return [[ts, 10, 12, 9, 11, 100] for ts in ts_list]


def test_clean_ohlcv_schema():
    df = clean_ohlcv(_rows([0, 3600_000, 7200_000]))
    assert list(df.columns) == ["open", "high", "low", "close", "volume", "sentiment"]
    assert df.index.name == "timestamp"
    assert str(df.index.tz) == "UTC"


def test_clean_ohlcv_dedups_and_sorts():
    df = clean_ohlcv(_rows([7200_000, 0, 0, 3600_000]))  # 중복(0) + 역순
    ts = [int(t.timestamp() * 1000) for t in df.index]
    assert ts == [0, 3600_000, 7200_000]


def test_clean_ohlcv_sentiment_is_na():
    df = clean_ohlcv(_rows([0, 3600_000]))
    assert df["sentiment"].isna().all()
