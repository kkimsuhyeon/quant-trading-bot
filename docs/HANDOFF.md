# HANDOFF — 진행 상황 스냅샷

> 작성: 2026-06-28 (컨텍스트 compact 전 스냅샷).
> 다음 세션은 **이 문서 + `CLAUDE.md`(가드레일) + `PLAN.md`(로드맵) + `docs/design/README.md`(Phase 인덱스)**를 보고 이어가면 된다.

## 1. 한 줄 현황
Phase 0~2d 완료 — 검증 가능한 백테스트 실험실 + 전략 6개 + 5년 데이터 구축. **다음 = Phase 3(견고성 검증).**

## 2. 완료된 사이클

| Phase | 내용 | 결과 |
|---|---|---|
| 0+1 | 실험실(fetch+하네스) + SMA hello world | 파이프라인 관통 |
| 2 | 추세추종(SMA) vs 평균회귀(RSI/볼린저) | 둘 다 B&H에 짐 |
| 2b | 6전략 비교 (Donchian/TSMom/MACD 추가) | 거래 잦을수록 악화(수수료) |
| 2c | 1h vs 4h | 4h가 나음, SMA(4h) 첫 양수 |
| 2d | 5년(2022 폭락 포함) 1h·4h | 추세추종 낙폭 방어 입증, **Donchian(4h) 발굴** |

## 3. 핵심 발견 (누적)
- **1h 단순전략은 수수료에 먹힘 → 4h가 답.** (분봉·잦은매매 지양 원칙을 데이터로 확인)
- **승률 ≠ 수익**, 거래 빈도(=수수료)가 성패의 큰 변수.
- **추세추종의 가치 = 총수익이 아니라 낙폭 방어.** Donchian(4h) 5년: +50%, MDD **-46%** vs B&H **-77%**.
- **아직 총수익으로 B&H(+75%)를 이긴 전략은 없음** — 정상(깔때기 작동 중). 대부분 탈락이 목적.

## 4. 유망 후보 (Phase 3 검증 대상)
1. **Donchian 돌파 (4h)** — 5년 +50% / MDD -46% / 샤프 +0.24
2. **SMA 교차 (4h)** — 5년 +19% / MDD -60% / 샤프 +0.09

## 5. 레포 상태
- **main 최신: `b5b9897`**, 전체 **13 tests pass** (`python -m pytest -q`).
- **전략 6개** (`strategies/`): sma_cross, rsi_reversion, bollinger_reversion, donchian_breakout, ts_momentum, macd_cross. 모두 -5% 고정손절(신호 종가 proxy), `use_sentiment=False` 슬롯만(미구현).
- **하네스** (`backtest.py`, 고정): `FractionalBacktest`, `commission=0.001`, `spread=0.0`, `trade_on_close=False`. 전략 추가 시 수정 금지.
- **데이터** (`fetch.py`, 기본 `years=5`): `data/BTC_USDT_{1h,4h}.parquet` = 5년(2021-06~2026-06), **gitignore라 클론 후 `python fetch.py` 필요**.
- 비교 노트북: `research/`. 설계: `docs/design/`. 구현계획: `docs/plans/`. 전략 설명: `docs/strategies/`.
- **GitHub**: `git@github.com:kkimsuhyeon/quant-trading-bot.git` (origin/main 동기화됨).

## 6. 환경 / 실행
- **Python 3.13** + venv `.venv` + **`pandas<3` 고정** (중요: backtesting FractionalBacktest가 pandas 3.0 Copy-on-Write와 비호환 → read-only array 에러).
- 셋업: `python3.13 -m venv .venv && source .venv/bin/activate && python -m pip install -r requirements.txt`
- 실행: `python -m pytest -q` / `python fetch.py` / `python backtest.py`
- 함정: venv에선 `pip` 대신 **`python -m pip`**; `python`이 alias로 시스템 파이썬을 가리키면 `.venv/bin/python` 직접 사용.

## 7. 협업 (Codex)
- Codex가 tmux 세션 **`trader-codex`**에서 함께 작업. **레포 작업 전 협의 + 완료 후 크로스리뷰**가 규칙.
- 메시지 전송: **send-and-verify** (텍스트 보낸 뒤 Enter 따로, `capture-pane`로 제출 확인, 미제출 시 Enter만 재시도). 상세 = `.agents/collaboration.md`.
- 헬퍼: `scratchpad/send_to_codex.sh` (세션별 스크래치라 재생성 필요할 수 있음).

## 8. 다음 단계 — Phase 3 (견고성 검증)
- **목적**: Donchian/SMA(4h)의 +50%가 진짜 엣지냐, 이 특정 5년에만 운 좋았냐(과최적화)를 가름.
- **도구(만들 것, 재사용)**: 아웃오브샘플(앞 70%/뒤 30%), 워크포워드, 파라미터 민감도(손절 3/5/8% 등), 룩어헤드 재점검.
- 현 후보는 **탈락할 수도 있음 — 그게 정상**(싸게 죽이기).
- 대안 경로: 본인 전략 아이디어 / 다른 자산 / 숏·선물(P7).

## 9. 미구현(자리만) — 나중 Phase
- **sentiment**(데이터 컬럼 + 전략 `use_sentiment` 스위치 자리만): Phase 5
- **포트폴리오 결합**(검증 통과 전략들 동시 실행): Phase 7
- **선물(롱/숏·레버리지)**: Phase 7
- **ATR 적응형 손절 / 손절값 민감도**: Phase 3

## 10. 작업 방식 메모
- 설계 합의 후엔 전체 사이클(설계→계획→서브에이전트 TDD→내부리뷰→Codex 크로스리뷰→머지→push) **자율 진행** OK. 마지막에 결론 보고. (오너 = 백엔드 개발자, 파이썬·퀀트 초보 → "왜"를 설명하고 과신 금물.)
