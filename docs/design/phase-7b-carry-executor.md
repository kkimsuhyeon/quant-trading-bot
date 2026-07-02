# Phase 7b-carry-executor — 캐리 양다리 demo 실행기 (숏 퍼프 + 롱 현물)

> 7b/7b-v2에서 검증된 캐리 엣지(무상관·net 양수)를 **demo 환경(가짜 돈)에서 실제 주문으로 리허설**하는 단계.
> 초점은 "델타중립 수익기"가 아니라 **"부분실패를 보상(compensate)할 수 있는 demo 양다리 실행기"**다 (Codex 합의).
> demo 펀딩은 합성이라 **경제성 검증이 아니라 배관(plumbing) 검증**이 목적이다.

## 개요 / 목표 (강하게 한정)

BTC/USDT 캐리 포지션(선물 demo `demo-fapi`에 퍼프 숏 + 현물 demo `demo-api`에 현물 롱, 1x 무레버리지
동일 base 수량)을 여는·유지하는·닫는 최소 실행 엔진.

- 검증 대상: 양다리 진입/청산이 안전하게 되나 · 부분실패 시 보상 트랜잭션이 작동하나 ·
  킬스위치/margin 가드가 자동으로 도나 · 프로세스 사망 후 재개가 되나.
- **완전한 원자성은 불가능하다.** 설계 원칙은 "atomic"이 아니라 **"compensating transaction +
  불확실 시 자동 재시도 금지(halt)"** (Codex).

## 가드레일 (필수)

- **여전히 demo(가짜 돈).** 실거래는 별도 단계(가드레일 1).
- **첫 `--live` 주문은 48h 클린 게이트(7b-live-prep, 2026-07-04경 판정) 통과 후에만.**
  그전엔 구현·synthetic 테스트·dry-run까지.
- **1x 무레버리지 델타중립만** (7b-v2에서 사전 고정 — 레버리지는 금지).
- **always-on** (7b-v2 검증 모델 그대로 — 동적 진입 임계값 = 최적화 시작이므로 금지).
- **리스크 우선(가드레일 5):** 2층 킬스위치 + 보수적 사이즈 + 정합 체크. 자동으로 돈다.
- **mainnet 유출 차단:** 주문 전 양쪽 엔드포인트 demo assert (fapi_demo_logger 패턴).
- **하네스/전략 불변.** 신규 모듈만 추가.

## 구조 — 신규 모듈 `carry_executor.py` (기존 재사용)

```text
make_fapi_exchange()            # fapi_demo_logger에서 import (demo-fapi 치환 + mainnet-leak assert)
make_spot_exchange()            # demo_executor 패턴 (demo-api 치환 + assert)
get_carry_state() / save_state  # paper/carry_state.json — phase·intent·수량·high_water·halted
run_once(live=False, confirm_open=False, symbol="BTC/USDT") -> dict
  # 락 → 상태 로드 → 양쪽 잔고/포지션 조회 → phase별 분기(아래 상태기계) → 감사 로그
```

- **재사용:** fcntl 단일 락(별도 `.carry_lock`) · append-only 감사 CSV · intent 저장 후 주문 ·
  quoteOrderQty/precision/min-notional 처리 · dust 판정 (전부 demo_executor에서 검증된 패턴).
- **ETH 확장 자리:** `symbol` 파라미터만. 구현·검증은 BTC 통과 후.

## Phase 상태기계 (핵심 — 프로세스 사망/부분실패 견딤)

```text
idle → opening_futures → opening_spot → open
open → closing_futures → closing_spot → idle
(모든 상태) → halted_manual   # 수동 리셋 전 신규 주문 금지
```

- 각 전이 **직전에** intent(phase·수량·notional·타임스탬프)를 state에 저장하고 주문한다.
- 다음 실행이 중간 phase를 발견하면(=직전 실행이 죽음): **자동 신규 진입 금지**, 실제
  포지션 스냅샷과 대조 → 명확하면 이어서 진행(예: opening_spot에서 죽었고 선물 숏 확인됨 →
  현물 매수 재개), **불명확하면 halted_manual**.

## 진입 흐름 (선물 먼저 — 더 불안정한 다리부터)

```text
precheck: 양쪽 auth·잔고·canTrade·기존 포지션 0 확인. 하나라도 이상 → 진입 안 함
notional = min(선물 availableBalance × 0.30, 현물 USDT × 0.95)   # 보수적 시작 (50%는 나중)
1. 선물 숏 시장가 (opening_futures) → positionRisk로 실제 체결량 확인
   실패 → 아무 일도 안 일어남 = 깨끗한 중단 (보상 불필요)
2. 확인된 숏 수량만큼 현물 매수 (opening_spot) → open
   실패/부분체결 → 즉시 선물 reduce-only 청산(보상 트랜잭션)
   보상도 실패 → halted_manual + naked_exposure=true + exposure 스냅샷 저장. 자동 재시도 금지
```

- 선물 먼저인 이유: ① demo-fapi가 둘 중 더 불안정(최근 unblock) — 실패 확률 높은 다리를
  먼저 시도하면 보상 자체가 불필요한 경우가 많음. ② 남은 다리가 현물 롱이면 청산 위험이
  없는 양성 노출 (숏 단독보다 안전).

## 청산 흐름 (상태별 "위험 다리 먼저" — Codex)

```text
선물 숏 존재 → reduce-only 청산 먼저 (closing_futures) → 현물 매도 (closing_spot) → idle
  현물 매도 실패 → 잔여 현물 롱은 양성(청산 위험 없음) → halted_manual만, 재시도 금지
현물만 존재(선물 없음) → 바로 현물 매도
선물만 존재(naked short) → reduce-only 청산이 최우선
크래시 후 closing_* 재개 → 청산은 이어가되 halted_manual로 종결 (중단 원인 불명 → 수동 확인)
```

