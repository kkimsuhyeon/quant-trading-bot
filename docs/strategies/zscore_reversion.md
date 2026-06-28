# Z-score 평균회귀 (Z-score Reversion)

- **유형**: 평균회귀 (mean-reversion)
- **상태**: 폐기 (Phase 2e 탐색에서 B&H 낙폭 방어 실패)
- **코드**: `strategies/zscore_reversion.py` (`ZScoreReversion`)
- **설계/검증**: [`docs/design/phase-2e-more-strategies.md`](../design/phase-2e-more-strategies.md)

## 한 줄 요약
가격이 이동평균에서 **−2 표준편차 아래로 벗어나면 사고**(반등 기대), **평균으로 복귀하면 판다.**

## 시장에 대한 믿음
"과하게 떨어진 가격은 평균으로 되돌아온다." Bollinger 하단 반등과 같은 평균회귀 아이디어를
z-score(표준화 편차)로 표현한 버전.

## 지표
- `z = (Close − SMA(20)) / std(20)`

## 규칙
| 조건 | 동작 |
|---|---|
| z < −2.0, 포지션 없음 | 매수 (손절: 신호 종가 기준 −5% proxy) |
| z ≥ 0.0 | 청산 (평균 복귀) |

## 파라미터
| 이름 | 기본값 | 의미 |
|---|---|---|
| `window` | 20 | 평균/표준편차 기간 |
| `entry_z` | −2.0 | 진입 z 임계 |
| `exit_z` | 0.0 | 청산 z 임계 |
| `stop_loss_pct` | 0.05 | 손절 비율 (신호 종가 기준 −5% proxy) |
| `use_sentiment` | False | sentiment 스위치 (자리만, Phase 5) |

## 결과 (참고 — BTC 4h, 약 5년)
| 지표 | 값 |
|---|---|
| 수익률 | **−72.8%** |
| MDD | −78.1% (B&H −77%보다 깊음 → 방어 실패) |
| Sharpe | −1.02 |
| 거래 수 | 253 |

→ **탈락.** 크립토 4h에서 평균회귀는 일관되게 실패(RSI·Bollinger와 동일 패턴). 게다가 **손절이
평균회귀의 '반등' 믿음과 충돌**(가장 많이 떨어진 순간=반등 직전에 손절). 가드레일5대로 손절을 통일
적용했고, MR이 손절로 불리해 탈락하는 것은 *정상*이다(설계서 사전 명시).

## 관련
- 설계: `docs/design/phase-2e-more-strategies.md`
- 노트북: `research/2026-06-28_phase2e_more_strategies.ipynb`
- 유사(먼저 탈락): [`bollinger_reversion.md`](bollinger_reversion.md), [`rsi_reversion.md`](rsi_reversion.md)
