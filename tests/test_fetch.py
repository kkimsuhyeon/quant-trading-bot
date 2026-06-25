import pandas as pd
from fetch import clean_ohlcv, fetch_paginated


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


class FakeExchange:
    """since 이후 캔들을 limit개씩 돌려주는 가짜 거래소."""

    def __init__(self, rows):
        self._rows = sorted(rows)  # [[ts, o, h, l, c, v], ...]

    def fetch_ohlcv(self, symbol, timeframe, since, limit):
        return [r for r in self._rows if r[0] >= since][:limit]


def test_fetch_paginated_stitches_all_batches():
    rows = [[i * 3600_000, 1, 1, 1, 1, 1] for i in range(2500)]  # 2500개
    out = fetch_paginated(FakeExchange(rows), "BTC/USDT", "1h", since=0, limit=1000)
    assert len(out) == 2500                       # 누락 없이 전부
    assert [r[0] for r in out] == [r[0] for r in rows]  # 순서 유지
