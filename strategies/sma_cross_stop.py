import pandas as pd
from backtesting import Strategy
from backtesting.lib import crossover


def SMA(series, n):
    return pd.Series(series).rolling(n).mean().values


class SmaCrossWithStop(Strategy):
    fast = 20
    slow = 50
    stop_loss_pct = 0.05      # 신호 종가 기준 -5% proxy (실제 진입은 다음 봉 시가)
    use_sentiment = False

    def init(self):
        close = self.data.Close
        self.sma_fast = self.I(SMA, close, self.fast)
        self.sma_slow = self.I(SMA, close, self.slow)

    def next(self):
        price = self.data.Close[-1]
        if crossover(self.sma_fast, self.sma_slow):
            self.buy(sl=price * (1 - self.stop_loss_pct))
        elif crossover(self.sma_slow, self.sma_fast):
            self.position.close()
