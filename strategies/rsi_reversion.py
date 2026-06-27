import pandas as pd
from backtesting import Strategy


def RSI(close, n):
    s = pd.Series(close)
    delta = s.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / n, min_periods=n, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / n, min_periods=n, adjust=False).mean()
    rs = avg_gain / avg_loss
    return (100 - 100 / (1 + rs)).values


class RsiReversion(Strategy):
    rsi_period = 14
    oversold = 30
    exit_level = 50
    stop_loss_pct = 0.05
    use_sentiment = False

    def init(self):
        self.rsi = self.I(RSI, self.data.Close, self.rsi_period)
        # sentiment 자리 (Phase 5):
        # if self.use_sentiment:
        #     self.sentiment = self.data.sentiment

    def next(self):
        price = self.data.Close[-1]
        if not self.position:
            if self.rsi[-1] < self.oversold:                 # 과매도 → 매수
                self.buy(sl=price * (1 - self.stop_loss_pct))  # -5% 손절
        else:
            if self.rsi[-1] > self.exit_level:               # 중립 복귀 → 청산
                self.position.close()
        # sentiment 자리 (Phase 5, 비활성)
