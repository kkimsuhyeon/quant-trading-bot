import pandas as pd
from backtesting import Strategy


def ZSCORE(series, n):
    s = pd.Series(series)
    return ((s - s.rolling(n).mean()) / s.rolling(n).std()).values


class ZScoreReversion(Strategy):
    window = 20
    entry_z = -2.0
    exit_z = 0.0
    stop_loss_pct = 0.05
    use_sentiment = False

    def init(self):
        self.z = self.I(ZSCORE, self.data.Close, self.window)

    def next(self):
        price = self.data.Close[-1]
        if not self.position:
            if self.z[-1] < self.entry_z:           # 평균 -2σ 이탈 → 매수(반등 기대)
                self.buy(sl=price * (1 - self.stop_loss_pct))
        elif self.z[-1] >= self.exit_z:             # 평균 복귀 → 청산
            self.position.close()
