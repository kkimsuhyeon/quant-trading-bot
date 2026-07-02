# HANDOFF — 현재 상황 (2026-07-02)

> 새 세션/컨텍스트 재시작용 요약. 상세는 `docs/design/*`(README 인덱스) + `.superpowers/sdd/progress.md`(로컬 원장) + auto-memory 참조.
> main HEAD = `c5495c5`, 전체 **107 tests green**. 모든 Phase가 main에 머지됨.

## 이 프로젝트
크립토 퀀트 **"전략을 싸게 검증하는 실험실"** (돈 버는 봇 아님). ccxt+pandas+Backtesting.py, Python 3.13, `.venv`.
가드레일: 검증 없는 실거래 금지 / 하네스·전략 분리 / 룩어헤드 금지 / 리스크 우선(킬스위치) / AI는 도구 / 과최적화·regime-switching 금지. (`CLAUDE.md`)

## ★ 지금 *가동 중*인 것 (로컬 Mac cron 3줄 — 맥 켜져 있을 때만, 전부 `cd <repo> &&` 접두어 필수)
1. **섀도우** `paper_trade.py` (4h, 6×/일, HH:10): 6전략 신호+sentiment+펀딩 → `paper/` 로깅(주문X).
2. **demo 실행엔진** `demo_executor.py --live` (매시간 HH:10): **Keltner를 현물 Demo(`demo-api`)에 실주문**(가짜돈). 현재 현금 대기(`action=none`), 에러 0, 킬스위치 −15%, halted=false.
3. **★NEW fapi 로거** `fapi_demo_logger.py` (매시간 HH:05): **선물 demo(`demo-fapi`) read-only 안정성 로거**. auth/계정/포지션/펀딩+latency → `paper/fapi_demo_status.csv`·`fapi_demo_premium.csv`. 주문 0.
   - **목적: 48h 클린 게이트** — auth 실패 0·핵심 필드 결측 0·nextFundingTime 정상 진행·잔고 일관 → 통과 시 **캐리 선물 실행기** 구축(다음 단계로 합의됨).
   - 첫 실행 OK: auth=True, wallet ~10,505 USDT, premium_ok=True, latency 118ms. 관찰 시작 2026-07-02.

## ★ 최근 큰 변화 (2026-07-01~02)
- **선물 demo unblock**: 내내 -2008로 막혀 있던 `demo-fapi.binance.com`이 풀림(같은 키로 인증 성공, canTrade=True, margin ~10.5k). 공식문서상 testnet REST=demo-fapi 확인. → 캐리(유일 무상관 엣지)의 실행 리허설 경로가 열림.
- **7b-live-prep 완료**(main 머지): read-only `fapi_demo_logger.py` — make_fapi_exchange(모든 fapi URL→demo-fapi 치환+mainnet-leak assert, run_once 주입경로도 assert), 부분실패 허용(블록별 try/except, status 1행은 무조건 기록), premium_ok=BTC/ETH 양쪽, error 200자, append-only CSV, fcntl 락(.fapi_demo_lock — demo의 .demo_lock과 별개). 리뷰: opus final Ready + Codex(Important 1=주입경로 assert 우회→해소).
- **테스트 오염 버그 수정**: test_demo_executor.py reconcile 테스트가 실제 `paper/demo_orders.csv`를 오염(가짜 b1 행) → autouse chdir(tmp_path) fixture로 격리(c5495c5). 가짜 행 청소 완료, 재발 0 검증.

## 검증 결과 (핵심 — 전부 정직한 결론)
- **추세/돌파 4종**(Keltner·Regime·Donchian·SMA+손절, BTC+ETH 4h): 검증 통과. **유일 생존 현물 엣지 = "낙폭 방어"**(초과수익 아님). 서로 고상관.
- **평균회귀·1h·짧은모멘텀**: 전부 탈락. 10전략×10코인 전수 — 새 엣지 없음.
- **캐리(펀딩, 7b/7b-v2)**: **유일한 무상관(상관~0) 양수 엣지.** net(haircut 2~6%) 후도 BTC/ETH 양수(연 3~5%). tail(거래소 파산/ADL)은 모델 밖 — 'testnet 후보'까지만.
- **추세+캐리 결합(7c/7c-v2)**: MDD 분산은 net에서도 진짜·견고, Sharpe 개선 modest. testnet 포트 후보(가중 미고정).
- **sentiment(F&G≥75 회피, Phase 5)**: 약하게 일관 도움이나 Keltner만 사전 바 통과 → 보편 오버레이 승격 안 함.
- **다코인 분산(7a)**: 약함(크립토 고상관).

## 알아둘 것 / gotcha
- **키**: `.env`(gitignore)에 `BINANCE_TESTNET_API_KEY/SECRET`(=Spot Demo 키, 선물 demo도 이 키로 인증됨). `BINANCE_DEMO_*`가 우선, TESTNET는 폴백. 키값은 채팅에 붙여넣지 않기.
- **cron 함정**: `cd <repo> &&` 접두어 없으면 조용히 실패(CWD=$HOME). 이 실수 2회 발생 — 등록/수정 시 `crontab -l | grep -c "cd /Users/test/workspace/quant-trading-bot &&"` = 3 확인.
- **demo/live 변경은 최소 1회 실환경 dry 검증**(Codex 합의 체크리스트) — fake exchange 테스트가 거래소 API 경계(sapi 404 등)를 못 잡음.
- **4h 고정 이유**: 1h는 수수료/whipsaw로 사망(실증). 닫힌 봉만 사용(룩어헤드 방지) — 봉 지연은 정상.
- `paper/`·`data/`·`.env`·`.superpowers/`는 gitignore(로컬 전용).

## 코드 맵
- 하네스(고정): `backtest.py`, `robustness.py`(OOS/워크포워드/민감도).
- 전략(부품): `strategies/*.py` — 검증 4종 + 폐기·탐색용. `use_sentiment` 스위치(Regime/Keltner 배선).
- 도구: `carry.py`(펀딩 손익 gross+net), `portfolio.py`, `sentiment.py`(F&G), `fetch.py`, `paper_trade.py`(섀도우), `demo_executor.py`(현물 demo 실주문), **`fapi_demo_logger.py`(선물 demo read-only 로거, NEW)**.
- 문서: `docs/design/*`(설계·결과·판정, README 인덱스), `docs/plans/*`, `notes/hypothesis_*.md`, `notes/testnet_prep.md`.

## 협업/워크플로
- Codex: tmux `trader-codex`(자문+크로스리뷰). send-keys 본문→Enter 분리, capture-pane으로 제출 확인(`.agents/collaboration.md`).
- Phase당: brainstorming→설계doc→Codex자문→writing-plans→SDD(구현자+task리뷰 subagent=sonnet)→opus 최종리뷰+Codex 크로스리뷰→ff-merge→push. 원장 `.superpowers/sdd/progress.md`.
- 오너: 백엔드(Java) 배경, 파이썬·퀀트 초보. 작게 진행·이유 설명·정직한 기대치. 설계 승인 후엔 자율 사이클.

## 다음 (합의된 경로)
1. **48h 클린 게이트 관찰** (2026-07-04경 판정) — `paper/fapi_demo_status.csv` 확인: auth_ok 전부 True, error 빈값, next_funding_time 8h 간격 진행, wallet 일관.
2. **통과 시 → 캐리 선물 실행기 설계·구축** (숏-퍼프+롱-현물, demo-fapi 실주문 — brainstorming부터, Codex 협의).
3. 병행 관찰: 현물 demo Keltner 첫 체결(돌파 대기), 섀도우 로그 누적.
