# Phase 4b — 섀도우 cron 확장 (sentiment 로깅 + 펀딩 기록기)

> Phase 4 섀도우(`paper_trade.py`, 4h마다 BTC/USDT 현물 추세신호 로깅, 주문X)를 확장.
> 라이브 데이터를 싸게 더 쌓는다 — 여전히 **섀도우(주문X·돈X)**. 하네스/전략 불변.

## 개요 / 목표
방금 검증한 두 가지를 라이브로 적립:
1. **sentiment 로깅** — sentiment를 지원하는 추세전략(Regime/Keltner)에 대해 **baseline + sentiment 신호를 나란히** 기록. 극탐욕 구간이 오면 필터가 baseline과 *실제로 갈리는지*를 라이브로 포착.
2. **펀딩 기록기** — 매 실행마다 BTC/ETH perp 현재 펀딩을 별도 CSV에 적립. 캐리 testnet/실거래 prep + "펀딩이 history처럼 도나" 라이브 sanity.

## 설계 (paper_trade.py 확장, 모양 최소 변경)
### 1. sentiment 신호 로깅
- `STRATEGIES`를 `name -> (strategy, params)`로 확장. sentiment 지원 2종에 변형 추가:
  ```python
  STRATEGIES = {
      "keltner": (KeltnerBreakout, {}),
      "regime": (RegimeFilter, {}),
      "donchian": (DonchianBreakout, {}),
      "sma_stop": (SmaCrossWithStop, {}),
      "keltner_sent": (KeltnerBreakout, {"use_sentiment": True}),
      "regime_sent": (RegimeFilter, {"use_sentiment": True}),
  }
  ```
- `desired_position(df, strategy, **params)` — params를 `run_backtest`에 전달.
- `run_once`: `fetch_live` 후 **라이브 F&G 부착** — `attach_fng(df, fetch_fng())`로 sentiment 컬럼 채움(없으면 NaN=필터off). 그 뒤 `_append_signals`가 변형 포함 순회.
- **Graceful fallback**: F&G fetch 실패(네트워크)면 sentiment 컬럼 NaN → 필터 off → sentiment 변형이 baseline과 동일. cron은 안 깨짐. (기존 signal-bot의 graceful 패턴과 동일 철학.)
- 기존 CSV 스키마 유지(추가 행만; strategy 이름으로 baseline/sentiment 구분). 멱등키(strategy,symbol,timeframe,bar)로 중복 skip 그대로.

### 2. 펀딩 기록기
- 새 파일 `paper/funding.csv`, 컬럼 `[run_at, symbol, funding_time, funding_rate, mark_price]`.
- `record_funding(symbols=("BTC/USDT:USDT","ETH/USDT:USDT"), exchange=None, dry_run=False)`:
  ccxt `fetch_funding_rate(sym)` 스냅샷 → `funding_time`(다음 정산시각)로 **멱등 dedup**(8h 정산, 4h cron이라 같은 정산 두 번 안 적게). append.
- `run_once`에서 신호 로깅 뒤 호출. **Graceful**: 실패해도 신호 로깅엔 영향 없음(try/except 경고 후 진행).
- `paper/`는 이미 gitignore.

## 검증 / 테스트 (synthetic, 네트워크 비의존)
- `desired_position`이 params(use_sentiment=True)를 전달 → 합성 극탐욕 데이터에서 sentiment 변형이 현금(0).
- `_append_signals`가 sentiment 변형 행을 포함하고 멱등 dedup 유지.
- 펀딩 dedup: 같은 `funding_time` 두 번 호출 → 한 행만.
- 라이브 F&G/펀딩 fetch는 네트워크라 유닛테스트 제외(기존 fetch_live처럼). attach_fng는 7b-v2 테스트가 이미 커버.

## 금지 / 불변
- 주문 실행 없음(여전히 섀도우). 하네스·전략 파일 수정 없음(전략은 use_sentiment 이미 보유).
- Donchian/SMA+stop엔 sentiment 변형 안 만듦(전략에 use_sentiment 분기 미구현 — Regime/Keltner만 Phase 5에서 배선됨).

## 산출물
- `paper_trade.py` 확장(STRATEGIES 변형·desired_position params·F&G 부착·record_funding) + `tests/test_paper_trade.py` 보강
- 본 문서 + `docs/design/README.md` 인덱스. (cron 명령은 그대로 — `python paper_trade.py`가 둘 다 수행.)
