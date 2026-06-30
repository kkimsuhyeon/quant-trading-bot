# Phase 4c — 현물 demo 실행 엔진 (Keltner)

> Phase 4 "페이퍼 트레이딩"의 **2단계 = testnet/demo 실제 주문**. (1단계 섀도우는 신호만 로깅했음.)
> **처음으로 실제 주문을 낸다 — 단 바이낸스 *Demo*(가짜 돈)에서.** 실거래 아님.
> 목적: "백테스트가 라이브 *주문 기계*와 맞물리나"(체결·포지션추적·정합성·킬스위치)를 **안전하게** 검증.

## 개요 / 목표 (강하게 한정)
검증된 **Keltner(BTC/USDT 4h)** 신호대로 **현물 demo(`demo-api.binance.com`)에 시장가 주문**을 내는 최소 엔진.
- 검증 대상: 주문이 실제 체결되나 · 의도 포지션 vs 실제 포지션 정합 · 에러/멱등 · **킬스위치** 작동.
- **선물·캐리는 범위 밖**(demo-fapi 마이그레이션 정리 후 같은 엔진에 엔드포인트만 교체).

## 가드레일 (필수)
- **여전히 demo(가짜 돈).** 실거래는 별도 단계(가드레일 1).
- **리스크 우선(가드레일 5):** 하드 킬스위치 + 고정 사이즈 + 레버리지 0(현물). 신호만 있고 리스크룰 없는 실행은 미완성.
- **하네스/전략 불변:** `fetch_live`·`desired_position`(paper_trade) 재사용, 전략 코드 안 건드림.
- **dry-run 먼저:** 기본은 계산·로그만. 실제 전송은 명시적 `--live`.

## 구조 — 새 모듈 `demo_executor.py` (기존 재사용)
```text
get_spot_position(exchange, base="BTC") -> float        # 현재 보유 base 수량(현물 잔고)
target_state(df) -> int                                  # = desired_position(df, KeltnerBreakout) (0/1)
reconcile(exchange, df, equity_state, ...) -> dict       # 목표 vs 실제 → 시장가 주문으로 정렬
  # 목표=1(롱) & 미보유 → 가용 USDT*frac 매수 ; 목표=0(현금) & 보유 → 보유 base 전량 매도
  # 이미 목표 상태면 주문 없음(멱등)
run_once(live=False) -> dict                             # fetch_live → target → 킬스위치 점검 → reconcile → 로그
```
- **엔드포인트:** ccxt binance, `urls['api']`의 spot를 `https://demo-api.binance.com`로 치환. 키는 `.env`의 `BINANCE_TESTNET_API_KEY/SECRET`(현물 demo 동작 확인됨).
- **재사용:** `fetch_live`(라이브 4h), `desired_position`(전략 신호), 단일 락·멱등 패턴(paper_trade).

## 주요 결정 (기본값 — demo라 단순/안전 우선)
- **주문**: 시장가(market). cron이 봉 마감 ~10분 뒤 실행 → 사실상 다음 봉 진입(백테스트 `trade_on_close=False`와 정합).
- **사이즈**: 진입 시 가용 USDT의 **95%**(수수료/최소수량 버퍼), 청산 시 보유 base **전량**. (백테스트의 all-in/all-out과 정합. 고정 비율, 최적화 없음.)
- **킬스위치**: equity(=USDT + base×가격) 고점 대비 **−15%** 도달 시 → **거래 정지 + 전량 청산 + 수동 리셋 요구**. 상태는 `paper/demo_state.json`.
- **대상**: Keltner 1개 · BTC/USDT 1종 · 현물 demo. (다전략/포트폴리오/선물 = 다음.)
- **최소 주문**: 거래소 min-notional/lot 미만이면 skip + 경고(주문 거부 방지).

## 안전 / 테스트 (synthetic — ★라이브 주문 절대 안 냄)
- 자동 테스트는 **fake exchange 주입**(네트워크/실주문 0): reconcile 로직(목표1+미보유→매수주문 1건 / 목표0+보유→매도 / 이미목표→무주문), 킬스위치 발동(고점−15%→halt+청산), 멱등을 **값으로 검증**.
- 기본 `dry_run=True`. 실제 demo 주문은 사용자가 `--live`로 의도적으로만.
- 단일 락·staleness 가드(paper_trade 패턴).

## 운영 (사용자 수동 절차)
1. `.env`에 demo 현물 키(동작 확인됨).
2. `python demo_executor.py`(dry-run)로 "무슨 주문을 낼지" 먼저 확인.
3. 이상 없으면 `python demo_executor.py --live`로 demo에 실제 주문.
4. (선택) cron 등록은 검증 후. 섀도우 cron과 별도.

## 범위 밖 / 다음
다전략·자본배분(포트폴리오), 선물/캐리(demo-fapi), 레버리지, 지정가/스톱주문, **실거래(real money)**. 확장 자리: `run_once(strategy, allocation, ...)` 인자화.

## 산출물
- `demo_executor.py` + `tests/test_demo_executor.py`(synthetic, fake exchange)
- 본 문서 + `docs/design/README.md` 인덱스 + `.env.example`(키 템플릿)
