import pandas as pd
from backtesting import Strategy


def SMA(series, n):
    return pd.Series(series).rolling(n).mean().values


class RegimeFilter(Strategy):
    sma_n = 200
    stop_loss_pct = 0.05
    use_sentiment = False

    def init(self):
        self.sma = self.I(SMA, self.data.Close, self.sma_n)

    def next(self):
        price = self.data.Close[-1]
        if not self.position:
            if price > self.sma[-1]:                # 장기 MA 위 → 보유
                self.buy(sl=price * (1 - self.stop_loss_pct))
        elif price < self.sma[-1]:                  # 장기 MA 아래 → 현금
            self.position.close()
