import pandas as pd
from backtesting import Strategy


def MOMENTUM(close, n):
    s = pd.Series(close)
    return (s / s.shift(n) - 1).values                 # 과거 n봉 수익률


class TimeSeriesMomentum(Strategy):
    lookback = 30
    stop_loss_pct = 0.05
    use_sentiment = False

    def init(self):
        self.mom = self.I(MOMENTUM, self.data.Close, self.lookback)
        # sentiment 자리 (Phase 5):
        # if self.use_sentiment: self.sentiment = self.data.sentiment

    def next(self):
        price = self.data.Close[-1]
        if not self.position:
            if self.mom[-1] > 0:                        # 모멘텀 양 → 매수
                self.buy(sl=price * (1 - self.stop_loss_pct))
        else:
            if self.mom[-1] <= 0:                       # 모멘텀 음 → 청산
                self.position.close()
