# Keltner 변동성 돌파 (Keltner Breakout)

- **유형**: 돌파 (breakout) — 트리거는 변동성(ATR) 밴드
- **상태**: 검증 통과 (Phase 2e — BTC+ETH 견고성 3축 통과)
- **코드**: `strategies/keltner_breakout.py` (`KeltnerBreakout`)
- **설계/검증**: [`docs/design/phase-2e-more-strategies.md`](../design/phase-2e-more-strategies.md)

## 한 줄 요약
EMA 중심선 위로 **ATR 밴드(EMA + 2×ATR)를 돌파하면 사고**, **EMA 아래로 떨어지면 판다.**

## 시장에 대한 믿음
"가격이 평소 변동성(ATR) 범위를 크게 벗어나 위로 튀면, 새 추세가 시작될 확률이 높다."
Donchian이 '가격 채널' 돌파라면, Keltner는 '변동성 밴드' 돌파 — 트리거가 다르다.

## 지표
- 중심선: `EMA(20)` (지수이평)
- 밴드 폭: `ATR(20)` (Wilder, `ewm(alpha=1/n)`)
- 상단 = EMA + 2×ATR

## 규칙
| 조건 | 동작 |
|---|---|
| 종가 > EMA + 2×ATR, 포지션 없음 | 매수 (손절: 신호 종가 기준 −5% proxy) |
| 종가 < EMA | 청산 (하단 밴드 청산은 늦어 MDD↑ → 중심선 청산 채택) |

- 룩어헤드 방지: 지표는 완성봉 종가/ATR 기준, 주문은 다음 봉 시가(`trade_on_close=False`). ATR는 전봉 종가(`shift(1)`) 사용.

## 파라미터
| 이름 | 기본값 | 의미 |
|---|---|---|
| `ema_n` | 20 | 중심선 EMA 기간 |
| `atr_n` | 20 | ATR 기간 |
| `atr_mult` | 2.0 | 밴드 폭 배수 |
| `stop_loss_pct` | 0.05 | 손절 비율 (신호 종가 기준 −5% proxy) |
| `use_sentiment` | False | sentiment 스위치 (자리만, Phase 5) |

## 잘 되는 장세 / 깨지는 장세
- **잘 됨**: 변동성 확장과 함께 추세가 나는 장. EMA 청산이 빨라 추세 반전 시 낙폭을 방어한다.
- **깨짐**: 큰 폭락이 *없는* 횡보·완만 상승장 — 빠른 청산이 상승 일부를 놓쳐 B&H에 뒤질 수 있다.

## 결과 (참고 — BTC/ETH 4h, 약 5년, 수수료 0.1%/side)
| 자산 | FULL | OOS(뒤30%) | 파라미터 민감도 | 워크포워드 |
|---|---|---|---|---|
| BTC | +83.1% / MDD −37.3% | −30.0% / −34.1% (방어O) | 16조합 100% 방어·100% 양수 | 5/5 |
| ETH | +103.3% / −28.7% | **+5.6%** / −27.7% (방어O) | 16조합 100% 방어·100% 양수 | 5/5 |

→ **현재까지 가장 견고한 후보.** B&H도 이김. 단 ⚠️ B&H 초과수익의 상당부분은 2022 폭락이 검증 창에
들어있어서다(폭락 회피가 엣지) — 폭락 없는 OOS에선 BTC 절대수익 음수. **본질은 낙폭 방어 도구.**
Donchian/Regime/SMA+stop과 같은 추세 계열이라 **상관 높음**(분산 가치 제한).

## 관련
- 설계·검증: `docs/design/phase-2e-more-strategies.md`
- 노트북: `research/2026-06-28_phase2e_more_strategies.ipynb`
