# 선물 demo 안정성 로거 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 방금 unblock된 선물 demo(`demo-fapi.binance.com`)에서 auth·계정·포지션·펀딩을 시간당 read-only로 로깅해 며칠간 엔드포인트 안정성을 관찰한다.

**Architecture:** 신규 read-only 모듈 `fapi_demo_logger.py`. ccxt.binance(defaultType=future)의 모든 fapi URL을 demo-fapi로 치환 + mainnet-leak assert 후, latency/account/positions/premiumIndex를 부분실패 허용으로 조회해 append-only CSV 2개(`paper/fapi_demo_status.csv`, `paper/fapi_demo_premium.csv`)에 기록. 주문/상태변경 엔드포인트는 코드에 없다.

**Tech Stack:** Python 3.13, ccxt, pandas, pytest. `.venv/bin/python`. 기존 `demo_executor.py` 패턴 재사용.

## Global Constraints

- **읽기 전용.** 주문/레버리지/마진/포지션 변경 엔드포인트(create_order, set_leverage 등)를 코드에 넣지 않는다.
- **mainnet 유출 차단.** 조회 전 모든 fapi URL이 `demo-fapi.binance.com`인지 assert. 아니면 즉시 raise.
- **시크릿·raw 응답 헤더 로깅 금지.** 필요한 필드만 파싱해 기록. error 컬럼은 `type:msg` 요약 최대 200자.
- **하네스/전략 불변.** 신규 모듈만 추가. 기존 파일은 `docs/design/README.md` 인덱스 외 미변경.
- **부분 실패 허용.** account/positions/premium 각 블록 독립 try/except. 하나 실패해도 status 1행은 무조건 기록.
- **산출물은 `paper/`** (gitignore, 로컬 전용): `fapi_demo_status.csv`, `fapi_demo_premium.csv`.
- **키**: `.env`의 `BINANCE_DEMO_API_KEY/SECRET` 우선, `BINANCE_TESTNET_*` 폴백. 둘 다 없으면 RuntimeError.
- 테스트는 **synthetic fake exchange만** 사용, 네트워크·라이브 호출 0. (기존 `tests/test_demo_executor.py`의 `FakeEx` 패턴)

---

### Task 1: 순수 파서 + mainnet-leak assert + 상수

**Files:**
- Create: `fapi_demo_logger.py`
- Test: `tests/test_fapi_demo_logger.py`

**Interfaces:**
- Consumes: (없음)
- Produces:
  - 상수 `FAPI_DEMO_HOST="demo-fapi.binance.com"`, `FAPI_MAINNET_HOST="fapi.binance.com"`, `SYMBOLS=[("BTCUSDT","BTC/USDT"),("ETHUSDT","ETH/USDT")]`, `STATUS_CSV`, `PREMIUM_CSV`, `LOCK_PATH`, `STATUS_COLS`, `PREMIUM_COLS`
  - `parse_account(raw: dict) -> dict` → keys `wallet_balance:float, available_balance:float, can_trade:bool, acct_update_time`
  - `count_open_positions(raw: list) -> int` (positionAmt != 0 개수)
  - `parse_premium(raw: dict, symbol: str) -> dict` → keys `symbol, mark_price:float, index_price:float, last_funding_rate:float, next_funding_time`
  - `_assert_demo_fapi(exchange) -> None` (fapi* URL이 전부 demo-fapi면 통과, 아니면 RuntimeError)

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_fapi_demo_logger.py`:
```python
import pytest
import fapi_demo_logger as fx


def test_parse_account():
    raw = {"totalWalletBalance": "10495.28", "availableBalance": "10490.0",
           "canTrade": True, "updateTime": 1782910000000}
    a = fx.parse_account(raw)
    assert a["wallet_balance"] == 10495.28
    assert a["available_balance"] == 10490.0
    assert a["can_trade"] is True
    assert a["acct_update_time"] == 1782910000000


def test_count_open_positions():
    raw = [{"symbol": "BTCUSDT", "positionAmt": "0.0"},
           {"symbol": "ETHUSDT", "positionAmt": "1.5"},
           {"symbol": "SOLUSDT", "positionAmt": "-2.0"}]
    assert fx.count_open_positions(raw) == 2


def test_parse_premium():
    raw = {"markPrice": "58456.4", "indexPrice": "58460.0",
           "lastFundingRate": "0.0001", "nextFundingTime": 1782921600000}
    p = fx.parse_premium(raw, "BTC/USDT")
    assert p["symbol"] == "BTC/USDT"
    assert p["mark_price"] == 58456.4
    assert p["index_price"] == 58460.0
    assert p["last_funding_rate"] == 0.0001
    assert p["next_funding_time"] == 1782921600000


