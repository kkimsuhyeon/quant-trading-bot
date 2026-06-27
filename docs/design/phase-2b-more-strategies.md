# Phase 2b 상세 설계 — 전략 라인업 확장 (추세/모멘텀 계열)

> 상태: **설계 완료, 구현 전**
> Phase 2([phase-2-baseline-compare.md](phase-2-baseline-compare.md))의 연장 — 비교군을 6개로 넓혀 계열별 실패 양상을 본다.
> 관련: [`PLAN.md`](../../PLAN.md), [`CLAUDE.md`](../../CLAUDE.md). cross-agent 검토(Codex) 거침.

## 1. 개요 & 범위

현재 전략은 추세 1개(SMA) + 평균회귀 2개(RSI, 볼린저)뿐이다. **추세/모멘텀 계열 3개**를 독립 부품으로 추가해
같은 BTC 데이터로 비교(총 6개). 목적은 Phase 2와 동일 — **이기는 전략 찾기가 아니라** 계열별로 어떻게/어디서
깨지는지(특히 강한 상승장에서 추세/모멘텀이 Buy & Hold에 얼마나 근접하는지) 이해하는 것.

**기대치(정직)**: 강한 상승장(BTC +101%)에선 대부분 또 Buy & Hold에 질 가능성이 높다. 그게 정상이며, 확인 자체가 목적.

## 2. 추가 전략 (모두 교과서 전략, 직접 계산)

기존 패턴 그대로: Backtesting.py `Strategy` 상속, **고정 -5% 손절**(`self.buy(sl=...)`, 신호 종가 기준 proxy),
`use_sentiment=False` 슬롯, 지표 직접 계산(pandas-ta 미사용), 가설문서 선작성.

### Donchian 돌파 (`DonchianBreakout`) — 돌파(breakout)
- 믿음: 일정 기간 최고가를 넘으면 새 추세가 시작된다(터틀 트레이딩).
- 지표: 상단=과거 `entry_n`봉 최고가, 하단=과거 `exit_n`봉 최저가. **현재 봉 제외**(`.shift(1)`) — 룩어헤드 방지.
- 진입: 포지션 없고 `종가 > 상단 채널` → 매수
- 청산: `종가 < 하단 채널` → 청산
- 파라미터: `entry_n=20`, `exit_n=10`, `stop_loss_pct=0.05`

### 시계열 모멘텀 (`TimeSeriesMomentum`) — 모멘텀
- 믿음: 최근 일정 기간 수익률이 양(+)이면 그 추세가 이어진다.
- 지표: `mom = close / close.shift(lookback) - 1` (과거 lookback봉 수익률).
- 진입: 포지션 없고 `mom > 0` → 매수
- 청산: `mom <= 0` → 청산
- 파라미터: `lookback=30`, `stop_loss_pct=0.05`

### MACD 교차 (`MacdCross`) — 추세
- 믿음: 단기-장기 EMA 차이(MACD)가 시그널선을 상향 돌파하면 상승 모멘텀.
- 지표: `MACD = EMA(fast) - EMA(slow)`, `signal = EMA(MACD, sig)`.
- 진입: MACD가 시그널선을 **위로 교차**(crossover) → 매수
- 청산: MACD가 시그널선을 **아래로 교차** → 청산
- 파라미터: `fast=12`, `slow=26`, `sig=9`, `stop_loss_pct=0.05`

## 3. 비교 / 산출물

- 기존 비교 노트북을 확장(또는 신규)해 **6개 전략**(SMA, RSI, 볼린저, Donchian, 시계열모멘텀, MACD)을 같은 BTC 1h에 비교: 표(Return/B&H/Sharpe/MDD/WinRate/#Trades) + 수익곡선 6개.
- 각 신규 전략: `notes/hypothesis_*.md`(선작성) + `docs/strategies/*.md`(설명+실제 결과) + 단위테스트.
- 인덱스(`docs/strategies/README.md`, `docs/design/README.md`) 갱신.

## 4. 불변 / 제약

- 하네스(`backtest.py`)·데이터(`fetch.py`)·기존 전략 수정 금지.
- `commission=0.001`, `spread=0.0`, `trade_on_close=False`. Python 3.13 + `pandas<3`.
- 손절값 최적화/스윕 금지(고정 5%). ATR·민감도는 Phase 3.

## 5. 범위 밖

- 멀티자산 전략(상대 모멘텀, 페어) → 나중. 변동성 돌파/스토캐스틱 등 추가 변형 → 필요 시 다음 사이클.
- 견고성 검증(OOS/워크포워드) → Phase 3.
