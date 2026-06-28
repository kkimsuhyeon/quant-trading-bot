# Phase 4 — 1단계: 섀도우 전진 테스트 (Shadow Forward-Test)

## 개요

검증된 4전략(Keltner / Regime / Donchian / SMA+손절)을 **라이브 BTC/USDT 4h에 전진(forward)**
적용해, **실거래 없이** "지금 들고 있을 포지션"을 주기적으로 기록한다.

> 목적: **백테스트가 라이브 데이터·로직과 어긋나는지(과최적화·버그·데이터 결측)를 싸게 들키기.**
> 실제 체결/슬리피지 측정은 **2단계(바이낸스 테스트넷)** 로 분리(이 문서 범위 밖, 1단계 검증 후 설계).

- 사용자 결정: **단계적**(섀도우 → 테스트넷) + **cron 운영**.
- 대상: BTC/USDT 4h, 후보 4개 전부(로깅이라 비용 ~0).
- 가드레일: 하네스(`backtest.py`)·전략·`robustness.py` **불변**. 새 파일만 추가.

## 핵심 설계 원칙

**시그널 재구현 금지 (divergence 방지).** 라이브 시그널을 새로 코딩하면 백테스트와 어긋날 위험이 크다.
대신 **기존 전략 코드를 그대로 `run_backtest`로 돌려, 마지막 완성봉 기준 "롱/현금" 포지션을 읽는다.**
→ 라이브 시그널 == 백테스트 시그널 (같은 코드). 하네스/전략 분리 철학 유지.

**미완성 캔들 배제 (룩어헤드/불완전봉 방지).** 라이브 fetch의 **마지막(현재 형성 중) 캔들은 버린다**
(`fetch.py`와 동일 규칙). 시그널은 완성된 봉만으로 계산.

## 구조 (새 파일 2개) — Codex 자문 반영

### 1. `paper_trade.py` — 라이브 로거 (cron이 `python paper_trade.py` 호출)
```text
fetch_live(symbol="BTC/USDT", timeframe="4h", limit=1000) -> DataFrame
    # ccxt 공개 API(키 불필요)로 최근 1000개 캔들. 마지막 미완성봉 제거(fetch.py 규칙 동일).
    # fetch.py의 clean_ohlcv 재사용 → _to_backtesting_format. limit=1000(≈5.5개월):
    # SMA200 워밍업 + 윈도우 경로의존성 완충(아래 한계 참조).

desired_position(df, strategy) -> int   # 1=롱, 0=현금
    # `_, stats = run_backtest(df, strategy); return int(stats._strategy.position.size > 0)`
    # (검증됨: Backtesting.py는 종료 시 강제청산 안 함 → 열린 포지션 = 현재 스탠스.
    #  _trades엔 열린 트레이드 안 들어옴 → 부적합. position.size 부호만 사용.)
    # ⚠️ `_strategy`는 private API → desired_position 단위테스트 필수(아래 테스트).

run_once(dry_run=False) -> None
    # 1) file lock (fcntl/lockfile) — cron 중복 실행 방지.
    # 2) fetch_live.
    # 3) staleness 체크: 마지막 완성봉 시간이 기대 범위(≈ now - 1봉±여유)인가? 너무 오래됐으면
    #    append 말고 error를 stdout/cron.log에 남기고 종료.
    # 4) 4전략 각각 desired_position 계산.
    # 5) idempotency: 각 (strategy, signal_bar_time)가 signals.csv에 이미 있으면 skip(중복 append 방지).
    # 6) 없으면 long-format으로 행 append + stdout 요약(cron 로그 확인용). dry_run이면 append 없이 요약만.
```
`__main__`: 인자로 `--dry-run` 지원, 기본은 `run_once()`.

### 2. `paper_report.py` — 오프라인 분석 (가끔 실행)
```text
# 1단계-1 범위(지금 구현): paper/signals.csv 읽어(같은 (strategy, signal_bar_time) 중복은 마지막만):
#  load_signals(): 멱등키 dedup + 정렬.
#  proxy_equity(): 시그널 변화 시 신호봉 종가에 proxy 체결(수수료 0.1%/side)로 전진 페이퍼 수익곡선.
#  ("체결" 대신 proxy_price/signal_close 용어 — 실제 다음봉 시가 체결 규칙과 혼동 방지.)
```
> **후속(데이터 누적 후 별도 task)**: same-period backtest 곡선과 라이브 시그널 *일치성 비교*는
> signals.csv에 라이브 데이터가 수 주 쌓인 뒤에야 의미가 있다. 지금은 로그가 비어 있어 비교 대상이 없으므로
> 1단계-1 범위에서 제외하고, 데이터가 쌓이면 추가한다(proxy 곡선 vs backtest 곡선을 분리해 표시 — 차이가
> 나는 게 정상, 어긋난 봉 = 데이터/로직 갭 경보). (Codex 자문: 범위와 문서 정렬.)

