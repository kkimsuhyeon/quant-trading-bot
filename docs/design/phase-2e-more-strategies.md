# Phase 2e — 추가 전략 탐색 (Keltner / Regime / Z-score)

## 개요

현물 4h 제약 안에서 **트리거가 다른** 전략 3개를 추가로 탐색한다. 목적은 "이긴 전략 찾기"가
아니라 **이미 본 엣지(추세=방어 OK, 평균회귀=실패) 외에 다른 게 있나** 보는 것.

> ⚠️ **이건 "탐색"이다 — 판정(통과/탈락)이 아니다.** 여기서 좋아 보이는 건 "robustness 검증 대상"일
> 뿐, **Phase 3식 3축(OOS·민감도·워크포워드) + ETH out-of-asset 을 통과해야** 비로소 후보다.
> 많이 던져서 우연히 좋은 걸 줍는 **데이터 스누핑**을 경계한다. (Codex 자문 반영)

- 대상: BTC/USDT 4h 먼저(싸게 거름) → 생존자만 ETH로 검증. 데이터 이미 있음.
- 재사용: `robustness.py`, 하네스 그대로. **새 전략 파일 3개만 추가, 기존 전략/하네스 불변.**
- 수수료 0.1%/side, 손절은 신호 종가 기준 -5% proxy(전 전략 공통).

## 추가 전략 3개 (Codex 자문 파라미터)

### 1. Keltner 변동성 돌파 (`KeltnerBreakout`) — 돌파, 트리거 = 변동성 밴드
EMA 중심선 ± ATR 밴드. Donchian이 "가격 채널"이면 이건 "변동성(ATR) 밴드".
```python
import pandas as pd
from backtesting import Strategy


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

    def init(self):
        self.ema = self.I(EMA, self.data.Close, self.ema_n)
        self.atr = self.I(ATR, self.data.High, self.data.Low, self.data.Close, self.atr_n)

    def next(self):
        price = self.data.Close[-1]
        upper = self.ema[-1] + self.atr_mult * self.atr[-1]
        if not self.position:
            if price > upper:                       # 상단 밴드 돌파 → 매수
                self.buy(sl=price * (1 - self.stop_loss_pct))
        elif price < self.ema[-1]:                  # 중심선(EMA) 하향 이탈 → 청산 (하단밴드 청산은 늦음)
            self.position.close()
```

### 2. 추세 필터 / Regime (`RegimeFilter`) — 추세, 트리거 = 장기 MA 위/아래
교차가 아니라 **단순 스위치**: 가격이 장기 MA 위면 보유, 아래면 현금. (Codex: Donchian/SMA보다 단순해 설명력 좋음)
```python
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
```

### 3. Z-score 평균회귀 (`ZScoreReversion`) — 평균회귀, 트리거 = 표준화 편차
가격이 평균에서 z 표준편차만큼 벗어나면 반등 베팅. (⚠️ Bollinger와 중복 큼 — 기대 낮게, 스누핑 최강 경고)
```python
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
```

- 룩어헤드: 모든 지표는 완성봉 종가 기준, 주문은 다음 봉 시가 체결(`trade_on_close=False`) — 기존 SMA/Bollinger와 동일 규칙.
- **MR + 손절 주의 (Codex)**: 우리는 "손절이 평균회귀에 해롭다"를 데이터로 확인했다(RSI 손절ON시 -28%→-63%).
  z-score MR에도 가드레일5 준수를 위해 손절 5%를 **통일 적용**한다(전략별 예외 안 둠). 따라서
  **z-score MR이 손절 때문에 탈락해도 그것은 정상**이다.

## "robustness 검증 대상" 선별 기준 (탐색 → 검증 게이트, 결과 보기 전 확정)

Phase 2e 탐색에서 아래를 만족하는 전략만 robustness(Phase 3식) 검증 대상으로 올린다:
- full BTC 4h에서 **B&H 대비 MDD 방어** (전략 MDD가 B&H보다 얕음).
- 수익률은 보조, **B&H 초과수익은 기준 아님**(thesis = 낙폭 방어).

검증 대상이 되면: BTC 4h에서 OOS(70/30) / 파라미터 민감도 / 워크포워드 5구간 → 통과 시 ETH out-of-asset.
- 손절 민감도(3/5/8%)는 robustness 단계에서만 보고, **Phase 2e 탐색 기본은 5% 고정**.
- ETH는 검증이지 탐색 확장이 아니다(분리).

## 산출물
- `strategies/keltner_breakout.py`, `strategies/regime_filter.py`, `strategies/zscore_reversion.py` + 각 테스트
- `research/2026-06-28_phase2e_more_strategies.ipynb` (탐색 비교 + 생존자 robustness)
- 본 문서 + `docs/strategies/` 문서 3개 + 인덱스, `docs/design/README.md` 인덱스
- 하네스/기존 전략 변경 없음.

## 정직한 기대치
대부분 또 탈락할 것이다(깔때기 정상). 3개 다 추세/MR의 변주라, 결과는 기존 패턴(추세=방어, MR=실패)을
재확인할 가능성이 크다. 새로 좋아 보이는 게 나와도 **단일 관측 = 스누핑 의심**, robustness 통과가 전제.

*(결과는 분석 실행 후 본 문서에 추가)*
