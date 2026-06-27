import pandas as pd
from backtesting import Strategy
from backtesting.lib import crossover


def MACD_LINE(close, fast, slow):
    s = pd.Series(close)
    return (s.ewm(span=fast, adjust=False).mean()
            - s.ewm(span=slow, adjust=False).mean()).values


def MACD_SIGNAL(close, fast, slow, sig):
    s = pd.Series(close)
    macd = (s.ewm(span=fast, adjust=False).mean()
            - s.ewm(span=slow, adjust=False).mean())
    return macd.ewm(span=sig, adjust=False).mean().values


class MacdCross(Strategy):
    fast = 12
    slow = 26
    sig = 9
    stop_loss_pct = 0.05
    use_sentiment = False

    def init(self):
        self.macd = self.I(MACD_LINE, self.data.Close, self.fast, self.slow)
        self.signal = self.I(MACD_SIGNAL, self.data.Close, self.fast, self.slow, self.sig)
        # sentiment 자리 (Phase 5):
        # if self.use_sentiment: self.sentiment = self.data.sentiment

    def next(self):
        price = self.data.Close[-1]
        if crossover(self.macd, self.signal):          # 상향 교차 → 매수
            if not self.position:
                self.buy(sl=price * (1 - self.stop_loss_pct))
        elif crossover(self.signal, self.macd):        # 하향 교차 → 청산
            if self.position:
                self.position.close()
