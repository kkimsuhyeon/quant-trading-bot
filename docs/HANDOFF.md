# HANDOFF — 현재 상황 (2026-07-01)

> 컨텍스트 compact/세션 재시작용 요약. 상세는 `docs/design/*` + `.superpowers/sdd/progress.md`(로컬 원장) + auto-memory 참조.
> main HEAD = `dff53e6`, 전체 **94 tests green**. 모든 Phase가 main에 머지됨.

## 이 프로젝트
크립토 퀀트 **"전략을 싸게 검증하는 실험실"** (돈 버는 봇이 아니라). ccxt+pandas+Backtesting.py, Python 3.13, `.venv`.
가드레일: 검증 없는 실거래 금지 / 하네스·전략 분리 / 룩어헤드 금지 / 리스크 우선(킬스위치) / AI는 도구지 트레이더 아님 / 과최적화·regime-switching 금지. (`CLAUDE.md`)

## ★ 지금 *가동 중*인 것 (로컬 Mac cron — 맥 켜져 있을 때만)
1. **섀도우** `paper_trade.py` (4h, 6×/일): 6전략 신호 + sentiment 변형 + 펀딩 → `paper/`에 로깅(주문X).
2. **demo 실행엔진** `demo_executor.py --live` (매시간): **Keltner를 바이낸스 *현물 Demo*에 실제 주문**(가짜 돈). 현재 Keltner=현금이라 매수 대기 중(`action=none`), 에러/실패 0. 킬스위치 −15%.
   - 로그·상태(전부 `paper/`=gitignore, 로컬전용): `demo_cron.log`, `demo_orders.csv`, `demo_state.json`(high_water 5000/halted false).
   - 중단: `crontab -e`로 demo 줄 삭제.

## 검증 결과 (핵심 — 전부 정직한 결론)
- **추세/돌파 4종**(Keltner·Regime·Donchian·SMA+손절, BTC+ETH 4h): **검증 통과. 유일 생존 엣지 = "낙폭 방어"**(초과수익 아님). 서로 상관 높음(≈같이 움직임).
- **평균회귀·1h·짧은모멘텀**: 전부 탈락(수수료·잡음). 10전략×10코인 다 돌려봄 — 새 엣지 없음.
- **캐리(펀딩, 7b/7b-v2)**: **유일한 무상관(상관~0) 양수 엣지.** net(haircut 2~6%) 후에도 BTC/ETH 양수(연 3~5%). → "testnet 후보"까지(★단 gross 한계·거래소tail 모델밖·실거래 아님).
- **추세+캐리 결합(7c/7c-v2)**: **낙폭(MDD) 분산은 net에서도 진짜·견고**, Sharpe 개선은 modest/haircut 민감. = "concept proof→낙폭분산 실재"로 격상. testnet 포트 후보(가중 미고정).
- **sentiment(Fear&Greed 극탐욕 회피, Phase 5)**: 약하게 일관 도움(Sharpe 7/8↑·MDD 악화0)이나 **Keltner만 사전바 통과, Regime 미흡** → 보편 오버레이 승격 안 함.
- **다코인 분산(7a)**: 약함(크립토 고상관). "코인 늘리기"는 분산 아님.

## ★ 미해결 / 알아둘 것
- **선물 demo(캐리용)는 막혀 있음**: `demo.binance.com` Demo Trading 키가 `demo-fapi.binance.com`에서 `-2008`(Demo Trading이 API로 현물만 노출, 선물은 마이그레이션 중, 6/22 점검 직후). 현물 demo는 인증OK·동작함. 엔진은 `BINANCE_DEMO_BASE_URL` env로 빼둬서 정리되면 엔드포인트만 교체하면 캐리로 확장.
- **키**: `.env`(gitignore)에 `BINANCE_DEMO_API_KEY/SECRET`(구 `BINANCE_TESTNET_*`도 폴백). `.env.example` 참조. `demo_executor.load_env()`가 .env를 os.environ에 주입.
- **4h 고정 이유**: 1h는 거래 3~4배→수수료/whipsaw로 죽음. 실증 확인. 봉 지연은 룩어헤드 방지(닫힌 봉만)이자 잡음 필터 = 스윙엔 정상.
- `paper/`·`data/`·`.env`·`.superpowers/`는 gitignore(로컬 전용, GitHub에 없음).

## 코드 맵
- 하네스(고정): `backtest.py`(FractionalBacktest, commission 0.001), `robustness.py`(OOS/워크포워드/민감도).
- 전략(부품): `strategies/*.py` — 검증본 4종 + 폐기·탐색용. `use_sentiment` 스위치 보유(Regime/Keltner만 배선).
- 도구: `carry.py`(펀딩 손익 gross+net), `portfolio.py`(다코인·sleeve 결합), `sentiment.py`(F&G fetch/attach), `fetch.py`(OHLCV+펀딩 수집), `paper_trade.py`(섀도우), `demo_executor.py`(demo 실주문).
- 문서: `docs/design/*`(설계·결과·판정, README 인덱스), `docs/plans/*`(구현계획), `notes/hypothesis_*.md`, `notes/testnet_prep.md`.

## 협업/워크플로
- Codex: tmux `trader-codex` (설계 자문 + 크로스리뷰). 각 Phase: brainstorming→설계doc→Codex자문→writing-plans→SDD(구현자+task리뷰 subagent, sonnet)→opus 최종리뷰+Codex 크로스리뷰→ff-merge→push.
- 사용자: 백엔드(Java) 배경, 파이썬·퀀트 초보. 작게 진행·이유 설명·정직한 기대치(과대주장 금지). 설계 승인 후엔 자율로 build→merge→push 사이클.

## 다음 후보 (사용자 결정 대기)
1. **demo에서 Keltner 관찰** (지금 가동 중 — 신호 뜨면 첫 체결 확인).
2. **다전략 확장** — 포트폴리오 배분기 필요(Phase 7 영역), 단 추세 상관 높아 분산효과 낮음.
3. **선물 demo 재시도** — 바이낸스 마이그레이션 정리 후 캐리.
4. **소액 실거래(Phase 6)** — 진짜 최종 관문(가드레일 충족 후).
5. 정리/일단락.
