# Phase 7c-v2 — 추세+캐리 결합 net 재검증 (gross 환상 걷어내기)

> 7c(gross)는 추세+캐리 50:50이 MDD↓·Sharpe↑를 보였지만 캐리가 gross라 **개선폭이 과장**됐다(concept proof).
> 7b-v2에서 **net 캐리(haircut)가 통과**했으니, **같은 결합을 net 캐리로 다시 묶어** "분산 효과 중 무엇이 *진짜*였나"를 본다. 새 코드 없음(도구 재사용). Codex 자문 반영.

## 개요 / 목표 (한정)
**질문:** *"7c의 MDD↓·Sharpe↑ 중, 캐리를 gross→net(현실 haircut)으로 바꿔도 남는 건 무엇인가?"*
- 7c는 "gross concept proof"로 **보존**한다(이 문서는 별도). net 결과를 7c에 섞으면 gross/net 판정이 혼탁해짐.
- **새 코드 없음**: `net_carry_pnl`(7b-v2) + `combine_sleeves`/`portfolio_metrics`(7c) 재사용. 노트북+문서만.

## 범위 (Codex)
- 비교는 **같은 공통창**에서 `추세 단독` vs `추세 + net 캐리` (combine_sleeves 가중 분리). 일간, periods_per_year=365.
- 캐리 haircut: **본문 net 2%(base) + 4%(stress)**, 6%는 appendix/sanity.
- 검증 추세 4전략(Regime/Keltner/Donchian/SMA+손절) × 50:50. 가중 70/30·30/70은 sensitivity일 뿐 — **최적화·고정 금지**(가중 선택은 testnet 전까지 안 정함).
- 판정은 **"testnet 포트폴리오 후보"까지만** (Phase 4 후보 아님).

## 결과 (BTC 4h 추세 + BTC net 캐리, 일간, 같은 공통창) — [MDD% / Sharpe]
| 추세전략 | 추세 단독 | +gross 캐리 | **+net 2%** | **+net 4%** |
|---|---|---|---|---|
| Regime | -33.9 / 0.81 | -23.7 / 0.85 | **-24.5 / 0.82** | -25.3 / 0.79 |
| Keltner | -35.8 / 0.62 | -22.8 / 0.72 | **-24.0 / 0.67** | -25.2 / 0.62 |
| Donchian | -44.8 / 0.41 | -22.4 / 0.51 | **-23.5 / 0.46** | -24.5 / 0.42 |
| SMA+손절 | -52.9 / 0.39 | -27.4 / 0.50 | **-28.4 / 0.45** | -29.4 / 0.40 |

(Return은 gross 때와 동일하게 감소 — 캐리 수익이 추세보다 낮아 가중 평균이 내려감. MDD/Sharpe가 핵심.)

## 판정 — gross에서 무엇이 진짜로 남았나
✅ **낙폭(MDD) 개선 = 진짜고 robust.** 추세 단독 대비 결합 MDD가 **net 4%(stress)에서도 4전략 전부 크게 얕아짐**(예: Donchian -44.8→-24.5, SMA -52.9→-29.4, Keltner -35.8→-25.2). haircut을 올려도 거의 안 무너진다 — 이건 **gross 환상이 아니라 무상관 sleeve가 주는 실제 리스크 분산**이다. (haircut은 캐리의 *수익*만 깎지 *낙폭 평탄화*는 거의 안 건드림.)

🟡 **Sharpe 개선 = modest하고 haircut 민감.** net 2%(base)에선 4전략 중 3개(Keltner/Donchian/SMA)가 여전히 개선, Regime은 ~flat. **net 4%(stress)에선 전부 ~breakeven**(추세 단독과 비슷). 즉 위험대비 *수익* 개선은 gross가 보여준 것보다 얇고, 비용이 커지면 사라진다.

**결론:** 7c의 "MDD↓·Sharpe↑"는 net으로 보면 **"MDD↓는 진짜·견고, Sharpe↑는 modest·haircut 민감"**으로 갈린다. **무상관 엣지(캐리)를 더하면 *낙폭을 실제로 줄인다*는 게 net에서도 확인됨** = 7c가 "gross concept proof"에서 **"낙폭 분산은 실재"로 격상**. → **testnet에서 검증할 포트폴리오 후보**(추세 + net 캐리). 단 가중치는 미고정, Phase 4 후보 아님.

## ⚠️ 정직한 한계
- **net 캐리도 여전히 haircut proxy** (7b-v2 한계 그대로) — 거래소 파산·ADL·극단 basis·청산 tail은 **모델 밖**. 결합이 좋아져도 "실거래 가능"이 아니라 **"testnet worth doing"**.
- Return은 결합 시 감소(캐리가 저수익) — "낙폭을 사고 수익을 일부 판다".
- 단일 역사 경로·BTC 단일자산 추세 + BTC 캐리·1x. 가중치 최적화 안 함(sensitivity만).

## 산출물
- `research/2026-06-30_phase7c_v2_net_combine.ipynb` (4전략 × 추세단독/+gross/+net2/+net4 MDD·Sharpe 표 + 곡선 + haircut별 MDD/Sharpe 추이)
- 본 문서 + `docs/design/README.md` 인덱스. (새 코드/테스트 없음 — 기존 도구 테스트가 커버.)
