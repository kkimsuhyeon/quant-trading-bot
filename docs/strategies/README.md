# 전략 문서 (Strategies)

각 전략이 **무엇이고, 어떤 믿음에 기반하며, 언제 작동/깨지는지** 설명하는 문서 모음.
전략 코드는 [`strategies/`](../../strategies/), 이 폴더는 그 설명.

> 새 전략을 추가할 때마다 아래 표에 한 줄 + 상세 문서 1개를 추가한다.
> 새 문서는 [`sma_cross.md`](sma_cross.md)의 구조(요약·믿음·지표·규칙·장세·결과)를 따른다.

| 전략 | 유형 | 상태 | 문서 | 코드 |
|---|---|---|---|---|
| SMA 교차 | 추세추종 | hello world (미검증) | [sma_cross.md](sma_cross.md) | `strategies/sma_cross.py` |
| RSI 과매도 반등 | 평균회귀 | 검증 중 | [rsi_reversion.md](rsi_reversion.md) | `strategies/rsi_reversion.py` |
| 볼린저 하단 반등 | 평균회귀 | 검증 중 | [bollinger_reversion.md](bollinger_reversion.md) | `strategies/bollinger_reversion.py` |

상태 단계: **hello world → 검증 중 → 검증 통과 → 폐기**
