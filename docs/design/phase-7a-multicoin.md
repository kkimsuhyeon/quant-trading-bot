# Phase 7a — 다(多)코인 현물 포트폴리오 (분산 효과 검증)

> Phase 7(확장)을 당겨서 시작. **현물만** (선물/레버리지 = 7b, 나중). 사용자 승인 + Codex 자문 반영.

## 개요 / 목표 (한정)

**질문 하나:** *"여러 코인에 우리 추세 전략을 분산하면, BTC 단독보다 정말 더 매끈해지나(낙폭↓ / Sharpe↑)?"*

- **이것은 "최적 포트폴리오 찾기"가 아니다.** 분산 효과의 *유무*를 보는 검증이다. (Codex 강조)
- 우리가 단일자산에서 부딪힌 천장("4개 추세전략이 다 BTC라 상관 높아 분산 안 됨")을, **서로 다른 시장(코인)** 으로 넘어설 수 있는지 보는 것 = CTA가 100개 시장으로 버는 그 효과의 축소판.

## 유니버스 (survivor-biased — 반드시 라벨)

- 정의: **"2021-06 이전부터 Binance USDT 현물 4h 데이터가 있고, 현재도 유동성이 큰 메이저 코인 고정셋"** (8~10개).
  후보: BTC, ETH, BNB, SOL, ADA, XRP, DOGE, AVAX, LINK, LTC. (전부 2021-06 이전 상장 확인됨.)
- 제외 규칙(사전 명시): **스테이블코인 / 랩핑 토큰(WBTC 등) / 레버리지 토큰(UP/DOWN 등)** 제외.
- ⚠️ **생존편향(survivorship bias) 명시:** 이건 "오늘까지 살아남은 메이저"라, 죽은 코인(LUNA/UST·FTT 등)을 포함하지 않는다.
  → **시장 전체 검증이 아니라 "메이저-코인 후보 검증"** 이다. 결과 해석·문서에 이 한계를 박는다.
  (진짜 point-in-time 유니버스 = 상장/상폐·과거 시총·토큰 분류까지 필요 → v1 범위 밖.)

## 전략 (탐색공간 제한)

- **Regime(1순위), Keltner(2순위) 만 사용.** Donchian/SMA+stop은 후속.
- 이유(Codex): 4전략 × 10코인 = "전략 선택 × 코인 선택" 탐색공간 폭발 → 과최적화·스누핑 위험.
- 목적은 "전략 비교"가 **아니라** "분산 효과가 **전략을 바꿔도(Regime↔Keltner)** 유지되는가" 확인.

## 결합 방식 — 새 고정 도구 `portfolio.py`

Backtesting.py는 단일자산이라, 다자산은 **억지로 엔진을 바꾸지 않고** per-coin 결과를 결합한다(robustness.py처럼 고정 도구).

```text
# portfolio.py
per_coin_equity(symbols, strategy, timeframe="4h", **params) -> DataFrame
    # 각 코인에 backtest.run_backtest 실행 → 코인별 equity curve(시간축 정렬) 수집.
    # 코인 상장(데이터 시작) 전 구간 = 그 코인 equity는 '현금'(자본 그대로, 미참여).

combine_equal_weight(equities, cash=10_000) -> Series
    # 초기 자본을 코인 수로 등분 배정 → 각자 방치(매봉 리밸런싱 X) → 합산 포트 equity.
    # 상장 전 코인 몫은 현금 보유(타 코인에 재분배 X = 누수 방지).

portfolio_metrics(equity_series) -> dict     # 총수익/MDD/Sharpe
return_correlation(equities) -> DataFrame    # 코인별 전략 equity 수익률 상관행렬
```

- **누수 방지:** 코인별 신호는 자기 OHLCV 과거만(기존 전략 그대로). 상장 전 몫 재분배 금지. 미래수익 기반 필터 금지.
- v1은 **초기 동일자본 buy-and-hold식 합산**(매봉 리밸런싱·랭크 배분 없음). 진짜 횡단 랭크/리밸런싱 엔진은 **v2(별도)**.

## 검증 기준 (Codex)

**Primary (분산이 도움 됐나):**
- BTC 단독(같은 전략) 대비 **포트폴리오 MDD 감소**
- **Sharpe 개선**
- **총수익이 크게 훼손되지 않음**
- 포트 equity가 **특정 1~2개 코인에 의존하지 않음**

**Secondary:**
- 코인별 전략 성과 분포(몇 개가 이기나 / 다수가 방어하나)
- **상관행렬** 2종: 코인 B&H 수익률 상관 + 전략 equity 수익률 상관
- 5개 구간(segment)에서 BTC 대비 MDD 방어가 몇 번 재현되나
- 코인별 robustness는 **라이트**(per-coin full + segment + OOS 정도; 전 코인 풀 Phase 3는 과함)
- **BTC 제외 alt 바스켓**도 별도로 봄(BTC가 비교대상과 겹치므로 — alt만의 분산효과가 더 선명)

**금지:** point-in-time 흉내, 사후(ex-post) 가중치 최적화, 성과 좋은 코인만 사후 선별.

## 정직한 한계
- **survivor-biased major-coin 유니버스** → 후보 검증이지 시장 전체 검증 아님.
- 알트는 실제 스프레드가 0.1%보다 넓음(수수료 가정의 낙관). 한계 명시.
- v1 = "분산이 도움 되나" 확인. 진짜 횡단 모멘텀/리밸런싱 엔진은 v2.
- 분산도 "부자 되기"가 아니라 "같은 추세 엣지를 더 매끈하게(위험조정 개선)"가 기대치.

## 산출물
- `portfolio.py` (고정 결합 도구) + `tests/test_portfolio.py` (synthetic, data/ 비의존)
- 유니버스 데이터 수집(`fetch.py` 확장 또는 호출) — 코인 8~10개 4h
- `research/2026-06-29_phase7a_multicoin.ipynb` (포트 vs BTC단독 vs alt바스켓, 상관행렬, 구간 방어)
- 본 문서 + `docs/design/README.md` 인덱스

## 다음 (7b, 나중)
선물(숏/레버리지/펀딩) — 현물 다코인 검증 후. 레버리지 변동성타겟·carry 등.

*(결과·판정은 분석 실행 후 본 문서에 추가)*
