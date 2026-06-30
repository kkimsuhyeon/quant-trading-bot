import json
import urllib.request

import pandas as pd


def fetch_fng(limit=0):
    """alternative.me Fear&Greed 일간 지수 → Series(일간 UTC 자정 → 0~100 float)."""
    url = f"https://api.alternative.me/fng/?limit={limit}&format=json"
    with urllib.request.urlopen(url, timeout=30) as r:
        data = json.load(r)["data"]
    idx = pd.to_datetime([int(x["timestamp"]) for x in data], unit="s", utc=True)
    return pd.Series([float(x["value"]) for x in data], index=idx).sort_index()


def attach_fng(df, fng):
    """OHLCV df의 sentiment 컬럼을 F&G로 채워 반환.
    D 값은 D+1부터 사용(인덱스 +1일 shift) → df 인덱스로 ffill → numeric float.
    df 시작 전 결측은 NaN(= 필터 off). 원본 df는 변경하지 않는다."""
    avail = fng.sort_index().copy()
    avail.index = avail.index + pd.Timedelta(days=1)           # D 값은 D+1 00:00 UTC부터 사용 가능
    s = avail.reindex(avail.index.union(df.index)).ffill().reindex(df.index)
    out = df.copy()
    out["sentiment"] = pd.to_numeric(s, errors="coerce").astype("float64")
    return out


def save_fng(s, path="data/fng.parquet"):
    import os
    os.makedirs("data", exist_ok=True)
    s.to_frame("fng").to_parquet(path)
    return path
