import pandas as pd
from backtesting import Strategy
from strategies.sentiment_filter import sentiment_risk_off


def EMA(series, n):
    return pd.Series(series).ewm(span=n, adjust=False).mean().values


def ATR(high, low, close, n):
    high, low, close = pd.Series(high), pd.Series(low), pd.Series(close)
    prev = close.shift(1)
    tr = pd.concat([high - low, (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean().values   # Wilder ATR


class KeltnerBreakout(Strategy):
    ema_n = 20
    atr_n = 20
    atr_mult = 2.0
    stop_loss_pct = 0.05
    use_sentiment = False
    sentiment_threshold = 75

    def init(self):
        self.ema = self.I(EMA, self.data.Close, self.ema_n)
        self.atr = self.I(ATR, self.data.High, self.data.Low, self.data.Close, self.atr_n)

    def next(self):
        _sv = self.data.sentiment[-1] if self.use_sentiment else float("nan")
        if sentiment_risk_off(self.use_sentiment, _sv, self.sentiment_threshold):
            if self.position:
                self.position.close()
            return
        price = self.data.Close[-1]
        upper = self.ema[-1] + self.atr_mult * self.atr[-1]
        if not self.position:
            if price > upper:                       # 상단 밴드 돌파 → 매수
                self.buy(sl=price * (1 - self.stop_loss_pct))
        elif price < self.ema[-1]:                  # 중심선(EMA) 하향 이탈 → 청산 (하단밴드 청산은 늦음)
            self.position.close()