## 데이터/상태
- **`paper/signals.csv`** (append-only, **long-format**) = 단일 진실원천. 별도 state 파일 없음(2단계에서 필요).
  멱등키로 cron 중복·재실행에 견고.
- **스키마(컬럼)**: `run_at`(UTC), `symbol`, `timeframe`, `strategy`, `signal_bar_time`(마지막 완성봉),
  `signal_bar_close`, `desired_position`(0/1), `source_rows`, `lookback_bars`, `strategy_params`(파라미터 repr — 드리프트 감지).
- 멱등키 = (`strategy`, `symbol`, `timeframe`, `signal_bar_time`). 중복이면 run_once가 skip / report는 마지막만.
- `paper/`는 `.gitignore` (데이터처럼 레포 미포함).

## 운영 (cron)
- **봉 마감 ~10분 뒤** 실행(거래소 캔들 확정 지연 감안). UTC 4h봉 기준:
  ```cron
  10 0,4,8,12,16,20 * * *  cd /Users/test/workspace/quant-trading-bot && ./.venv/bin/python paper_trade.py >> paper/cron.log 2>&1
  ```
- 절대경로 + venv python 고정. 머신이 꺼져 있던 구간은 로그가 비는 것뿐(append-only라 안전, report가 빈 구간 표시).
- cron 셋업 안내는 본 설계 문서에 두고, 구현 후 README엔 최소 사용법만.

## 테스트 (synthetic, data/ 비의존)
- **`desired_position` (필수, private API 의존이라 중요)**:
  - 명확히 롱으로 끝나는 합성 데이터 → 1, 명확히 현금으로 끝나는 데이터 → 0.
  - 마지막 봉 하나를 바꾸면 포지션이 기대대로 바뀌는지(시그널 민감).
- `fetch_live`가 마지막 미완성봉을 제거하고 OHLC 포맷 반환(모킹/구조 검증).
- `run_once`가 올바른 long-format 스키마 행을 append(임시 디렉터리) + **같은 (strategy, signal_bar_time) 재실행 시 중복 append 안 함**(멱등성).

## 정직한 한계
- 체결가를 **완성봉 종가 proxy**로 가정 — 실제는 다음 봉 시가 + 슬리피지(2단계 테스트넷에서 측정).
- 4h라 결정 빈도 낮음 → **의미있는 표본엔 수 주~수개월** 필요. 즉시 결론 안 남(원래 그런 단계).
- 라이브·백테스트가 같은 바이낸스 소스라 데이터 *불일치*는 적지만, 결측/지연/리비전은 잡힘.
- 섀도우는 "시그널/데이터 정합성" 검증이지 "체결 현실성" 검증이 아니다(그건 2단계).
- **1봉 실행 지연(룩어헤드 아님, 안전한 지연):** 하네스가 `trade_on_close=False`(다음 봉 시가 체결)라,
  *마지막 완성봉*에서 난 시그널은 다음 봉 체결분이고 그 봉은 미완성이라 제거된다. 따라서 기록되는
  `desired_position`은 사실상 *직전 완성봉까지의 결정*을 반영 → 행의 `signal_bar_time`보다 한 봉 늦을 수 있다.
  이는 실거래 체결모델(종가 결정→다음 봉 체결)에 오히려 충실한 것이며, **report에서 라이브 vs 백테스트
  시그널 비교 시 이 구조적 1봉 지연을 "갭"으로 오인하지 않도록** 정렬에 감안한다.

## 산출물
- `paper_trade.py`, `paper_report.py` + 테스트
- `.gitignore`에 `paper/` 추가
- 본 문서 + `docs/design/README.md` 인덱스 + cron 셋업 안내(README)

## 2단계 (보류, 1단계 검증 후 설계)
바이낸스 **테스트넷 실주문**: API 키(사용자 생성) + `run_once`가 로그 대신 실제 (가짜돈) 주문 → 실제 체결/슬리피지/주문타입/API 검증.

*(구현 후 결과/관찰을 본 문서에 추가)*
