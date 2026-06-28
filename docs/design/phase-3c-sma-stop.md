# Phase 3c — SMA 리스크룰 보강 재검증

## 개요

Phase 3에서 **SMA Cross(4h)** 는 두 이유로 탈락했다: (1) 워크포워드 낙폭방어 일관성 약함(2/5),
(2) **손절(stop-loss)이 없음 → 가드레일 5 위반(미완성)**.

(2)는 싸게 닫을 수 있는 결함이다. **손절을 붙인 "완성본"으로 다시 평가**해서, SMA가 견고성 검증을
통과하는 2번째 후보가 되는지 본다. (Phase 4 페이퍼라는 무거운 단계로 가기 전, 싼 검증을 먼저 소진 —
깔때기 철학. 포트폴리오(P7)엔 검증 통과 전략이 여럿일수록 좋다.)

> 이건 "탈락한 걸 억지로 살리기"가 아니다. 가드레일 5가 *손절 없는 전략 = 미완성*이라 했으므로,
> **완성된 버전을 평가하는 것**이 정당한 절차다. 단, 통과할 때까지 손절값을 깎는 곡선맞추기는 금지.

## 무엇을 만드나 (기존 불변)

- **새 전략 `strategies/sma_cross_stop.py` → `SmaCrossWithStop`** 신설.
  - **기존 `SmaCross`는 건드리지 않는다** (Phase 2/3 비교 결과 보존성 — Codex 권고).
  - 로직: 기존 SMA 교차와 동일 + **손절만 추가**.
- 하네스(`backtest.py`)·`robustness.py`·다른 전략 **변경 없음**. 검증은 Phase 3와 동일 도구·동일 grid·동일 split.

### 전략 코드
```python
import pandas as pd
from backtesting import Strategy
from backtesting.lib import crossover


def SMA(series, n):
    return pd.Series(series).rolling(n).mean().values


class SmaCrossWithStop(Strategy):
    fast = 20
    slow = 50
    stop_loss_pct = 0.05      # 신호 종가 기준 -5% proxy (실제 진입은 다음 봉 시가)
    use_sentiment = False     # Phase 5 자리

    def init(self):
        close = self.data.Close
        self.sma_fast = self.I(SMA, close, self.fast)
        self.sma_slow = self.I(SMA, close, self.slow)

    def next(self):
        price = self.data.Close[-1]
        if crossover(self.sma_fast, self.sma_slow):       # 골든크로스 → 매수 + 손절
            self.buy(sl=price * (1 - self.stop_loss_pct))
        elif crossover(self.sma_slow, self.sma_fast):     # 데드크로스 → 청산
            self.position.close()
```

> 손절은 **신호 캔들 종가 기준 -X% proxy**다. `trade_on_close=False`라 실제 진입은 다음 봉 시가이므로
> "진입가 대비"가 아니라 "신호 종가 기준"으로 읽어야 한다 (Phase 2/3 문구와 동일 규칙).

## 탈락 기준 (결과 보기 **전에** 확정 — Codex 자문 반영)

검증 대상 = `SmaCrossWithStop(4h)`, **손절 기본값 5% 기준으로 판정**. Donchian과 **동일 잣대**.

1. **OOS (70/30)**: BTC OOS에서 **B&H 대비 MDD 방어 재현**. (절대수익 음수 허용)
2. **민감도 (단일 spike 아님)**:
   - **손절 민감도**: stop ∈ {3%, 5%, 8%} 에서 5% 기본값이 **외딴 spike가 아니어야** 함(셋 다 비슷한 방향).
   - **MA grid**: `fast {10,15,20,30} × slow {40,50,60,100}` (fast<slow)에서 **다수(≥60%)가 B&H보다 MDD 얕아야** 함. (수익 양수 비율은 보조)
   - ❗ **3/5/8 중 가장 좋은 값을 고르지 않는다** (곡선맞추기 금지). 5%는 사전 고정값.
3. **워크포워드**: 5개 연속 구간 중 **최소 3구간 B&H 대비 MDD 방어**.
4. **ETH 재현 (BTC 통과 시에만)**: BTC를 통과하면 ETH 4h에서 1~3을 **동일 기준으로 재현**해야 최종 통과.

### 통과해도 붙는 단서 (반드시 명시 — Codex)
> SMA+손절이 통과하더라도 **Donchian과 같은 4h 추세추종 계열이라 독립 알파로 보지 않는다.**
> 포트폴리오 분산 가치는 제한적이며, Phase 4에서는 **Donchian의 대체/보조 후보로만** 취급한다.
> (통과해도 "후보 2개"이지 "분산된 포트폴리오"가 아니다.)

### 기준이 *아닌* 것
- "B&H 총수익을 이겨야 한다"는 **기준이 아니다.** 현 thesis는 수익 극대화가 아니라 **낙폭 방어**다.

## 순서
SMA+손절 전략(+테스트) → **BTC 3축** → 통과 시 **ETH 3b** → 통과 시 Phase 4 후보 2개 / 탈락 시 Donchian 단독 Phase 4.
3번째 자산은 생략(이번 질문은 "SMA 완성본 재평가 가치"이지 Donchian 추가 증명이 아님).

## 산출물
- `strategies/sma_cross_stop.py` + `tests/` 테스트
- `research/2026-06-28_phase3c_sma_stop.ipynb` (BTC 3축 + 손절 민감도; ETH는 통과 시)
- 본 문서 + `docs/design/README.md` 인덱스
- (선택) `docs/strategies/sma_cross_stop.md` 전략 설명

*(결과·판정은 분석 실행 후 본 문서에 추가)*
