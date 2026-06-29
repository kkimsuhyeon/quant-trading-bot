import ccxt
import pandas as pd

OHLCV_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]


def clean_ohlcv(rows):
    df = pd.DataFrame(rows, columns=OHLCV_COLUMNS)
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df.drop_duplicates("timestamp").sort_values("timestamp")
    df["sentiment"] = pd.NA
    return df.set_index("timestamp")


def fetch_paginated(exchange, symbol, timeframe, since, limit=1000):
    all_rows = []
    while True:
        batch = exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=limit)
        if not batch:
            break
        all_rows += batch
        since = batch[-1][0] + 1          # 다음 페이지: 마지막 캔들 다음부터
        if len(batch) < limit:
            break                          # 더 받을 게 없음
    return all_rows


def fetch_ohlcv(symbol="BTC/USDT", timeframe="1h", years=5, exchange=None):
    exchange = exchange or ccxt.binance()
    since = exchange.milliseconds() - years * 365 * 24 * 60 * 60 * 1000
    rows = fetch_paginated(exchange, symbol, timeframe, since)
    df = clean_ohlcv(rows)
    if len(df) > 0:
        df = df.iloc[:-1]                  # 미완성 마지막 캔들 제거
    return df


def save(df, symbol, timeframe, data_dir="data"):
    import os
    os.makedirs(data_dir, exist_ok=True)
    name = f"{symbol.replace('/', '_')}_{timeframe}"
    df.to_parquet(f"{data_dir}/{name}.parquet")
    df.to_csv(f"{data_dir}/{name}.csv")
    return name


def fetch_funding(symbol="BTC/USDT:USDT", years=5, exchange=None):
    """무기한 선물 펀딩비 히스토리(8h). symbol은 linear perp 형식(예 'BTC/USDT:USDT')."""
    exchange = exchange or ccxt.binance()
    since = exchange.milliseconds() - years * 365 * 24 * 60 * 60 * 1000
    rows = []
    while True:
        batch = exchange.fetch_funding_rate_history(symbol, since=since, limit=1000)
        if not batch:
            break
        rows += batch
        nxt = batch[-1]["timestamp"] + 1   # 다음 페이지
        if nxt <= since:
            break
        since = nxt
        if len(batch) < 1000:
            break
    df = pd.DataFrame([{"timestamp": pd.to_datetime(r["timestamp"], unit="ms", utc=True),
                        "fundingRate": float(r["fundingRate"])} for r in rows])
    return df.drop_duplicates("timestamp").sort_values("timestamp").set_index("timestamp")


def save_funding(df, coin, data_dir="data"):
    import os
    os.makedirs(data_dir, exist_ok=True)
    df.to_parquet(f"{data_dir}/{coin}_USDT_funding.parquet")
    return f"{coin}_USDT_funding"


if __name__ == "__main__":
    for symbol in ["BTC/USDT", "ETH/USDT"]:
        for tf in ["1h", "4h"]:
            df = fetch_ohlcv(symbol, tf, years=5)
            save(df, symbol, tf)
            print(f"{symbol} {tf}: {len(df)} candles, {df.index[0]} ~ {df.index[-1]}")

    for coin in ["BTC", "ETH"]:                       # Phase 7b 캐리용 펀딩비(perp)
        fdf = fetch_funding(f"{coin}/USDT:USDT", years=5)
        save_funding(fdf, coin)
        print(f"{coin} funding: {len(fdf)} pts, {fdf.index[0]} ~ {fdf.index[-1]}")