class _UrlEx:
    def __init__(self, api):
        self.urls = {"api": api}


def test_assert_demo_fapi_passes_when_all_demo():
    ex = _UrlEx({"fapiPublic": "https://demo-fapi.binance.com/fapi/v1",
                 "fapiPrivateV2": "https://demo-fapi.binance.com/fapi/v2",
                 "public": "https://api.binance.com/api/v3"})
    fx._assert_demo_fapi(ex)  # raise 안 하면 통과


def test_assert_demo_fapi_raises_on_mainnet_leak():
    ex = _UrlEx({"fapiPublic": "https://demo-fapi.binance.com/fapi/v1",
                 "fapiPrivateV2": "https://fapi.binance.com/fapi/v2"})  # ← 메인넷
    with pytest.raises(RuntimeError):
        fx._assert_demo_fapi(ex)
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_fapi_demo_logger.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fapi_demo_logger'`

- [ ] **Step 3: 최소 구현**

`fapi_demo_logger.py`:
```python
import os
import sys
import time
import fcntl
import pandas as pd
import ccxt
from demo_executor import load_env

FAPI_DEMO_HOST = "demo-fapi.binance.com"
FAPI_MAINNET_HOST = "fapi.binance.com"
SYMBOLS = [("BTCUSDT", "BTC/USDT"), ("ETHUSDT", "ETH/USDT")]  # (fapi심볼, 표시심볼)

STATUS_CSV = "paper/fapi_demo_status.csv"
PREMIUM_CSV = "paper/fapi_demo_premium.csv"
LOCK_PATH = "paper/.fapi_demo_lock"

STATUS_COLS = ["run_at", "latency_ms", "auth_ok", "wallet_balance", "available_balance",
               "can_trade", "acct_update_time", "positions_ok", "n_open_positions",
               "premium_ok", "error"]
PREMIUM_COLS = ["run_at", "symbol", "mark_price", "index_price", "last_funding_rate",
                "next_funding_time"]


def parse_account(raw):
    return {
        "wallet_balance": float(raw["totalWalletBalance"]),
        "available_balance": float(raw["availableBalance"]),
        "can_trade": bool(raw["canTrade"]),
        "acct_update_time": raw.get("updateTime"),
    }


def count_open_positions(raw):
    return sum(1 for p in raw if float(p.get("positionAmt", 0)) != 0)


def parse_premium(raw, symbol):
    return {
        "symbol": symbol,
        "mark_price": float(raw["markPrice"]),
        "index_price": float(raw["indexPrice"]),
        "last_funding_rate": float(raw["lastFundingRate"]),
        "next_funding_time": raw.get("nextFundingTime"),
    }


def _assert_demo_fapi(exchange):
    for k, u in exchange.urls["api"].items():
        if isinstance(u, str) and "fapi" in k.lower() and FAPI_DEMO_HOST not in u:
            raise RuntimeError(f"mainnet leak guard: {k}={u} (demo-fapi 아님)")
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv/bin/python -m pytest tests/test_fapi_demo_logger.py -v`
Expected: PASS (5개)

- [ ] **Step 5: 커밋**

```bash
git add fapi_demo_logger.py tests/test_fapi_demo_logger.py
git commit -m "feat(fapi): 선물 demo 로거 파서+mainnet-leak assert (Task1)"
```

---

### Task 2: `make_fapi_exchange` (URL 치환 + assert + 키)

**Files:**
- Modify: `fapi_demo_logger.py`
- Test: `tests/test_fapi_demo_logger.py`

**Interfaces:**
- Consumes: `_assert_demo_fapi`, `FAPI_MAINNET_HOST`, `FAPI_DEMO_HOST`, `load_env`
- Produces: `make_fapi_exchange() -> ccxt.binance` (defaultType=future, 모든 fapi URL을 demo-fapi로 치환한 뒤 `_assert_demo_fapi` 통과한 exchange)

- [ ] **Step 1: 실패하는 테스트 작성** (`tests/test_fapi_demo_logger.py`에 추가)

