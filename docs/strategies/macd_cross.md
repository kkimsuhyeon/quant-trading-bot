# MACD 교차 (MACD Cross)

- **유형**: 추세 (trend-following)
- **상태**: 검증 중
- **코드**: `strategies/macd_cross.py` (`MacdCross`)
- **가설**: [`notes/hypothesis_macd_cross.md`](../../notes/hypothesis_macd_cross.md)

## 한 줄 요약
MACD선이 시그널선을 **위로 교차하면 사고**, **아래로 교차하면 판다.**

## 시장에 대한 믿음
"단기 EMA와 장기 EMA의 차이(MACD)가 시그널선을 상향 돌파하면 상승 모멘텀이 붙는다."
EMA 기반 모멘텀 필터로, SMA 교차보다 최근 가격 변화에 빠르게 반응한다.

## 지표
- **MACD선**: EMA(12) − EMA(26) — 단기·장기 지수이동평균의 차이
- **시그널선**: MACD선의 EMA(9) — MACD의 추세를 평활화

## 규칙
| 조건 | 동작 |
|---|---|
| MACD선이 시그널선을 **위로** 교차 (`crossover`) 이고 포지션 없음 | 매수 (손절: 진입가 −5%) |
| MACD선이 시그널선을 **아래로** 교차 이고 포지션 있음 | 청산 |

- 룩어헤드 방지: EMA는 확정된 종가로만 계산 (`close[-1]`).
- 주문: 다음 봉 시가 체결 (`trade_on_close=False`).

## 파라미터
| 이름 | 기본값 | 의미 |
|---|---|---|
| `fast` | 12 | 단기 EMA 기간(봉) |
| `slow` | 26 | 장기 EMA 기간(봉) |
| `sig` | 9 | 시그널 EMA 기간(봉) |
| `stop_loss_pct` | 0.05 | 손절 비율 (진입가 대비 −5%) |
| `use_sentiment` | False | sentiment 스위치 (자리만, 미구현 — Phase 5) |

## 잘 되는 장세 / 깨지는 장세
- **잘 됨**: 뚜렷한 추세장 — 교차 후 추세가 길게 지속될 때.
- **깨짐**: 횡보장 — 잦은 교차(휩쏘)로 거래가 1000회를 넘어 수수료로 자본이 소진된다.

## 결과 (참고)
BTC/USDT 1h, 약 3년, 수수료 0.1%/side:

| 지표 | 값 |
|---|---|
| 수익률 | **−81.70%** |
| Buy & Hold | 101.50% |
| 샤프 | −2.15 |
| MDD(최대낙폭) | −82.22% |
| 승률 | 30.94% |
| 거래 수 | 1015 |

→ 진다. 거래 횟수가 1015회로 많아 수수료 누적이 치명적이다.
SMA 교차(308회)보다 훨씬 많이 거래해 결과가 더 나쁘다.
1시간봉에서는 EMA 기반 빠른 반응이 오히려 노이즈 추종으로 이어진다.

## 관련
- 가설: `notes/hypothesis_macd_cross.md`
- 비교 노트북: `research/2026-06-27_six_strategy_compare.ipynb`
- 설계: `docs/design/phase-2-baseline-compare.md`
