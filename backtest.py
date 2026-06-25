import pandas as pd


def _to_backtesting_format(df):
    return df.rename(columns={
        "open": "Open", "high": "High", "low": "Low",
        "close": "Close", "volume": "Volume",
    })


def load_data(symbol="BTC/USDT", timeframe="1h", data_dir="data"):
    name = f"{symbol.replace('/', '_')}_{timeframe}"
    df = pd.read_parquet(f"{data_dir}/{name}.parquet")
    return _to_backtesting_format(df)