```python
def test_make_fapi_exchange_rewrites_urls_to_demo(monkeypatch):
    monkeypatch.setenv("BINANCE_DEMO_API_KEY", "k")
    monkeypatch.setenv("BINANCE_DEMO_API_SECRET", "s")
    ex = fx.make_fapi_exchange()
    fapi_urls = [u for k, u in ex.urls["api"].items()
                 if isinstance(u, str) and "fapi" in k.lower()]
    assert fapi_urls, "fapi url이 하나는 있어야 함"
    assert all(fx.FAPI_DEMO_HOST in u for u in fapi_urls)  # 전부 demo-fapi


def test_make_fapi_exchange_requires_keys(monkeypatch):
    monkeypatch.delenv("BINANCE_DEMO_API_KEY", raising=False)
    monkeypatch.delenv("BINANCE_DEMO_API_SECRET", raising=False)
    monkeypatch.delenv("BINANCE_TESTNET_API_KEY", raising=False)
    monkeypatch.delenv("BINANCE_TESTNET_API_SECRET", raising=False)
    # .env를 읽지 못하게 존재하지 않는 경로로 load_env 대체
    monkeypatch.setattr(fx, "load_env", lambda *a, **k: None)
    with pytest.raises(RuntimeError):
        fx.make_fapi_exchange()
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_fapi_demo_logger.py::test_make_fapi_exchange_rewrites_urls_to_demo -v`
Expected: FAIL — `AttributeError: module 'fapi_demo_logger' has no attribute 'make_fapi_exchange'`

- [ ] **Step 3: 최소 구현** (`fapi_demo_logger.py`에 추가)

```python
def make_fapi_exchange():
    load_env()
    key = os.environ.get("BINANCE_DEMO_API_KEY") or os.environ.get("BINANCE_TESTNET_API_KEY")
    sec = os.environ.get("BINANCE_DEMO_API_SECRET") or os.environ.get("BINANCE_TESTNET_API_SECRET")
    if not key or not sec:
        raise RuntimeError("API 키 없음 — .env에 BINANCE_DEMO_API_KEY/SECRET (또는 BINANCE_TESTNET_*) 설정 필요")
    ex = ccxt.binance({"apiKey": key, "secret": sec, "enableRateLimit": True,
                       "options": {"defaultType": "future"}})
    for k in list(ex.urls["api"]):
        u = ex.urls["api"][k]
        if isinstance(u, str) and FAPI_MAINNET_HOST in u and FAPI_DEMO_HOST not in u:
            ex.urls["api"][k] = u.replace(FAPI_MAINNET_HOST, FAPI_DEMO_HOST)
    _assert_demo_fapi(ex)
    return ex
```

> 참고: `FAPI_DEMO_HOST not in u` 조건은 `demo-fapi.binance.com`이 `fapi.binance.com`을 부분문자열로 포함하는 문제로 이미 demo인 URL을 이중치환하는 것을 막는다.

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv/bin/python -m pytest tests/test_fapi_demo_logger.py -v`
Expected: PASS (7개)

- [ ] **Step 5: 커밋**

```bash
git add fapi_demo_logger.py tests/test_fapi_demo_logger.py
git commit -m "feat(fapi): make_fapi_exchange URL 치환+키 폴백 (Task2)"
```

---

### Task 3: `run_once` 오케스트레이션 + CSV 기록 + `__main__`

**Files:**
- Modify: `fapi_demo_logger.py`
- Test: `tests/test_fapi_demo_logger.py`

**Interfaces:**
- Consumes: `parse_account`, `count_open_positions`, `parse_premium`, `make_fapi_exchange`, `SYMBOLS`, `STATUS_CSV`, `PREMIUM_CSV`, `STATUS_COLS`, `PREMIUM_COLS`, `LOCK_PATH`
- Produces:
  - `measure_latency_ms(exchange) -> float`
  - `_append_csv(path, rows, cols) -> None` (append-only, 파일 없으면 헤더)
  - `run_once(exchange=None, now=None, status_csv=STATUS_CSV, premium_csv=PREMIUM_CSV) -> dict` → `{"status": {...}, "premium": [...]}` (lock 걸리면 `{"skip":"lock"}`)

- [ ] **Step 1: 실패하는 테스트 작성** (`tests/test_fapi_demo_logger.py`에 추가)

```python
import pandas as pd


class FakeFapi:
    """읽기 전용 fake — 주문 메서드 없음(있으면 안 됨)."""
    def __init__(self, fail=None):
        self.fail = fail or set()          # {"account","positions","premium","time"}
        self.urls = {"api": {"fapiPublic": "https://demo-fapi.binance.com/fapi/v1"}}
    def fapiPublicGetTime(self):
        if "time" in self.fail: raise Exception("time_timeout")
        return {"serverTime": 1782910000000}
    def fapiPrivateV2GetAccount(self):
        if "account" in self.fail: raise Exception("auth_fail")
        return {"totalWalletBalance": "10495.0", "availableBalance": "10490.0",
                "canTrade": True, "updateTime": 1782910000000}
    def fapiPrivateV2GetPositionRisk(self):
        if "positions" in self.fail: raise Exception("pos_fail")
        return [{"symbol": "BTCUSDT", "positionAmt": "0.0"}]
    def fapiPublicGetPremiumIndex(self, params):
        if "premium" in self.fail: raise Exception("prem_fail")
        return {"markPrice": "58456.4", "indexPrice": "58460.0",
                "lastFundingRate": "0.0001", "nextFundingTime": 1782921600000}


