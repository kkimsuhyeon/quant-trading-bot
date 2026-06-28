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

---

## 결과 (BTC/USDT 4h, ETH/USDT 4h, 각 5년)

### 손절이 바꾼 것 (full, 20/50)
| 자산 | SMA (손절 없음) | SMA+손절 5% |
|---|---|---|
| BTC | +18.9% / MDD -60.1% | **+45.4% / MDD -53.5%** |
| ETH | -41.3% / MDD -71.4% | **+50.5% / MDD -45.6%** |

→ 손절 추가로 **수익·낙폭이 둘 다 개선**됐다. 특히 ETH에선 -41%(손실)이 +50%(이익)로 뒤집힘.
손절이 **추세추종의 약점(추세 반전 시 손실 누적)을 직접 막아** 두 자산 모두에서 효과를 냈다.

### BTC 검증 (탈락기준 대조)
- **①OOS**: OOS MDD -33.9% vs B&H -52.7% (**방어 +18.8%p**), 수익 -1.4%(≈flat, B&H -37.4%보다 훨씬 나음) → ✅
- **②민감도**: 손절 3/5/8% 전부 방어(5%가 단일 spike 아님; 3%+128%·5%+45%·8%+32%). MA grid 16조합 **B&H낙폭방어 100%**, 수익>0 94%, 기본 20/50 상위 8/16 → ✅
- **③워크포워드**: **3/5 구간 방어** (손절 없던 SMA는 2/5였음 → 손절이 일관성도 개선). 기준(≥3) 충족 → ✅
- → **BTC 3축 통과.**

### ETH 검증 (out-of-asset, 동일 기준)
- **①OOS**: OOS MDD -40.3% vs B&H -68.0% (**방어 +27.8%p**), 수익 **+3.5%(양수)** → ✅
- **②민감도**: 손절 3/5/8% 전부 방어. MA grid 16조합 **B&H낙폭방어 100%**, 수익>0 88%, 기본 상위 8/16 → ✅
- **③워크포워드**: **5/5 구간 전부 방어** (BTC보다 강함) → ✅
- → **ETH 3축 통과.**

## 판정: ✅ SmaCrossWithStop — BTC+ETH 통과 (검증된 2번째 후보)

손절 추가가 SMA의 **두 탈락 사유를 모두 고쳤다**: (1) 리스크룰 부재(가드레일5) 해소, (2) 방어
일관성도 개선(BTC 워크포워드 2/5 → 3/5, ETH 5/5). 두 자산에서 견고성 3축을 통과 →
**"낙폭 방어 도구"로서 검증된 2번째 후보.** (주목: ETH에선 SMA+손절(+50%)이 Donchian(-36%)보다 나았다.)

### 통과에 붙는 단서 (반드시 명시)
- ⚠️ **Donchian과 같은 4h 추세추종 계열 → 독립 알파 아님.** 포트폴리오 분산 가치 제한적,
  Phase 4에서는 **Donchian의 대체/보조 후보로만** 취급(통과해도 "후보 2개"이지 분산된 포트폴리오 아님).
- ⚠️ **손절 값에 민감.** 더 타이트할수록(3%) 좋았고 ETH에선 8%가 음수 — 5%는 *사전 고정한 합리적 값*이고
  3/5/8 전 구간이 방어는 하지만, "손절값과 무관하게 견고"한 건 아니다. (3% best 채택은 곡선맞추기라 안 함.)
- ⚠️ **여전히 B&H 총수익은 못 이김**(BTC +45% vs B&H +75%) — Donchian과 동일하게 "수익기 아닌 방어 도구".

## 정직한 한계
- BTC·ETH 둘 다 크립토 베타라 상관 높음(완전 독립 검증 아님). ETH가 약세장이라 방어가 잘 보인 면도 있음.
- 손절이 결과를 크게 바꾼 만큼, "손절 파라미터" 자체가 새로운 자유도다 — 5%로 사전 고정해 곡선맞추기는 피했으나, 향후 과신 금물.

## 다음 단계
- **후보 2개 확정**: Donchian(4h) + SmaCrossWithStop(4h). 둘 다 "낙폭 방어 도구", 서로 상관 높음.
- → **Phase 4 페이퍼 트레이딩**으로 진입 가능 (둘 다, 또는 Donchian 우선 + SMA+stop 보조).
