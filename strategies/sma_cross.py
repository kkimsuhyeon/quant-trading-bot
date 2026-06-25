import pandas as pd
from backtesting import Strategy
from backtesting.lib import crossover


def SMA(series, n):
    return pd.Series(series).rolling(n).mean().values


class SmaCross(Strategy):
    fast = 20                # 단기 이평
    slow = 50                # 장기 이평
    use_sentiment = False    # sentiment on/off 스위치 자리 (구현 Phase 5)

    def init(self):
        close = self.data.Close
        self.sma_fast = self.I(SMA, close, self.fast)
        self.sma_slow = self.I(SMA, close, self.slow)
        # sentiment 자리 (Phase 5):
        # if self.use_sentiment:
        #     self.sentiment = self.data.sentiment

    def next(self):
        # 룩어헤드 방지: 현재까지 공개된 완성 캔들만 사용, 주문은 다음 봉 시가 체결.
        if crossover(self.sma_fast, self.sma_slow):     # 골든크로스 → 매수
            self.buy()
        elif crossover(self.sma_slow, self.sma_fast):   # 데드크로스 → 청산
            self.position.close()
        # sentiment 자리 (Phase 5, 비활성):
        # if self.use_sentiment:
        #     score = self.sentiment[-1]
        #     ...