def test_run_once_happy_path(tmp_path):
    s = str(tmp_path / "status.csv"); p = str(tmp_path / "premium.csv")
    ex = FakeFapi()
    r = fx.run_once(exchange=ex, now=pd.Timestamp("2026-07-01T10:05:00Z"),
                    status_csv=s, premium_csv=p)
    assert r["status"]["auth_ok"] is True
    assert r["status"]["positions_ok"] is True
    assert r["status"]["premium_ok"] is True
    assert r["status"]["n_open_positions"] == 0
    assert r["status"]["wallet_balance"] == 10495.0
    assert len(r["premium"]) == 2                       # BTC, ETH
    sdf = pd.read_csv(s); pdf = pd.read_csv(p)
    assert len(sdf) == 1 and len(pdf) == 2
    assert list(sdf.columns) == fx.STATUS_COLS
    assert list(pdf.columns) == fx.PREMIUM_COLS


def test_run_once_partial_failure_still_writes_status(tmp_path):
    s = str(tmp_path / "status.csv"); p = str(tmp_path / "premium.csv")
    ex = FakeFapi(fail={"premium"})
    r = fx.run_once(exchange=ex, now=pd.Timestamp("2026-07-01T10:05:00Z"),
                    status_csv=s, premium_csv=p)
    assert r["status"]["auth_ok"] is True               # account는 성공
    assert r["status"]["premium_ok"] is False           # premium만 실패
    assert "premium" in r["status"]["error"]
    assert len(pd.read_csv(s)) == 1                      # status는 기록됨
    import os
    assert not os.path.exists(p)                         # premium 행 0 → 파일 미생성


def test_run_once_auth_failure_recorded(tmp_path):
    s = str(tmp_path / "status.csv"); p = str(tmp_path / "premium.csv")
    ex = FakeFapi(fail={"account"})
    r = fx.run_once(exchange=ex, now=pd.Timestamp("2026-07-01T10:05:00Z"),
                    status_csv=s, premium_csv=p)
    assert r["status"]["auth_ok"] is False
    assert r["status"]["wallet_balance"] is None
    assert "account" in r["status"]["error"]
    assert len(pd.read_csv(s)) == 1


def test_run_once_appends(tmp_path):
    s = str(tmp_path / "status.csv"); p = str(tmp_path / "premium.csv")
    ex = FakeFapi()
    fx.run_once(exchange=ex, now=pd.Timestamp("2026-07-01T10:05:00Z"), status_csv=s, premium_csv=p)
    fx.run_once(exchange=ex, now=pd.Timestamp("2026-07-01T11:05:00Z"), status_csv=s, premium_csv=p)
    assert len(pd.read_csv(s)) == 2                      # append (헤더 중복 없음)
    assert len(pd.read_csv(p)) == 4
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_fapi_demo_logger.py::test_run_once_happy_path -v`
Expected: FAIL — `AttributeError: module 'fapi_demo_logger' has no attribute 'run_once'`

- [ ] **Step 3: 최소 구현** (`fapi_demo_logger.py`에 추가)

```python
def measure_latency_ms(exchange):
    t0 = time.monotonic()
    exchange.fapiPublicGetTime()
    return round((time.monotonic() - t0) * 1000, 1)


def _append_csv(path, rows, cols):
    if not rows:
        return
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    header = not os.path.exists(path)
    df = pd.DataFrame([{c: r.get(c) for c in cols} for r in rows], columns=cols)
    df.to_csv(path, mode="a", header=header, index=False)


