import pandas as pd
from sentiment import attach_fng


def test_attach_fng_lags_one_day_ffill_and_float():
    # F&G: 01-01=10, 01-02=90 (일간 UTC 자정)
    fng = pd.Series([10.0, 90.0],
                    index=pd.to_datetime(["2021-01-01", "2021-01-02"], utc=True))
    idx = pd.date_range("2021-01-01", "2021-01-03 20:00", freq="4h", tz="UTC")
    df = pd.DataFrame({"Open": 1.0, "High": 1.0, "Low": 1.0, "Close": 1.0, "Volume": 1.0}, index=idx)

    out = attach_fng(df, fng)

    # 01-01 봉: 01-01 값은 01-02부터 사용 → 아직 없음 → NaN (필터 off)
    assert pd.isna(out.loc["2021-01-01 12:00", "sentiment"])
    # 01-02 봉: 01-01 값(01-02 00:00부터 사용) → 10
    assert out.loc["2021-01-02 12:00", "sentiment"] == 10.0
    # 01-03 봉: 01-02 값(01-03 00:00부터 사용) → 90
    assert out.loc["2021-01-03 12:00", "sentiment"] == 90.0
    assert out["sentiment"].dtype == "float64"
    # 원본 df는 안 바뀜
    assert "sentiment" not in df.columns
