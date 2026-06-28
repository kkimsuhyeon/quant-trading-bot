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
| 3 | 견고성 검증 (OOS / 워크포워드 / 민감도) | 구현 완료 (Donchian 통과·SMA 탈락) | [phase-3-robustness.md](phase-3-robustness.md) |
| 3b | ETH out-of-asset 재현 (Donchian) | 구현 완료 (ETH도 통과 — 2자산 검증) | [phase-3b-eth.md](phase-3b-eth.md) |
| 4 | 페이퍼 트레이딩 (테스트넷) | 예정 | — |
| 5 | AI sentiment 레이어 | 예정 | — |
| 6 | 소액 실거래 (현물) | 예정 | — |
| 7 | 확장 (포트폴리오 / 선물) | 예정 | — |
