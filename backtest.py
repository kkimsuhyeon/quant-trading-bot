import pandas as pd
from backtesting.lib import FractionalBacktest


def _to_backtesting_format(df):
    return df.rename(columns={
        "open": "Open", "high": "High", "low": "Low",
        "close": "Close", "volume": "Volume",
    })


def load_data(symbol="BTC/USDT", timeframe="1h", data_dir="data"):
    name = f"{symbol.replace('/', '_')}_{timeframe}"
    df = pd.read_parquet(f"{data_dir}/{name}.parquet")
    return _to_backtesting_format(df)


def run_backtest(df, strategy, cash=10_000, commission=0.001, **params):
    bt = FractionalBacktest(
        df, strategy,
        cash=cash,
        commission=commission,   # 0.1% per side (거래소 수수료)
        spread=0.0,              # 슬리피지 미반영 (Phase 4 실측까지 보류)
        trade_on_close=False,    # 다음 봉 시가 체결 (룩어헤드 방지)
    )
    stats = bt.run(**params)
    return bt, stats


if __name__ == "__main__":
    from strategies.sma_cross import SmaCross
    df = load_data("BTC/USDT", "1h")
    bt, stats = run_backtest(df, SmaCross)
    print(stats)