- **선물 주문은 implicit fapi 엔드포인트(`fapiPrivatePostOrder`)로만** 낸다 — ccxt unified
  주문("BTC/USDT")은 현물 마켓으로 해석돼 mainnet 현물 URL로 라우팅됨(최종 리뷰에서 확정).
  implicit 경로만 `_assert_demo_fapi`가 실제로 커버한다.

## 리스크 관리 (2층 킬스위치 + 정합 체크 — 매 실행 자동)

1. **합산 equity DD −10%**: equity = 현물(USDT + base×가격) + 선물(walletBalance + UPnL).
   고점(high_water) 대비 −10% → halted 저장(먼저) → 청산 흐름 1회. 델타중립이라 −10%면
   뭔가 크게 잘못된 것 (현물 demo 실행기의 −15%보다 타이트).
2. **선물 margin 가드**: availableBalance / walletBalance < 0.5 → halted + 청산.
   (margin 필드의 demo 신뢰성은 48h 로거 데이터로 최종 확인 — Codex)
3. **다리 정합 체크**: |현물 base 보유 − |퍼프 숏 수량|| > dust 허용치(가격×차이 < min_notional
   이면 dust — demo_executor 판정 재사용) →
   **자동 보정 주문 금지, halted_manual + 수동확인만** (v1은 탐지+정지까지 — 자동
   리밸런싱은 주문 폭주/오판 위험, Codex).

## 안전 게이트 (실행 플래그)

- 기본 **dry-run**: 계산·판단·로그만, 주문 0.
- `--live`: 유지·킬스위치·청산·보상만 가능. **신규 진입 불가.**
- `--live --confirm-open`: 신규 진입 허용 (이중 확인 — 첫 진입은 사람이 의도적으로만).
- `--live` 시작 전 양쪽 fetch_balance demo assert (엔드포인트/키 불일치 시 주문 전 중단).

## 테스트 (synthetic — ★라이브 주문 절대 없음, fake exchange 2개 주입)

- 진입 성공 경로 (선물 체결량 → 현물 수량 일치, phase 전이, CSV 기록)
- 선물 실패 → 깨끗한 중단 (주문 0, idle 유지)
- 현물 실패 → 선물 reduce-only 보상 발동
- 보상 실패 → halted_manual + naked_exposure + 스냅샷
- 킬스위치 2종 (equity DD −10% / margin < 0.5) → halted 저장 후 청산 1회, 재진입 차단
- 정합 깨짐 → 보정 주문 없이 halted_manual
- 중간 phase에서 재시작 → 명확하면 재개 / 불명확하면 halt (자동 신규 진입 없음)
- 멱등성 (open 상태에서 재실행 → 주문 0) · mainnet-leak assert 양쪽
- dry-run에서 주문 함수 호출 0 (demo_executor의 mainnet-leak assert 테스트 패턴)

## 운영

⚠️ **선행 결정(첫 --live 전, 사용자와)**: 캐리는 Keltner demo 실행기와 **같은 현물 demo 계정·BTC를
공유**한다. Keltner 청산 신호가 캐리의 현물 헷지를 전량 매도하면 naked 숏이 남는다(정합 체크가
halt는 하지만 노출은 사람 개입 전까지 유지). → 캐리 --live 전에 ①별도 demo 서브계정/키 분리 또는
②캐리 가동 기간 Keltner cron 중지 중 하나를 결정해야 한다.

1. 구현·리뷰·머지 후: dry-run으로 판단 로그 수 회 확인.
2. **48h 게이트 통과 판정(사용자와 함께) 후** `--live --confirm-open`으로 첫 진입 1회.
   dry-run은 주문 경로에 도달하지 않으므로, 첫 진입 시 최소 수량 선물 주문이 실제로
   **demo-fapi에 도달하는지** 응답으로 확인하는 것까지가 검증이다.
3. 이후 cron 매시 **HH:15** (`:05` 로거·`:10` 실행기/섀도우와 분리, `cd <repo> &&` 접두어 필수):
   유지·킬스위치·정합 체크만 자동 (`--live`, confirm-open 없음 → 신규 진입은 절대 자동 안 됨).
4. 로그: `paper/carry_state.json` + `paper/carry_orders.csv` + `paper/carry_cron.log` (전부 gitignore).

## 범위 밖 / 다음

ETH(파라미터 자리만) · 다코인 캐리 바스켓 · 레버리지 · 자동 리밸런싱/자동 보정 ·
동적 진입 임계값 · 지정가 주문 · 추세+캐리 포트폴리오 결합(7c, 개별 검증 후) · **실거래**.

## ⚠️ 정직한 한계

- **demo 펀딩은 합성** → 이 단계가 성공해도 "캐리가 돈 번다" 검증이 아니라 "주문 기계가
  작동한다"까지다. 경제성·실제 basis/슬리피지는 소액 실거래에서만 드러난다.
- 현물 demo와 선물 demo는 **지갑 분리** → 실거래의 통합 마진/이체와 운영 모델이 다르다.
- 모델 밖 tail(거래소 파산·ADL·극단 basis)은 여전히 밖 (7b-v2 한계 그대로).

## 산출물

- `carry_executor.py` + `tests/test_carry_executor.py` (synthetic, fake exchange 2개)
- 런타임(전부 `paper/` = gitignore): `carry_state.json`, `carry_orders.csv`, `carry_cron.log`
- 본 문서 + `docs/design/README.md` 인덱스 갱신
