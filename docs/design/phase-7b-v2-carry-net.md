# Phase 7b-v2 — 펀딩 캐리 net 타당성 (비용·haircut 후 엣지 잔존 검증)

> v1(7b-carry)은 "펀딩이 추세와 무관한 독립 *양수* 손익원으로 존재했나? → 그렇다(단 gross)"를 확인했다.
> v2는 **"그 gross 엣지가 현실 비용·haircut 후에도 남는가?"** 하나만 본다. **실거래 엔진이 아니다** —
> gross 캐리에 **결정적(deterministic) haircut을 단계적으로 얹는 net 타당성 테스트**. (Codex 자문 반영.)

## 개요 / 목표 (강하게 한정)
**질문 하나:** *"v1의 연 ~6% gross 캐리가, 현실적 수수료 + basis/슬리피지 haircut + 음수 펀딩 레짐을 반영한 net 기준으로도 양(+)의 엣지 margin을 남기나?"*
- v1: "독립 손익원 **존재**" → v2: "비용/haircut 후에도 **edge margin이 남나**".
- **가정 수프 금지.** 데이터로 할 수 있는 것만 모델링하고, 못 하는 것은 stress/haircut/tail-note로 분리.

## 모델 (Codex 합의)
```text
net_carry = gross_funding 누적 − 4-leg 수수료(진입+청산 1회) − 연 haircut 누적차감
```
- **1x 무레버리지 델타중립만 primary.** 레버리지는 청산/basis/margin 모델을 부르므로 **넣지 않는다**(v3/testnet 전 금지).

## v2에 넣을 것
1. **수수료 3시나리오 고정**(민감도만, 최적화 금지):
   - base: spot 0.10% / perp 0.05%  ·  low: 0.05% / 0.02%  ·  high: 0.20% / 0.10%
2. **basis/헷지 슬리피지 = 연 haircut 고정 차감**(정밀 basis 시계열 없음 → 정밀 모델 금지):
   - base 연 2% · stress 연 4% · severe 연 6%. → "v1 연 ~6%가 비용 후 남나"에 직접 답.
3. **음수 펀딩 레짐 = 데이터 기반**(가정 아님 — funding history 있음):
   - 최장 음수 펀딩 streak · 음수 구간 총손실 · rolling 90일 net 최악 수익.
4. **leverage/청산 = 모델링 안 함, stress note로 분리**:
   - "1x fully-funded 현물 + collateralized perp 숏 → 정상 마진에선 청산 목표 없음. 단 basis spike/거래소 위험은 tail로 남음."
5. **capacity/운영 리스크 = 수치화 안 함**: 거래소 파산·withdrawal halt·ADL·극단 basis blowup은 **모델 밖 tail로 명시**("net 추정에 미포함").

## v2에 넣지 말 것
perp mark/spot-perp basis 정밀 시계열 추정(데이터 없음), 동적 진입/청산 임계(최적화 시작), 레버리지 최적화, 펀딩 예측 모델, 다코인 캐리 바스켓(BTC/ETH 검증 후에만).

## 구조 — `carry.py`에 함수 추가 (하네스/전략 불변, v1 함수 재사용)
```text
net_carry_pnl(funding, notional=1.0, spot_fee=0.001, perp_fee=0.0005,
              annual_haircut=0.02, periods_per_year=1095) -> pd.Series
    # drag = annual_haircut / periods_per_year (매 8h basis/슬리피지 차감)
    # = carry_pnl(funding - drag, notional, spot_fee, perp_fee)  ← v1 재사용(DRY)

rolling_worst_return(equity, window=270) -> float   # 270 = 90일 * 3(8h/day). 최악 90일 net 수익.

negative_funding_stats(funding) -> dict
    # longest_neg_streak(연속 음수 8h 개수) · neg_total(음수구간 합) · neg_ratio
```
- 지표는 v1의 `carry_metrics`(periods_per_year=1095) 재사용.

## 검증 / 통과 기준 (사전 고정 — Codex)
- **base haircut(2%) 후 BTC·ETH 둘 다 net 연수익 > 0.**
- **stress haircut(4%) 후 최소 한쪽 또는 50:50 바스켓이 net 양수.**
- **severe haircut(6%) 후 음수면 정상** — 실패가 아니라 "**edge margin thin**"으로 해석.
- rolling 90일 net 최악 수익이 감당 가능한 수준인가.
- **추세전략과 상관 ~0 유지**(haircut은 deterministic이라 상관 구조를 거의 안 바꿔야 정상).
- **v2 통과해도 "testnet 후보"이지 바로 실거래 후보 아님.**

## ⚠️ 정직한 한계
- **haircut은 거친 proxy다**(연 2/4/6% 고정 차감) — 실제 basis/슬리피지는 시변·상태의존. 정밀 추정은 데이터 부재로 불가.
- **모델 밖 tail**(거래소 파산·ADL·극단 basis blowup·withdrawal halt)은 **net 추정에 미포함** — 실거래 위험은 이보다 큼.
- 단일 역사 경로(2021~2026) · BTC/ETH 2자산 · 1x만.

## 금지
레버리지, 정밀 basis 모델, 동적 임계 최적화, 펀딩 예측, 다코인 확장, "실거래 엔진" 스코프 확장.

## 판정 문구
- v1: "독립 손익원 존재" / **v2: "비용/haircut 후에도 edge margin이 남는가"**.

## 산출물
- `carry.py`에 `net_carry_pnl` + `rolling_worst_return` + `negative_funding_stats` + `tests/test_carry.py` 보강(synthetic 값검증)
- `research/2026-06-30_phase7b_v2_carry_net.ipynb` (3 fee×3 haircut net 표 + 음수레짐 지표 + rolling 최악 + 추세 상관 유지 확인)
- 본 문서 + `docs/design/README.md` 인덱스

*(결과·판정은 분석 실행 후 본 문서에 추가)*
