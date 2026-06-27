import pandas as pd
from backtesting import Strategy


def DONCHIAN_HIGH(high, n):
    return pd.Series(high).rolling(n).max().shift(1).values   # 현재 봉 제외 → 룩어헤드 방지


def DONCHIAN_LOW(low, n):
    return pd.Series(low).rolling(n).min().shift(1).values


class DonchianBreakout(Strategy):
    entry_n = 20
    exit_n = 10
    stop_loss_pct = 0.05
    use_sentiment = False

    def init(self):
        self.upper = self.I(DONCHIAN_HIGH, self.data.High, self.entry_n)
        self.lower = self.I(DONCHIAN_LOW, self.data.Low, self.exit_n)
        # sentiment 자리 (Phase 5):
        # if self.use_sentiment: self.sentiment = self.data.sentiment

    def next(self):
        price = self.data.Close[-1]
        if not self.position:
            if price > self.upper[-1]:                 # 상단 돌파 → 매수
                self.buy(sl=price * (1 - self.stop_loss_pct))
        else:
            if price < self.lower[-1]:                 # 하단 이탈 → 청산
                self.position.close()
