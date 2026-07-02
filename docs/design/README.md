# 설계 문서 (Design Docs)

이 폴더는 **확정된 설계 상세(how)**를 담는다. 루트 문서와 역할을 분리한다:

- **`PLAN.md`** (레포 루트) — **실행 로드맵**: 어떤 Phase를 어떤 순서로, 무엇을 산출하는지 (큰 그림 / what).
- **`docs/design/*`** — **확정된 설계 상세**: 각 Phase를 코드 레벨로 어떻게 만들지 (how).
- **`CLAUDE.md` / `AGENTS.md` / `.agents/collaboration.md`** — 에이전트 가드레일·협업 규칙.

> 큰 그림이 바뀌면 `PLAN.md`를, 특정 Phase의 구현 설계가 정해지면 이 폴더의 문서를 본다.

## 진행 방식

각 Phase는 **한 사이클**(상세 설계 → 구현 계획 → 구현 → 검증)로 진행하고,
완료한 뒤 다음 Phase를 설계한다. 한 번에 여러 Phase를 벌이지 않는다.

## Phase별 설계 문서

| Phase | 범위 | 상태 | 상세 문서 |
|---|---|---|---|
| 0 + 1 | 데이터 수집 + 백테스트 하네스 + SMA hello world | 설계 완료 (구현 전) | [phase-0-1-lab.md](phase-0-1-lab.md) |
| 2 | baseline 전략 비교 (추세추종 vs 평균회귀) | 구현 완료 (Phase 3 검증 대기) | [phase-2-baseline-compare.md](phase-2-baseline-compare.md) |
| 2b | 전략 확장 (Donchian / TSMom / MACD) + 6전략 비교 | 구현 완료 (Phase 3 검증 대기) | [phase-2b-more-strategies.md](phase-2b-more-strategies.md) |
| 2c | 시간단위 비교 (1h vs 4h, 동일 6전략) | 구현 완료 | [phase-2c-4h-compare.md](phase-2c-4h-compare.md) |
| 2d | 5년(폭락장 포함) 1h·4h 비교 | 구현 완료 | [phase-2d-5yr-crash.md](phase-2d-5yr-crash.md) |
| 2e | 추가 전략 탐색 (Keltner/Regime/Z-score) | 구현 완료 (Keltner·Regime 통과, Z-score 탈락) | [phase-2e-more-strategies.md](phase-2e-more-strategies.md) |
| 3 | 견고성 검증 (OOS / 워크포워드 / 민감도) | 구현 완료 (Donchian 통과·SMA 탈락) | [phase-3-robustness.md](phase-3-robustness.md) |
| 3b | ETH out-of-asset 재현 (Donchian) | 구현 완료 (ETH도 통과 — 2자산 검증) | [phase-3b-eth.md](phase-3b-eth.md) |
| 3c | SMA 리스크룰 보강 재검증 (손절 추가) | 구현 완료 (BTC+ETH 통과 — 2번째 후보) | [phase-3c-sma-stop.md](phase-3c-sma-stop.md) |
| 4 | 페이퍼 트레이딩 — 1단계 섀도우(전진 테스트) | 구현 완료 (proxy 곡선; 백테스트 비교·테스트넷은 후속) | [phase-4-shadow.md](phase-4-shadow.md) |
| 4b | 섀도우 cron 확장 (sentiment 로깅 + 펀딩 기록기) | 구현 완료 (섀도우 유지, 주문X) | [phase-4b-cron-extend.md](phase-4b-cron-extend.md) |
| 4c | 현물 demo 실행 엔진 (Keltner, 2단계=실제주문) | 구현 완료 (demo 시장가·킬스위치·dry-run; 현물 demo 인증OK·선물 demo는 마이그레이션 대기) | [phase-4c-demo-executor.md](phase-4c-demo-executor.md) |
| 5 | sentiment 오버레이 (Fear&Greed 필터) | 구현 완료 (약한·일관 양(+), Keltner만 사전바 통과 / Regime 미흡 — 게임체인저 아님) | [phase-5-sentiment.md](phase-5-sentiment.md) |
| 6 | 소액 실거래 (현물) | 예정 | — |
| 7a | 다코인 현물 포트폴리오 (분산 효과 검증) | 구현 완료 (분산효과 약함 — 크립토 고상관) | [phase-7a-multicoin.md](phase-7a-multicoin.md) |
| 7b-carry | 펀딩 캐리 (독립 손익원 존재 검증, v1) | 구현 완료 (첫 무상관 양수 엣지 — 단 gross, 실행미검증) | [phase-7b-carry.md](phase-7b-carry.md) |
| 7c | 추세+캐리 2-엣지 포트폴리오 (개념검증) | 구현 완료 (4전략 전부 MDD↓·Sharpe↑ — 단 gross 과장, concept proof) | [phase-7c-portfolio-combine.md](phase-7c-portfolio-combine.md) |
| 7b-v2 | 캐리 net 타당성 (비용·haircut 후 엣지 잔존) | 구현 완료 (✅통과 — net 양수, 상관~0 유지 → testnet 후보. 단 tail 모델밖) | [phase-7b-v2-carry-net.md](phase-7b-v2-carry-net.md) |
| 7c-v2 | 추세+캐리 결합 net 재검증 (gross 환상 걷어내기) | 구현 완료 (MDD↓는 net에서도 진짜·견고 / Sharpe↑는 modest·haircut 민감 → testnet 포트 후보) | [phase-7c-v2-net-combine.md](phase-7c-v2-net-combine.md) |
| 7b-live-prep | 선물 demo 안정성 로거 (실행기 전 read-only 검증) | 구현 완료 (cron HH:05 가동 — 48h 클린 게이트 관찰 중, 통과 시 캐리 실행기) | [phase-7b-live-prep-fapi-logger.md](phase-7b-live-prep-fapi-logger.md) |
| 7b+ | 확장 (선물 롱/숏·레버리지) | 예정 | — |
