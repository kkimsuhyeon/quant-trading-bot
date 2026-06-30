import pandas as pd
from backtesting import Strategy
from strategies.sentiment_filter import sentiment_risk_off


def SMA(series, n):
    return pd.Series(series).rolling(n).mean().values


class RegimeFilter(Strategy):
    sma_n = 200
    stop_loss_pct = 0.05
    use_sentiment = False
    sentiment_threshold = 75

    def init(self):
        self.sma = self.I(SMA, self.data.Close, self.sma_n)

    def next(self):
        _sv = self.data.sentiment[-1] if self.use_sentiment else float("nan")
        if sentiment_risk_off(self.use_sentiment, _sv, self.sentiment_threshold):
            if self.position:
                self.position.close()       # 극탐욕 → 현금(청산), 신규 진입도 안 함
            return
        price = self.data.Close[-1]
        if not self.position:
            if price > self.sma[-1]:                # 장기 MA 위 → 보유
                self.buy(sl=price * (1 - self.stop_loss_pct))
        elif price < self.sma[-1]:                  # 장기 MA 아래 → 현금
            self.position.close()
