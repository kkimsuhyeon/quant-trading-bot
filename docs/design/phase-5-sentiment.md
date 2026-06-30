# Phase 5 — sentiment 오버레이 (Fear&Greed 필터, MVP)

> Phase 0에서 뚫어둔 `sentiment` 컬럼 + `use_sentiment` 스위치를 처음으로 *채우는* 단계.
> "가격이 아닌 재료(심리)가 검증된 추세 엣지에 새 정보를 더하나"를 **싸게** 본다. Codex 자문 반영.

## 개요 / 목표 (강하게 한정)
**질문 하나:** *"극탐욕(군중 심리) 구간을 피하면 검증된 추세전략의 곡선이 개선되나(MDD↓ / Sharpe↑)?"*
- AI가 매매를 정하는 게 **아니다**(가드레일 6). 여기선 AI조차 안 쓴다 — 이미 점수화된 **Fear&Greed 지수**를 feature로 받는다.
- baseline(`use_sentiment=False`) vs +sentiment(`True`) **백테스트 비교**로만 효과를 판정(가드레일 6).

## 가설 (결과 보기 **전** 고정 — pre-registration)
`notes/hypothesis_sentiment.md` 참조. 한 줄: **"Extreme Greed(F&G≥75)는 리스크 회피 오버레이지, 매수 신호도 숏도 아니다."**
- F&G와 추세는 원래 상관(탐욕↔상승, 공포↔하락)이라, **"추세는 아직 long인데 극탐욕"인 *발산* 지점**(거품 천장)을 거르는 게 가격이 못 주는 새 정보를 시험하는 것.
- 반대 방향(극공포 회피)은 Regime(가격>SMA200)이 이미 하락장에 현금이라 **중복** → MVP에서 제외.

## 룰 (Codex 합의)
```
if use_sentiment and fng_prev >= 75:   # fng_prev = 직전 확정 일간 F&G
    현금 (기존 보유 청산 + 신규 진입 차단)
else:
    기존 추세전략 규칙 그대로
```
- **임계 75 고정** = alternative.me 표준 "Extreme Greed" 밴드(75~100). **튜닝 금지.** (80은 절대 sweep 안 함 — 나중에 sensitivity appendix로만.)
- 극탐욕 청산은 **숏이 아니다**(과열 회피이지 bearish 예측 아님).

## 데이터 / 룩어헤드 (Codex 강조 — 누수 차단)
- **소스**: Crypto Fear&Greed Index (alternative.me API, 0~100 일간, 2018~). `data/`에 저장(gitignore).
- **정렬**: F&G의 날짜 D 값은 **D+1 00:00 UTC부터** 사용(당일 누수 차단) → 4h봉에 **forward-fill** → 신호는 완성봉 `sentiment[-1]`, 체결은 다음 봉(하네스 기본).
- **dtype**: sentiment 컬럼을 **numeric float**로 채운다(현재 `pd.NA`/object면 Backtesting indicator가 깨짐 — Critical).
- **결측 = 필터 off**(baseline처럼 동작). 결측 구간을 버리면 기간선택 편향이 생김 → 버리지 않는다.

## 구조 (하네스 불변)
- **F&G 수집**: `fetch.py`에 `fetch_fng()` + sentiment 컬럼 채우는 헬퍼(또는 `sentiment.py` 소도구). 현물처럼 재현 가능하게.
- **전략**: `RegimeFilter`(1순위)·`KeltnerBreakout`(보조)의 주석 처리된 `if self.use_sentiment:` 자리를 구현. 다른 전략·하네스는 안 건드림.
- **비교**: baseline(off) vs +sentiment(on)을 같은 데이터로 백테스트. (robustness.py로 OOS/구간도.)

## 검증 / 탈락 기준 (사전 고정 — Codex)
Primary = **Regime**, baseline 대비:
- **MDD**: 상대 10%+ 또는 의미있는 절대 pp 개선
- **Sharpe**: baseline 이상
- **Return**: baseline의 80% 미만으로 훼손되면 **실패**
- **turnover**: 크게 늘어 수수료로만 성능 깎으면 **실패**
- **구간/OOS**: 다수 구간에서 개선 없으면 "불안정" 판정

해석:
- **Regime 실패 → Phase 5 MVP 실패.** Keltner는 보조 재현용.
- 둘 다 개선 → sentiment 오버레이 후보. Keltner만 개선 → "전략 특이"로 낮춰 해석. 둘 다 악화 → **"F&G는 가격 추세에 새 정보를 못 준다"로 폐기.**

## ⚠️ 정직한 한계
- **추세전략에 극탐욕 회피는 추세 수익을 깎을 수 있다**(극탐욕=강한 상승장에 들어가 있고 싶은 구간). → **실패가 흔하다. 그래도 valid한 결론**(싸게 죽이기).
- turnover↑ → 수수료/세금 민감. 한계로 명시.
- F&G는 BTC/전체 시장 심리 지수(자산별 아님). ETH 등에도 같은 지수.

## 금지
임계 sweep(80은 appendix only), 숏, regime-switching식 해석("지금 탐욕장이니 전략 교체"), AI가 매매 결정.

## 산출물
- F&G 수집(`fetch.py`/`sentiment.py`) + sentiment 컬럼 채우기(numeric, t-1 shift, ffill) + `RegimeFilter`/`KeltnerBreakout` `use_sentiment` 구현 + 테스트(synthetic, 룩어헤드·결측off·청산룰 값검증)
- `research/2026-06-30_phase5_sentiment.ipynb` (baseline vs +sentiment: Return/MDD/Sharpe/turnover + 구간/OOS + F&G 분포)
- `notes/hypothesis_sentiment.md` + 본 문서 + `docs/design/README.md` 인덱스

*(결과·판정은 분석 실행 후 본 문서에 추가)*
