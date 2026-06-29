# Phase 7b (carry) v1 — 펀딩 캐리: 독립 손익원 존재 검증

> Phase 7b(선물)의 첫 조각 = **캐리(펀딩 수확)**. 사용자가 "진짜 무관한 엣지"를 찾아 선택. Codex 자문 반영.

## 개요 / 목표 (강하게 한정)

**질문 하나:** *"무기한 선물의 펀딩이, 과거에 우리 추세 엣지와 *무관한* 독립 손익원으로 존재했나?"*

- **이건 "실행 가능한 전략"이 아니다.** "펀딩 프리미엄이라는 독립 P&L이 *역사적으로 있었나*"를 **싸게** 보는 것.
- 우리가 못 가진 **유일하게 시장중립(가격 방향 무관)인 엣지** 후보. 추세와 상관이 낮으면 → 진짜 분산재.

## 캐리란 (메커니즘)
무기한 선물엔 8h마다 롱↔숏이 주고받는 **펀딩비**. 과열(롱 우위)이면 롱→숏 지불(양의 펀딩).
**델타중립 캐리 = 현물 롱 + 같은 크기 perp 숏** → 가격 손익 상쇄(중립) → 숏 다리가 **펀딩 수확**(양일 때 받고, 음일 때 냄).

## v1 모델 (Codex 자문)
- **always-on** 델타중립(현물 롱 + perp 숏), notional 1.0. (조건부 진입은 전략 최적화 + lookahead 위험 → v1 제외, 보조 sanity로만)
- 매 8h **realized 펀딩**을 손익에 누적. 가격 손익은 **중립 가정으로 무시**(P&L = 누적 펀딩 − 수수료).
- **수수료 4-leg 1회만**: 진입(현물 매수 0.001 + perp 매도 0.0005) + 청산(현물 매도 0.001 + perp 매수 0.0005). 보유 중 리밸런싱 수수료 없음. (보수적 기본값; Binance perp taker는 더 낮을 수 있으나 보수적으로.)
- 룩어헤드: 각 timestamp의 **realized(정산) 펀딩**만 사용. always-on이라 미래 rate 보고 진입하지 않음 → 누수 위험 작음. (단 ccxt timestamp가 "정산 시각의 realized rate"인지 확인 — 보통 그러함.)

## 구조 — 새 도구 `carry.py`
백테스트 엔진이 아니라 **펀딩 시계열 계산**이다(robustness/portfolio처럼 고정 도구). 하네스/전략 미수정.
```text
carry_pnl(funding, notional=1.0, spot_fee=0.001, perp_fee=0.0005) -> pd.Series
    # funding = 8h realized funding rate Series(시간 인덱스).
    # equity = notional*(1 + cumsum(funding)) - 4-leg 수수료(진입 t0 + 청산 마지막).
    #   진입 수수료 = notional*(spot_fee+perp_fee), 청산 동일. (총 2*(spot_fee+perp_fee).)

carry_metrics(equity, funding) -> dict
    # Return%, 연율 Return%, Sharpe(펀딩수익 기준), MDD, 음수펀딩 구간 낙폭.

funding_stats(funding) -> dict        # 평균/중앙/5·95 percentile/음수비율
```
- 상관 분석은 노트북/컨트롤러에서: carry 수익률 vs (추세전략 equity 수익률, BTC 가격 수익률) — 공통 timestamp로 리샘플.

## 데이터
- BTC/USDT perp, ETH/USDT perp **펀딩 히스토리 8h** (5년, ccxt `fetch_funding_rate_history`, 페이지네이션). `data/`에 저장(gitignore).

## 검증 기준 (Codex)
**Primary:** 수수료 후 누적수익 > 0 · 연율수익/MDD 또는 Sharpe 의미 있나 · 음수펀딩 구간 낙폭 · BTC/ETH 같은 방향인가.
**Independence (핵심):** carry 수익률이 **추세전략 equity 수익률과 상관 낮은가** + **BTC 가격 수익률과 상관 낮은가**(진짜 델타중립이면 ~0). 낮아야 "진짜 분산재".
**추가:** 펀딩 분포(평균/중앙/5-95%/음수비율) · 연도별·구간별 수익(2021 bull/2022 bear/2024~25 유지되나) · BTC vs ETH 분산(둘 다 비슷=시장구조 프리미엄 / 한쪽만=자산특화).

## ⚠️ 정직한 한계 (강하게 — Codex)
- 이건 **gross-ish 펀딩 모델** — **basis 수렴·헷지 슬리피지·델타 드리프트·청산·마진콜·borrow/커스터디·perp 거래소·세금·운영 리스크를 *전부 뺀* 값.** **실제 거래 가능 수익이 아니다.** (보수적 하한도 아님 — 오히려 낙관.)
- **붐비는 트레이드** → 미래 엣지는 압축. **음수 펀딩 regime 존재**(약세장).
- **v1이 좋아 보여도 바로 Phase 4 후보로 올리지 않는다.** 실행 현실성은 **Phase 7b-v2**에서 별도로 요구. 펀딩 구현 위험은 현물 추세보다 훨씬 크다.

## 금지
임계 최적화, 레버리지, 청산/basis 모델링, 복리/리밸런싱 최적화, conditional 진입(v1 primary).

## 산출물
- `carry.py` + `tests/test_carry.py` (synthetic 펀딩 시계열, data/·네트워크 비의존)
- 펀딩 데이터 수집(fetch 확장/스크립트)
- `research/2026-06-29_phase7b_carry.ipynb` (손익곡선·연도별·분포·상관)
- 본 문서 + `docs/design/README.md` 인덱스

*(결과·판정은 분석 실행 후 본 문서에 추가)*
