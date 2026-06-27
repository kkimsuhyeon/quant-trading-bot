# Phase 2 상세 설계 — baseline 전략 비교

> 상태: **설계 완료, 구현 전**
> 관련: 로드맵 [`PLAN.md`](../../PLAN.md), 가드레일 [`CLAUDE.md`](../../CLAUDE.md), 하네스 설계 [`phase-0-1-lab.md`](phase-0-1-lab.md)
> cross-agent 검토(Codex) 거침 — 검토 기록은 문서 끝.

## 1. 개요 & 범위 (Scope)

추세추종(SMA 교차, Phase 1에서 구현됨) 옆에 **평균회귀(mean-reversion) 전략 2개**를 독립 부품으로 추가하고,
**같은 BTC 데이터에 셋 다 돌려 비교**한다.

- **목적은 "이기는 전략 찾기"가 아니다.** 추세추종과 평균회귀가 **서로 반대 장세에서 깨지는 것**을 눈으로 확인하는 것.
  (추세추종=횡보장에서 깨짐 / 평균회귀=추세장에서 깨짐) → 나중 포트폴리오(Phase 7)의 근거.
- 이번부터 **진짜 전략 검증**이므로 가드레일이 추가 적용된다:
  - **가설 문서**(`notes/hypothesis_*.md`)를 백테스트 *전*에 작성 (가드레일 6 / 작업규율).
  - **리스크 레이어**(손절) 포함 (가드레일 5).

## 2. 만들 파일

```
strategies/
├─ rsi_reversion.py             RSI 과매도 반등 전략
└─ bollinger_reversion.py       볼린저 하단 반등 전략
notes/
├─ hypothesis_rsi_reversion.md       가설 (백테스트 전)
└─ hypothesis_bollinger_reversion.md 가설 (백테스트 전)
docs/strategies/
├─ rsi_reversion.md             전략 설명 (sma_cross.md 템플릿)
└─ bollinger_reversion.md       전략 설명
tests/test_strategies.py        두 전략 단위 테스트
research/2026-06-27_phase2_compare.ipynb   3전략 비교 (표 + 수익곡선)
```
+ 인덱스 업데이트: `docs/strategies/README.md`(표 2줄), `docs/design/README.md`(Phase 2 상태).

**하네스(`backtest.py`)는 수정하지 않는다.** 전략은 기존 `run_backtest(df, 전략)`로 그대로 실행.

## 3. 전략 규칙

지표는 **직접 계산**한다(새 의존성 없음). `pandas-ta`는 Python 3.12+ 요구라 현재 환경(3.9)에 설치 불가 → 표준 공식으로 헬퍼 함수 작성(SMA를 직접 짠 것과 동일 패턴).

### RSI 과매도 반등 (`RsiReversion`)
- 지표: **RSI(14)** — Wilder 방식(`ewm(alpha=1/n)`).
- 진입: 포지션 없고 `RSI < 30`(과매도) → 매수
- 청산: `RSI > 50`(중립 복귀) → 청산
- 손절: **신호 캔들 종가 기준 -5%** (`self.buy(sl=price*0.95)`). ⚠️ `trade_on_close=False`라 실제 진입은 다음 봉 시가이므로 "진입가 대비"가 아니라 "신호 종가 기준 -5% proxy"다.
- 파라미터: `rsi_period=14`, `oversold=30`, `exit_level=50`, `stop_loss_pct=0.05`, `use_sentiment=False`

### 볼린저 하단 반등 (`BollingerReversion`)
- 지표: **볼린저밴드(20, 2σ)** — 중심선=SMA(20), 하단=중심선-2·표준편차.
- 진입: 포지션 없고 `종가 < 하단밴드` → 매수. (반등을 확인하고 들어가는 게 아니라 **하단 이탈 즉시** 진입 = "하단 이탈 평균회귀"에 가깝다.)
- 청산: `종가 > 중심선(20 SMA)` → 청산
- 손절: **신호 캔들 종가 기준 -5%** (RSI와 동일 proxy)
- 파라미터: `bb_period=20`, `bb_std=2`, `stop_loss_pct=0.05`, `use_sentiment=False`

두 전략 모두 SMA와 동일하게 `use_sentiment` 스위치 자리만 둔다(미구현, Phase 5).

## 4. 리스크 관리 (가드레일 5)

- **고정 % 손절**: 두 전략 공통 `stop_loss_pct=0.05`. Backtesting.py의 `self.buy(sl=...)`로 손절가 지정. 단, `trade_on_close=False`라 sl 기준가는 **신호 캔들 종가**(실제 진입은 다음 봉 시가) → "신호 종가 기준 -5% proxy"로 이해한다.
- **이 손절값은 최적화 대상이 아니라 "파이프라인 비교용 고정 리스크 가드"다.** Phase 2에서 손절값 스윕(sweep) 금지.
  3/5/8% 민감도 비교는 **Phase 3 후보**로만 기록.
- 포지션 크기: SMA와 동일(가용 자본, fractional). 계좌 단위 킬스위치는 라이브/포트폴리오 단계로 미룸.
- ATR 기반 변동성 적응형 손절은 **Phase 3**로 미룸.

## 5. 비교 방법

`research/2026-06-27_phase2_compare.ipynb`에서:
- BTC/USDT 1h 동일 데이터에 `SmaCross`, `RsiReversion`, `BollingerReversion`을 각각 `run_backtest`.
- **비교 표**: Return [%], Buy & Hold Return [%], Sharpe, Max. Drawdown [%], Win Rate [%], # Trades.
- **수익곡선 3개를 한 그래프에 겹쳐** 그려, "추세 vs 평균회귀가 다른 구간에서 깨지는 것" 확인.

## 6. 비용 / 데이터 (불변)

- `commission=0.001`(0.1%/side), `spread=0.0`(슬리피지 보류) — Phase 1과 동일.
- 데이터: **BTC만**. ETH는 나중에 `fetch_ohlcv("ETH/USDT", ...)` 한 줄로 추가.

## 7. 검증 / 완료 기준

1. 각 전략 단위 테스트 통과: 합성 데이터(하락→반등)로 `# Trades > 0`, 손절가가 설정됨, stats 키 존재.
2. 비교 노트북에서 3전략 표 + 수익곡선이 나란히 출력.
3. 추세(SMA)와 평균회귀가 서로 다른 구간에서 깨지는 게 관찰됨(해석은 노트북/결론에 기록).
4. 두 전략 모두 `use_sentiment` 스위치 자리 유지(미구현).

## 8. 범위 밖 / 나중 (deferred)

- 손절값 민감도(3/5/8%), ATR 손절 → Phase 3.
- ETH·추가 자산 → 나중(한 줄 추가).
- 포트폴리오 결합(상관 낮은 전략 묶기) → Phase 7.
- sentiment 구현 → Phase 5.

## 9. Cross-agent 검토 기록 (Codex)

- **손절 방식**: Codex·Claude 합의 → 고정 % 손절, 기본값 -5%, 두 전략 공통, **Phase 2 손절값 스윕 금지**(과최적화 경계). ATR은 Phase 3. (§4)
- **지표 라이브러리**: pandas-ta가 Python 3.9에 설치 불가 → 지표 직접 계산으로 변경(검증 완료). (§3)
