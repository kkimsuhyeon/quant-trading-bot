# Phase 7b-live-prep — 선물 demo 안정성 로거 (read-only)

> 방금 unblock된 선물 demo(`demo-fapi.binance.com`)에서 **캐리 실행기를 만들기 전에**,
> 엔드포인트가 며칠간 안정적으로 인증·조회되는지 **read-only로 확인**하는 단계.
> 목적: "demo-fapi가 계속 살아있고 auth/스키마/조회가 일관적인가"를 관찰. **주문 0건.**

## 배경 (왜 지금)
- 2026-07-01 오전까지 demo-fapi가 `-2008`로 막혀 캐리(선물) 실행 불가였다.
- 같은 날 재확인 결과 **unblock**: `fapiPrivateV2GetAccount` 성공(margin ~10,495 USDT, `canTrade=True`),
  `positionRisk`/`premiumIndex` 조회 OK. 공식문서도 **testnet REST = `https://demo-fapi.binance.com`** 확인.
- **방금 풀린 엔드포인트**라 실주문(캐리) 실행기 전에 안정성부터 며칠 관찰한다. (안전 우선)

## 가드레일 (필수)
- **읽기 전용.** 주문/레버리지/마진/포지션 변경 엔드포인트는 **코드에 넣지 않는다.**
  (state-changing 함수 부재를 코드 리뷰로 확인)
- **mainnet 유출 차단.** 실행 전 거래소의 **모든 fapi URL이 `demo-fapi.binance.com`인지 assert.**
  하나라도 아니면 즉시 중단(조회 전).
- **시크릿·raw 응답 헤더 로깅 금지.** 필요한 필드만 파싱해 기록.
- **하네스/전략 불변.** 신규 모듈만 추가, 기존 코드 미변경.

## 구조 — 신규 모듈 `fapi_demo_logger.py`
```text
load_env()                                          # .env → os.environ (demo_executor 패턴 재사용 가능)
make_fapi_exchange() -> ccxt.binance                # defaultType=future, 모든 fapi URL을 demo-fapi로 치환 + assert
  # 키: BINANCE_DEMO_API_KEY/SECRET → 없으면 BINANCE_TESTNET_* 폴백. 둘 다 없으면 RuntimeError
_assert_demo_fapi(exchange)                         # urls['api'] 중 fapi* 값이 전부 demo-fapi.binance.com인지 검증
parse_account(raw) -> dict                          # walletBalance, availableBalance, canTrade, updateTime
count_open_positions(raw_positionrisk) -> int      # positionAmt != 0 개수
parse_premium(raw, symbol) -> dict                 # markPrice, indexPrice, lastFundingRate, nextFundingTime
run_once(exchange=None, now=None) -> dict           # 아래 흐름. status/premium 행 반환(테스트가 값으로 검증)
```

### `run_once` 흐름 (전부 read-only)
1. exchange 생성(없으면) → `_assert_demo_fapi` (mainnet 유출 차단).
2. **latency 측정**: `fapiPublicGetTime` 호출 왕복 ms.
3. **account**: `fapiPrivateV2GetAccount` → `parse_account`. (auth_ok)
4. **positions**: `fapiPrivateV2GetPositionRisk` → `count_open_positions`. (positions_ok)
5. **premium**: BTC/ETH `fapiPublicGetPremiumIndex` → `parse_premium`. (premium_ok)
6. **부분 실패 허용**: 2~5 각 블록 독립 `try/except`. 하나 실패해도 **status 한 줄은 무조건 기록**
   (해당 `*_ok=False` + `error` 컬럼에 `type: msg` 요약, 최대 200자).
7. append-only로 CSV 기록. (dry가 아니라 read-only라 항상 기록해도 안전)

## 로깅 항목 / 산출물 (append-only, `paper/` = gitignore)
- **`paper/fapi_demo_status.csv`** — 실행당 1행
  `run_at, latency_ms, auth_ok, wallet_balance, available_balance, can_trade, acct_update_time, positions_ok, n_open_positions, premium_ok, error`
- **`paper/fapi_demo_premium.csv`** — 실행당 2행(BTC/ETH)
  `run_at, symbol, mark_price, index_price, last_funding_rate, next_funding_time`
- 포지션 상세 파일은 두지 않는다: 이 단계엔 주문이 없어 항상 0포지션 → `n_open_positions`(개수)와
  `positions_ok`(읽기 성공)만 status에 남긴다. (YAGNI)

## 안정성 판정 게이트 (사전 고정)
**48시간 클린 → 다음 단계(캐리 실행기, 옵션1)로 진행.** "클린" 정의:
- **auth 실패 0** (`auth_ok=True` 연속)
- **핵심 필드 결측 0** (status/premium 필수 컬럼 빈값 없음)
- **`next_funding_time` 정상 진행** (단조 증가·합리적 8h 간격)
- **잔고/포지션 읽기 일관** (walletBalance 비정상 급변·스키마 붕괴 없음)
- 판정은 관찰 후 `paper/fapi_demo_status.csv`를 사람이(=사용자와 함께) 확인해 결정.

## 운영 (cron)
- 시간당 1회, **`5 * * * *`** (`HH:05`). demo 실행기(`:10`)·섀도우(`:10`)와 시각 분리.
- `cd <repo> && ./.venv/bin/python fapi_demo_logger.py >> paper/fapi_demo_cron.log 2>&1`.
- 등록은 **구현·검증·머지 후** 사용자 승인하에.

## 테스트 (synthetic — ★라이브 호출 절대 없음)
fake exchange 주입으로 값 검증(네트워크 0):
- account/positions/premium 정상 → status 1행 + premium 2행, 필드 정확.
- **부분 실패**: premium이 raise → `premium_ok=False`, status는 여전히 기록, account 값 보존.
- **mainnet-leak assert**: fapi URL이 `fapi.binance.com`(비-demo)이면 `_assert_demo_fapi`가 raise.
- `count_open_positions`: positionAmt 0/비0 혼합 카운트.
- `parse_premium`/`parse_account`: 필드 매핑·형변환.

## 범위 밖 / 다음 (옵션1 = 캐리 실행기)
- 실제 캐리 주문(숏-퍼프 + 롱-현물), 포지션 진입/청산, 자본배분, 킬스위치(선물) = **다음 단계**.
- 이 단계는 오직 "엔드포인트 안정성 관찰"까지.

## 산출물
- `fapi_demo_logger.py` + `tests/test_fapi_demo_logger.py` (synthetic, fake exchange)
- 런타임 산출물(둘 다 `paper/` = gitignore): `fapi_demo_status.csv`, `fapi_demo_premium.csv`, `fapi_demo_cron.log`
- 본 문서 + `docs/design/README.md` 인덱스 갱신
