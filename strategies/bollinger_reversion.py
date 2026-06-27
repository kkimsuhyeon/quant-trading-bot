import pandas as pd
from backtesting import Strategy


def SMA(close, n):
    return pd.Series(close).rolling(n).mean().values


def BB_LOWER(close, n, k):
    s = pd.Series(close)
    mid = s.rolling(n).mean()
    std = s.rolling(n).std()
    return (mid - k * std).values


class BollingerReversion(Strategy):
    bb_period = 20
    bb_std = 2
    stop_loss_pct = 0.05
    use_sentiment = False

    def init(self):
        self.mid = self.I(SMA, self.data.Close, self.bb_period)
        self.lower = self.I(BB_LOWER, self.data.Close, self.bb_period, self.bb_std)
        # sentiment 자리 (Phase 5):
        # if self.use_sentiment:
        #     self.sentiment = self.data.sentiment

    def next(self):
        price = self.data.Close[-1]
        if not self.position:
            if price < self.lower[-1]:                       # 하단 돌파 → 매수
                self.buy(sl=price * (1 - self.stop_loss_pct))  # -5% 손절
        else:
            if price > self.mid[-1]:                          # 중심선 복귀 → 청산
                self.position.close()
        # sentiment 자리 (Phase 5, 비활성)