def run_once(exchange=None, now=None, status_csv=STATUS_CSV, premium_csv=PREMIUM_CSV):
    os.makedirs("paper", exist_ok=True)
    lock_file = open(LOCK_PATH, "w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("[fapi] 다른 실행 중 — skip"); lock_file.close(); return {"skip": "lock"}
    try:
        exchange = exchange or make_fapi_exchange()
        if now is None:
            now = pd.Timestamp.now(tz="UTC")
        run_at = now.isoformat()
        status = {"run_at": run_at, "latency_ms": None, "auth_ok": False,
                  "wallet_balance": None, "available_balance": None, "can_trade": None,
                  "acct_update_time": None, "positions_ok": False, "n_open_positions": None,
                  "premium_ok": False, "error": ""}
        errors = []

        try:
            status["latency_ms"] = measure_latency_ms(exchange)
        except Exception as e:
            errors.append(f"latency:{type(e).__name__}:{e}")

        try:
            a = parse_account(exchange.fapiPrivateV2GetAccount())
            status.update({"auth_ok": True, "wallet_balance": a["wallet_balance"],
                           "available_balance": a["available_balance"],
                           "can_trade": a["can_trade"], "acct_update_time": a["acct_update_time"]})
        except Exception as e:
            errors.append(f"account:{type(e).__name__}:{e}")

        try:
            status["n_open_positions"] = count_open_positions(exchange.fapiPrivateV2GetPositionRisk())
            status["positions_ok"] = True
        except Exception as e:
            errors.append(f"positions:{type(e).__name__}:{e}")

        premium_rows = []
        for fsym, disp in SYMBOLS:
            try:
                pr = parse_premium(exchange.fapiPublicGetPremiumIndex({"symbol": fsym}), disp)
                premium_rows.append({"run_at": run_at, **pr})
            except Exception as e:
                errors.append(f"premium.{fsym}:{type(e).__name__}:{e}")
        status["premium_ok"] = len(premium_rows) == len(SYMBOLS)

        status["error"] = (" | ".join(errors))[:200]
        _append_csv(status_csv, [status], STATUS_COLS)
        _append_csv(premium_csv, premium_rows, PREMIUM_COLS)
        print(f"[fapi] auth={status['auth_ok']} positions={status['positions_ok']} "
              f"premium={status['premium_ok']} wallet={status['wallet_balance']} "
              f"latency={status['latency_ms']}ms")
        return {"status": status, "premium": premium_rows}
    finally:
        fcntl.flock(lock_file, fcntl.LOCK_UN); lock_file.close()


if __name__ == "__main__":
    run_once()
```

> **구현 주의(DRY/명료성):** 위 `_append_csv`의 리스트 컴프리헨션은 의도적으로 단순화한 형태로 다시 쓸 것 —
> 실제로는 다음처럼 명료하게 구현한다:
> ```python
> def _append_csv(path, rows, cols):
>     if not rows:
>         return
>     os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
>     header = not os.path.exists(path)
>     df = pd.DataFrame([{c: r.get(c) for c in cols} for r in rows], columns=cols)
>     df.to_csv(path, mode="a", header=header, index=False)
> ```

> **구현 주의:** `run_once`는 `now`가 `pd.Timestamp`라고 가정한다(테스트가 tz-aware Timestamp 주입). `run_at = now.isoformat()`.

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv/bin/python -m pytest tests/test_fapi_demo_logger.py -v`
Expected: PASS (11개)

- [ ] **Step 5: 전체 스위트 회귀 확인**

Run: `.venv/bin/python -m pytest -q`
Expected: 기존 통과 개수 + 11 (신규) 전부 PASS, 실패 0

- [ ] **Step 6: 커밋**

```bash
git add fapi_demo_logger.py tests/test_fapi_demo_logger.py
git commit -m "feat(fapi): run_once 오케스트레이션+CSV+__main__ (Task3)"
```

---

## 운영 (구현·검증·머지 후, 사용자 승인하에 — 코드 태스크 아님)

1. **실환경 dry 확인**: `cd <repo> && ./.venv/bin/python fapi_demo_logger.py` 1회 실행 →
   `paper/fapi_demo_status.csv`에 `auth_ok=True, premium_ok=True`, `paper/fapi_demo_premium.csv`에 2행 확인.
   (demo/live 관련 변경은 최소 1회 실환경 검증 — Codex 합의 체크리스트)
2. **cron 등록**: `5 * * * * cd /Users/test/workspace/quant-trading-bot && ./.venv/bin/python fapi_demo_logger.py >> paper/fapi_demo_cron.log 2>&1`
3. **48h 클린 게이트** 관찰 후 캐리 실행기(옵션1)로 진행.

## Self-Review 메모
- Spec 커버리지: 설계의 로깅 항목(status/premium 전 컬럼)·부분실패·mainnet-leak assert·read-only·게이트 모두 Task1–3 + 운영절에 매핑됨.
- 타입 일관성: `parse_account`/`parse_premium`/`count_open_positions` 반환 키가 `STATUS_COLS`/`PREMIUM_COLS` 및 run_once 사용처와 일치.
- 포지션 상세파일 없음(설계대로): `n_open_positions`+`positions_ok`만 status에 기록.
