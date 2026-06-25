import pandas as pd

OHLCV_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]


def clean_ohlcv(rows):
    df = pd.DataFrame(rows, columns=OHLCV_COLUMNS)
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df.drop_duplicates("timestamp").sort_values("timestamp")
    df["sentiment"] = pd.NA
    return df.set_index("timestamp")
