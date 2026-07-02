# Carry Executor (7b-carry-executor) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 검증된 캐리(숏 퍼프 demo-fapi + 롱 현물 demo-api, 1x 동일 base 수량)를 demo에서 실주문으로 리허설하는 `carry_executor.py` — 부분실패 보상 + phase 상태기계 + 2층 킬스위치.

**Architecture:** `demo_executor.py`(현물 주문·락·CSV·킬스위치 패턴)와 `fapi_demo_logger.py`(demo-fapi 팩토리·mainnet-leak assert)를 재사용하는 단일 신규 모듈. reconcile 방식: cron 매 실행마다 phase를 보고 필요한 것만 한다. 완전한 원자성 대신 **보상 트랜잭션 + 불확실 시 halted_manual**.

**Tech Stack:** Python 3.13, ccxt, pandas, pytest (fake exchange 주입 — 네트워크/실주문 0).

## Global Constraints (설계 doc `docs/design/phase-7b-carry-executor.md`에서 — 전 Task 공통)

- **테스트에서 실제 네트워크·실주문 절대 금지** — fake exchange 2개(spot/fut) 주입.
- **첫 `--live`는 48h 게이트(2026-07-04경) 통과 후 사용자와 함께** — 이 플랜 범위는 구현·테스트까지.
- 기본 dry-run. `--live`=유지·청산·보상만, `--live --confirm-open`=신규 진입 허용.
- 1x 무레버리지, BTC 단독(`symbol` 확장 자리만), always-on, 자동 리밸런싱/보정 금지.
- 상수(설계 확정): `FUT_FRAC=0.30`, `SPOT_FRAC=0.95`, `DD_LIMIT=0.10`, `MARGIN_MIN_RATIO=0.5`.
- 파일: 상태 `paper/carry_state.json`, 감사 `paper/carry_orders.csv`(append-only), 락 `paper/.carry_lock`.
- phase 값: `idle / opening_futures / opening_spot / open / closing_futures / closing_spot / halted_manual`.
- 모든 주문은 **intent 로그(주문 전) → 주문 → 결과 로그** 순서. state 저장은 주문 **전에**.
- 테스트 파일은 `test_demo_executor.py`의 autouse chdir(tmp_path) fixture 패턴 필수(실제 `paper/` 오염 금지).
- 기존 코드 스타일 유지: 짧은 한국어 주석, 타입 어노테이션 없음, 모듈 상수.

---

### Task 1: 순수 함수 + 상태 + 선물 파싱 (`carry_executor.py` 뼈대)

**Files:**
- Create: `carry_executor.py`
- Test: `tests/test_carry_executor.py`

**Interfaces (Produces — 이후 Task가 그대로 사용):**
- `load_state(path=STATE_PATH) -> dict` / `save_state(state, path=STATE_PATH)`
- `log_row(row, path=ORDERS_CSV)` — ORDER_COLS 스키마 append-only
- `compute_equity(spot_usdt, spot_base, price, fut_wallet, fut_upnl) -> float`
- `leg_mismatch(spot_base, perp_amt, price, min_notional) -> bool`
- `margin_breach(available, wallet) -> bool`
- `parse_fut_account(raw) -> dict` (wallet/available/upnl/can_trade)
- `perp_position_amt(raw_positionrisk, symbol="BTCUSDT") -> float` (부호 있는 positionAmt)
- `fetch_fut_filters(fut_ex, symbol="BTCUSDT") -> dict` (demo_executor.fetch_market_filters와 동일 shape)
- `_assert_demo_spot(exchange)` — spot mainnet 유출 차단
- 상수: `SYMBOL="BTC/USDT"`, `FUT_SYMBOL="BTCUSDT"`, `BASE_ASSET="BTC"`, `PHASES`, `ORDER_COLS`

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_carry_executor.py`

```python
import os
import json
import pytest
import carry_executor as ce


@pytest.fixture(autouse=True)
def _isolate_cwd(tmp_path, monkeypatch):
    """실제 paper/ 오염 금지 — test_demo_executor.py와 동일 패턴."""
    monkeypatch.chdir(tmp_path)


def test_default_state_is_idle():
    s = ce.load_state()
    assert s["phase"] == "idle"
    assert s["naked_exposure"] is False
    assert s["high_water"] == 0.0
    assert s["qty"] == 0.0


def test_state_roundtrip(tmp_path):
    s = ce.load_state()
    s["phase"] = "open"; s["qty"] = 0.05
    ce.save_state(s)
    assert ce.load_state()["phase"] == "open"
    assert ce.load_state()["qty"] == 0.05


def test_log_row_appends_with_header_once():
    ce.log_row({"run_at": "t1", "phase": "idle", "action": "none"})
    ce.log_row({"run_at": "t2", "phase": "open", "action": "none"})
    lines = open(ce.ORDERS_CSV).read().strip().split("\n")
    assert lines[0].startswith("run_at,")          # 헤더 1번
    assert len(lines) == 3


def test_compute_equity():
    # 현물 1000 USDT + 0.01 BTC*60000 + 선물지갑 5000 + UPnL -50
    assert ce.compute_equity(1000, 0.01, 60000, 5000, -50) == 1000 + 600 + 5000 - 50


def test_leg_mismatch_dust_tolerance():
    # 차이 0.00001 BTC * 60000 = 0.6 USDT < min_notional 10 → dust, 정합 OK
    assert ce.leg_mismatch(0.05001, -0.05, 60000, 10.0) is False
    # 차이 0.01 BTC * 60000 = 600 >= 10 → 정합 깨짐
    assert ce.leg_mismatch(0.06, -0.05, 60000, 10.0) is True
    # 양다리 0/0 → OK
    assert ce.leg_mismatch(0.0, 0.0, 60000, 10.0) is False


def test_margin_breach():
    assert ce.margin_breach(available=4000, wallet=10000) is True    # 0.4 < 0.5
    assert ce.margin_breach(available=6000, wallet=10000) is False
    assert ce.margin_breach(available=0, wallet=0) is False          # 0 지갑 방어


def test_parse_fut_account():
    raw = {"totalWalletBalance": "10500.5", "availableBalance": "9000.1",
           "totalUnrealizedProfit": "-12.3", "canTrade": True}
    a = ce.parse_fut_account(raw)
    assert a == {"wallet": 10500.5, "available": 9000.1, "upnl": -12.3, "can_trade": True}


def test_perp_position_amt():
    raw = [{"symbol": "ETHUSDT", "positionAmt": "1.0"},
           {"symbol": "BTCUSDT", "positionAmt": "-0.05"}]
    assert ce.perp_position_amt(raw) == -0.05
    assert ce.perp_position_amt([{"symbol": "BTCUSDT", "positionAmt": ""}]) == 0.0  # 빈문자 방어
    assert ce.perp_position_amt([]) == 0.0


def test_assert_demo_spot_raises_on_mainnet():
    class Ex:
        urls = {"api": {"public": "https://api.binance.com/api"}}
    with pytest.raises(RuntimeError):
        ce._assert_demo_spot(Ex())


def test_assert_demo_spot_passes_on_demo():
    class Ex:
        urls = {"api": {"public": "https://demo-api.binance.com/api"}}
    ce._assert_demo_spot(Ex())                        # no raise


def test_fetch_fut_filters():
    class Ex:
        def fapiPublicGetExchangeInfo(self, params):
            assert params == {"symbol": "BTCUSDT"}
            return {"symbols": [{"filters": [
                {"filterType": "LOT_SIZE", "stepSize": "0.001", "minQty": "0.001"},
                {"filterType": "MIN_NOTIONAL", "notional": "100"}]}]}
    m = ce.fetch_fut_filters(Ex())
    assert m["limits"]["cost"]["min"] == 100.0
    assert m["amount_step"] == 0.001
```

- [ ] **Step 2: 실패 확인**

Run: `./.venv/bin/python -m pytest tests/test_carry_executor.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'carry_executor'`

- [ ] **Step 3: 최소 구현** — `carry_executor.py`

```python
import os
import json
import fcntl
import sys
import pandas as pd
from demo_executor import (load_env, make_exchange as make_spot_exchange,
                           fetch_market_filters, round_amount, _balances,
                           update_high_water_and_breach)
from fapi_demo_logger import make_fapi_exchange, _assert_demo_fapi

SPOT_DEMO_HOST = "demo-api.binance.com"
STATE_PATH = "paper/carry_state.json"
ORDERS_CSV = "paper/carry_orders.csv"
LOCK_PATH = "paper/.carry_lock"
SYMBOL = "BTC/USDT"                 # ETH 확장 자리: 심볼 상수만 바꾸면 되는 구조 유지
FUT_SYMBOL = "BTCUSDT"
BASE_ASSET = "BTC"
FUT_FRAC = 0.30                     # 선물 가용잔고 대비 노셔널 상한 (보수적 시작)
SPOT_FRAC = 0.95                    # 현물 USDT 사용 상한 (수수료 버퍼)
DD_LIMIT = 0.10                     # 합산 equity 고점대비 -10% (델타중립이라 타이트)
MARGIN_MIN_RATIO = 0.5              # 선물 available/wallet < 0.5 → 가드

PHASES = ("idle", "opening_futures", "opening_spot", "open",
          "closing_futures", "closing_spot", "halted_manual")

ORDER_COLS = ["run_at", "phase", "action", "qty", "price", "equity",
              "order_id", "dry_run", "note"]


def load_state(path=STATE_PATH):
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {"phase": "idle", "reason": "", "naked_exposure": False,
            "high_water": 0.0, "qty": 0.0}


def save_state(state, path=STATE_PATH):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        json.dump(state, f, indent=2)


def log_row(row, path=ORDERS_CSV):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    header = not os.path.exists(path)
    pd.DataFrame([{c: row.get(c) for c in ORDER_COLS}], columns=ORDER_COLS).to_csv(
        path, mode="a", header=header, index=False)


def compute_equity(spot_usdt, spot_base, price, fut_wallet, fut_upnl):
    return spot_usdt + spot_base * price + fut_wallet + fut_upnl


def leg_mismatch(spot_base, perp_amt, price, min_notional):
    return abs(spot_base - abs(perp_amt)) * price >= min_notional


def margin_breach(available, wallet):
    return wallet > 0 and (available / wallet) < MARGIN_MIN_RATIO


def parse_fut_account(raw):
    return {"wallet": float(raw["totalWalletBalance"]),
            "available": float(raw["availableBalance"]),
            "upnl": float(raw["totalUnrealizedProfit"]),
            "can_trade": bool(raw["canTrade"])}


def perp_position_amt(raw, symbol=FUT_SYMBOL):
    for p in raw:
        if p.get("symbol") == symbol:
            return float(p.get("positionAmt") or 0)
    return 0.0


def _assert_demo_spot(exchange):
    for k, u in exchange.urls["api"].items():
        if isinstance(u, str) and "api.binance.com" in u and SPOT_DEMO_HOST not in u:
            raise RuntimeError(f"mainnet leak guard: {k}={u} (demo-api 아님)")


def fetch_fut_filters(fut_ex, symbol=FUT_SYMBOL):
    info = fut_ex.fapiPublicGetExchangeInfo({"symbol": symbol})
    fs = {f["filterType"]: f for f in info["symbols"][0]["filters"]}
    notional = fs.get("MIN_NOTIONAL") or fs.get("NOTIONAL") or {}
    lot = fs.get("LOT_SIZE", {})
    return {"limits": {"cost": {"min": float(notional.get("notional") or 100.0)},
                       "amount": {"min": float(lot.get("minQty") or 1e-3)}},
            "amount_step": float(lot.get("stepSize") or 1e-3)}
```

- [ ] **Step 4: 통과 확인**

Run: `./.venv/bin/python -m pytest tests/test_carry_executor.py -q`
Expected: PASS (11 passed)

- [ ] **Step 5: Commit**

```bash
git add carry_executor.py tests/test_carry_executor.py
git commit -m "feat(carry): 상태·순수함수·선물 파싱 뼈대 (Task1)"
```

---

### Task 2: fake exchange 2개 + 진입 시퀀스 `open_carry` (보상 트랜잭션 포함)

**Files:**
- Modify: `carry_executor.py` (open_carry 추가)
- Modify: `tests/test_carry_executor.py` (fakes + 진입 테스트 추가)

**Interfaces:**
- Consumes: Task 1 전부.
- Produces: `open_carry(spot_ex, fut_ex, state, snap, spot_mkt, fut_mkt, dry_run) -> dict`
  - `snap` = `{"spot_usdt", "spot_base", "price", "fut": {wallet, available, upnl, can_trade}, "perp_amt"}`
  - 반환 `{"action": "opened"|"would_open"|"skip"|"aborted_futures"|"compensated"|"error", "note": str}`
  - fakes(`FakeSpot`, `FakeFut`)는 Task 3·4·5 테스트가 재사용 — 시그니처 변경 금지.

**진입 규칙(설계 doc):** precheck(캔트레이드·기존 포지션 0) → notional=min(fut.available×0.30, spot_usdt×0.95) → qty를 fut step→spot step 순서로 내림 → **선물 숏 먼저**(실패=깨끗한 중단, idle 복귀) → 실제 체결량(positionRisk) 확인 → 그 수량으로 현물 매수 → 실패 시 선물 reduce-only 보상 → 보상도 실패면 `halted_manual + naked_exposure`.

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_carry_executor.py`에 추가

```python
PRICE = 60000.0

SPOT_INFO = {"symbols": [{"filters": [
    {"filterType": "LOT_SIZE", "stepSize": "0.00001", "minQty": "0.00001"},
    {"filterType": "NOTIONAL", "minNotional": "10"}]}]}
FUT_INFO = {"symbols": [{"filters": [
    {"filterType": "LOT_SIZE", "stepSize": "0.001", "minQty": "0.001"},
    {"filterType": "MIN_NOTIONAL", "notional": "100"}]}]}


class FakeSpot:
    def __init__(self, usdt=20000.0, base=0.0, fail_buy=False, fail_sell=False):
        self.urls = {"api": {"public": "https://demo-api.binance.com/api"}}
        self.usdt, self.base = usdt, base
        self.fail_buy, self.fail_sell = fail_buy, fail_sell
        self.orders = []

    def private_get_account(self):
        return {"balances": [{"asset": "USDT", "free": str(self.usdt)},
                             {"asset": "BTC", "free": str(self.base)}]}

    def public_get_exchangeinfo(self, params):
        return SPOT_INFO

    def create_market_buy_order(self, symbol, qty):
        if self.fail_buy:
            raise RuntimeError("spot buy failed")
        self.base += qty; self.usdt -= qty * PRICE
        self.orders.append(("buy", qty))
        return {"id": f"s{len(self.orders)}"}

    def create_market_sell_order(self, symbol, qty):
        if self.fail_sell:
            raise RuntimeError("spot sell failed")
        self.base -= qty; self.usdt += qty * PRICE
        self.orders.append(("sell", qty))
        return {"id": f"s{len(self.orders)}"}


class FakeFut:
    def __init__(self, wallet=10000.0, available=10000.0, upnl=0.0, perp_amt=0.0,
                 fail_sell=False, fail_reduce=False):
        self.urls = {"api": {"fapiPublic": "https://demo-fapi.binance.com/fapi",
                             "fapiPrivate": "https://demo-fapi.binance.com/fapi"}}
        self.wallet, self.available, self.upnl = wallet, available, upnl
        self.perp_amt = perp_amt
        self.fail_sell, self.fail_reduce = fail_sell, fail_reduce
        self.orders = []

    def fapiPrivateV2GetAccount(self):
        return {"totalWalletBalance": str(self.wallet), "availableBalance": str(self.available),
                "totalUnrealizedProfit": str(self.upnl), "canTrade": True}

    def fapiPrivateV2GetPositionRisk(self, params=None):
        return [{"symbol": "BTCUSDT", "positionAmt": str(self.perp_amt)}]

    def fapiPublicGetPremiumIndex(self, params):
        return {"markPrice": str(PRICE)}

    def fapiPublicGetExchangeInfo(self, params):
        return FUT_INFO

    def create_market_sell_order(self, symbol, qty):
        if self.fail_sell:
            raise RuntimeError("fut sell failed")
        self.perp_amt -= qty
        self.orders.append(("sell", qty, {}))
        return {"id": f"f{len(self.orders)}"}

    def create_market_buy_order(self, symbol, qty, params=None):
        if self.fail_reduce:
            raise RuntimeError("fut reduce failed")
        self.perp_amt += qty
        self.orders.append(("buy", qty, params or {}))
        return {"id": f"f{len(self.orders)}"}


def _snap(spot, fut):
    return {"spot_usdt": spot.usdt, "spot_base": spot.base, "price": PRICE,
            "fut": ce.parse_fut_account(fut.fapiPrivateV2GetAccount()),
            "perp_amt": fut.perp_amt}


def _mkts():
    return ({"limits": {"cost": {"min": 10.0}}, "amount_step": 0.00001},
            {"limits": {"cost": {"min": 100.0}}, "amount_step": 0.001})


def test_open_happy_path():
    spot, fut = FakeSpot(), FakeFut()
    state = ce.load_state()
    spot_mkt, fut_mkt = _mkts()
    res = ce.open_carry(spot, fut, state, _snap(spot, fut), spot_mkt, fut_mkt, dry_run=False)
    assert res["action"] == "opened"
    # notional = min(10000*0.30, 20000*0.95) = 3000 → qty = 0.05
    assert fut.orders == [("sell", 0.05, {})]
    assert spot.orders == [("buy", 0.05)]
    assert state["phase"] == "open"
    assert state["qty"] == 0.05
    assert os.path.exists(ce.ORDERS_CSV)


def test_open_dry_run_no_orders():
    spot, fut = FakeSpot(), FakeFut()
    state = ce.load_state()
    spot_mkt, fut_mkt = _mkts()
    res = ce.open_carry(spot, fut, state, _snap(spot, fut), spot_mkt, fut_mkt, dry_run=True)
    assert res["action"] == "would_open"
    assert fut.orders == [] and spot.orders == []
    assert state["phase"] == "idle"


def test_open_skips_if_position_exists():
    spot, fut = FakeSpot(), FakeFut(perp_amt=-0.05)
    state = ce.load_state()
    spot_mkt, fut_mkt = _mkts()
    res = ce.open_carry(spot, fut, state, _snap(spot, fut), spot_mkt, fut_mkt, dry_run=False)
    assert res["action"] == "skip"
    assert fut.orders == [] and spot.orders == []


def test_open_futures_fail_clean_abort():
    spot, fut = FakeSpot(), FakeFut(fail_sell=True)
    state = ce.load_state()
    spot_mkt, fut_mkt = _mkts()
    res = ce.open_carry(spot, fut, state, _snap(spot, fut), spot_mkt, fut_mkt, dry_run=False)
    assert res["action"] == "aborted_futures"
    assert spot.orders == []                          # 현물은 손도 안 댐
    assert state["phase"] == "idle"                   # 깨끗한 중단
    assert state["naked_exposure"] is False


def test_open_spot_fail_compensates_with_reduce_only():
    spot, fut = FakeSpot(fail_buy=True), FakeFut()
    state = ce.load_state()
    spot_mkt, fut_mkt = _mkts()
    res = ce.open_carry(spot, fut, state, _snap(spot, fut), spot_mkt, fut_mkt, dry_run=False)
    assert res["action"] == "compensated"
    # 숏 열림 → 현물 실패 → reduce-only 매수로 숏 닫힘
    assert fut.orders[0][0] == "sell"
    assert fut.orders[1][0] == "buy" and fut.orders[1][2].get("reduceOnly") is True
    assert state["phase"] == "halted_manual"          # 보상 성공해도 halt (자동 재시도 금지)
    assert state["naked_exposure"] is False


def test_open_compensation_fail_naked_halt():
    spot, fut = FakeSpot(fail_buy=True), FakeFut(fail_reduce=True)
    state = ce.load_state()
    spot_mkt, fut_mkt = _mkts()
    res = ce.open_carry(spot, fut, state, _snap(spot, fut), spot_mkt, fut_mkt, dry_run=False)
    assert res["action"] == "error"
    assert state["phase"] == "halted_manual"
    assert state["naked_exposure"] is True            # 숏 단독 노출 — 수동 개입 필요


def test_open_below_min_notional_skips():
    spot, fut = FakeSpot(usdt=50.0), FakeFut(available=200.0)
    state = ce.load_state()
    spot_mkt, fut_mkt = _mkts()
    # notional = min(200*0.3, 50*0.95)=47.5 < fut min 100 → skip
    res = ce.open_carry(spot, fut, state, _snap(spot, fut), spot_mkt, fut_mkt, dry_run=False)
    assert res["action"] == "skip"
    assert fut.orders == [] and spot.orders == []
```

- [ ] **Step 2: 실패 확인**

Run: `./.venv/bin/python -m pytest tests/test_carry_executor.py -q`
Expected: FAIL — `AttributeError: module 'carry_executor' has no attribute 'open_carry'` (Task 1 테스트는 PASS 유지)

- [ ] **Step 3: 구현** — `carry_executor.py`에 추가

```python
def _now_iso():
    return pd.Timestamp.now(tz="UTC").isoformat()


def open_carry(spot_ex, fut_ex, state, snap, spot_mkt, fut_mkt, dry_run):
    """진입: 선물 숏 먼저(불안정한 다리) → 체결량 확인 → 동수량 현물 매수.
    실패 처리: 선물 실패=깨끗한 중단 / 현물 실패=선물 reduce-only 보상 / 보상 실패=naked halt."""
    price = snap["price"]
    equity = compute_equity(snap["spot_usdt"], snap["spot_base"], price,
                            snap["fut"]["wallet"], snap["fut"]["upnl"])
    base = {"run_at": _now_iso(), "phase": state["phase"], "price": price,
            "equity": equity, "dry_run": dry_run}
    spot_min = spot_mkt["limits"]["cost"]["min"] or 10.0

    # precheck: 기존 포지션 없어야 진입 (perp 0 + 현물 dust만)
    if snap["perp_amt"] != 0 or snap["spot_base"] * price >= spot_min:
        log_row({**base, "action": "skip", "qty": 0, "order_id": "", "note": "position_exists"})
        return {"action": "skip", "note": "position_exists"}
    if not snap["fut"]["can_trade"]:
        log_row({**base, "action": "skip", "qty": 0, "order_id": "", "note": "cannot_trade"})
        return {"action": "skip", "note": "cannot_trade"}

    notional = min(snap["fut"]["available"] * FUT_FRAC, snap["spot_usdt"] * SPOT_FRAC)
    qty = round_amount(round_amount(notional / price, fut_mkt["amount_step"]),
                       spot_mkt["amount_step"])
    if qty * price < max(spot_min, fut_mkt["limits"]["cost"]["min"] or 100.0):
        log_row({**base, "action": "skip", "qty": qty, "order_id": "", "note": "below_min_notional"})
        return {"action": "skip", "note": "below_min_notional"}

    if dry_run:
        log_row({**base, "action": "would_open", "qty": qty, "order_id": "", "note": "dry_run"})
        return {"action": "would_open", "qty": qty}

    # 다리 1: 선물 숏 (intent 저장 → 주문)
    state["phase"] = "opening_futures"; state["qty"] = qty; save_state(state)
    log_row({**base, "phase": "opening_futures", "action": "fut_sell_intent", "qty": qty,
             "order_id": "", "note": ""})
    try:
        o = fut_ex.create_market_sell_order(SYMBOL, qty)
    except Exception as e:
        state["phase"] = "idle"; state["qty"] = 0.0; save_state(state)   # 아무 일도 안 일어남
        log_row({**base, "phase": "idle", "action": "aborted_futures", "qty": qty,
                 "order_id": "", "note": f"{type(e).__name__}"})
        return {"action": "aborted_futures"}
    log_row({**base, "phase": "opening_futures", "action": "fut_sell", "qty": qty,
             "order_id": o.get("id"), "note": ""})

    # 실제 체결량 확인 → 그 수량으로 현물 매수
    filled = abs(perp_position_amt(fut_ex.fapiPrivateV2GetPositionRisk({"symbol": FUT_SYMBOL})))
    spot_qty = round_amount(filled, spot_mkt["amount_step"])
    state["phase"] = "opening_spot"; state["qty"] = filled; save_state(state)
    log_row({**base, "phase": "opening_spot", "action": "spot_buy_intent", "qty": spot_qty,
             "order_id": "", "note": ""})
    try:
        o2 = spot_ex.create_market_buy_order(SYMBOL, spot_qty)
    except Exception as e:
        # 다리 2 실패 → 보상: 선물 reduce-only 청산. 성공해도 halt (자동 재시도 금지 — Codex)
        log_row({**base, "phase": "opening_spot", "action": "compensate_intent", "qty": filled,
                 "order_id": "", "note": f"spot_buy_failed:{type(e).__name__}"})
        try:
            oc = fut_ex.create_market_buy_order(SYMBOL, filled, {"reduceOnly": True})
            state["phase"] = "halted_manual"; state["reason"] = "spot_failed_compensated"
            state["qty"] = 0.0; save_state(state)
            log_row({**base, "phase": "halted_manual", "action": "compensated", "qty": filled,
                     "order_id": oc.get("id"), "note": ""})
            return {"action": "compensated"}
        except Exception as e2:
            state["phase"] = "halted_manual"; state["reason"] = "spot_failed_compensation_failed"
            state["naked_exposure"] = True; save_state(state)
            log_row({**base, "phase": "halted_manual", "action": "error", "qty": filled,
                     "order_id": "", "note": f"naked_short:{type(e2).__name__}"})
            return {"action": "error", "note": "naked_exposure"}

    state["phase"] = "open"; save_state(state)
    log_row({**base, "phase": "open", "action": "opened", "qty": spot_qty,
             "order_id": o2.get("id"), "note": ""})
    return {"action": "opened", "qty": spot_qty}
```

- [ ] **Step 4: 통과 확인**

Run: `./.venv/bin/python -m pytest tests/test_carry_executor.py -q`
Expected: PASS (18 passed)

- [ ] **Step 5: Commit**

```bash
git add carry_executor.py tests/test_carry_executor.py
git commit -m "feat(carry): open_carry 진입 시퀀스 — 선물 먼저+보상 트랜잭션+naked halt (Task2)"
```

---

### Task 3: 청산 시퀀스 `close_carry` (상태별 위험 다리 먼저)

**Files:**
- Modify: `carry_executor.py` (close_carry 추가)
- Modify: `tests/test_carry_executor.py` (청산 테스트 추가)

**Interfaces:**
- Consumes: Task 1·2 전부 (FakeSpot/FakeFut/_snap/_mkts 재사용).
- Produces: `close_carry(spot_ex, fut_ex, state, snap, spot_mkt, fut_mkt, dry_run, reason="") -> dict`
  - 반환 `{"action": "closed"|"would_close"|"none"|"error", "note": str}`

**청산 규칙(설계 doc·Codex):** 선물 숏 존재 → reduce-only 청산 **먼저** → 현물 매도. 현물만 존재 → 바로 현물 매도. 선물만 존재(naked) → reduce-only가 최우선. 선물 청산 실패 → `halted_manual`(양다리 유지 상태). 현물 매도 실패 → 잔여 롱은 양성이므로 `halted_manual`만(재시도 금지). 완료 → `idle`, qty=0.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
def test_close_full_position_futures_first():
    spot, fut = FakeSpot(usdt=17000.0, base=0.05), FakeFut(perp_amt=-0.05)
    state = ce.load_state(); state["phase"] = "open"; state["qty"] = 0.05
    spot_mkt, fut_mkt = _mkts()
    res = ce.close_carry(spot, fut, state, _snap(spot, fut), spot_mkt, fut_mkt,
                         dry_run=False, reason="test")
    assert res["action"] == "closed"
    assert fut.orders[0][0] == "buy" and fut.orders[0][2].get("reduceOnly") is True
    assert spot.orders == [("sell", 0.05)]            # 선물 먼저, 현물 나중
    assert state["phase"] == "idle" and state["qty"] == 0.0


def test_close_spot_only_sells_immediately():
    spot, fut = FakeSpot(usdt=17000.0, base=0.05), FakeFut(perp_amt=0.0)
    state = ce.load_state(); state["phase"] = "open"; state["qty"] = 0.05
    spot_mkt, fut_mkt = _mkts()
    res = ce.close_carry(spot, fut, state, _snap(spot, fut), spot_mkt, fut_mkt,
                         dry_run=False)
    assert res["action"] == "closed"
    assert fut.orders == []                           # 선물 없음 → 건너뜀
    assert spot.orders == [("sell", 0.05)]


def test_close_futures_fail_halts_before_spot():
    spot, fut = FakeSpot(usdt=17000.0, base=0.05), FakeFut(perp_amt=-0.05, fail_reduce=True)
    state = ce.load_state(); state["phase"] = "open"
    spot_mkt, fut_mkt = _mkts()
    res = ce.close_carry(spot, fut, state, _snap(spot, fut), spot_mkt, fut_mkt,
                         dry_run=False)
    assert res["action"] == "error"
    assert spot.orders == []                          # 현물은 손대지 않음 (헷지 유지)
    assert state["phase"] == "halted_manual"


def test_close_spot_fail_halts_benign():
    spot, fut = FakeSpot(usdt=17000.0, base=0.05, fail_sell=True), FakeFut(perp_amt=-0.05)
    state = ce.load_state(); state["phase"] = "open"
    spot_mkt, fut_mkt = _mkts()
    res = ce.close_carry(spot, fut, state, _snap(spot, fut), spot_mkt, fut_mkt,
                         dry_run=False)
    assert res["action"] == "error"
    assert fut.orders[0][2].get("reduceOnly") is True # 선물은 이미 닫힘
    assert state["phase"] == "halted_manual"
    assert state["naked_exposure"] is False           # 잔여 현물 롱 = 양성 노출


def test_close_dry_run_no_orders():
    spot, fut = FakeSpot(base=0.05), FakeFut(perp_amt=-0.05)
    state = ce.load_state(); state["phase"] = "open"
    spot_mkt, fut_mkt = _mkts()
    res = ce.close_carry(spot, fut, state, _snap(spot, fut), spot_mkt, fut_mkt,
                         dry_run=True)
    assert res["action"] == "would_close"
    assert fut.orders == [] and spot.orders == []


def test_close_nothing_to_close():
    spot, fut = FakeSpot(), FakeFut()
    state = ce.load_state(); state["phase"] = "open"
    spot_mkt, fut_mkt = _mkts()
    res = ce.close_carry(spot, fut, state, _snap(spot, fut), spot_mkt, fut_mkt,
                         dry_run=False)
    assert res["action"] == "closed"                  # 둘 다 없음 → 즉시 idle 복귀
    assert state["phase"] == "idle"
```

- [ ] **Step 2: 실패 확인**

Run: `./.venv/bin/python -m pytest tests/test_carry_executor.py -q`
Expected: FAIL — `AttributeError: ... no attribute 'close_carry'`

- [ ] **Step 3: 구현** — `carry_executor.py`에 추가

```python
def close_carry(spot_ex, fut_ex, state, snap, spot_mkt, fut_mkt, dry_run, reason=""):
    """청산: 위험 다리(선물 숏) 먼저 reduce-only → 현물 매도. 실패 시 halt, 재시도 금지."""
    price = snap["price"]
    equity = compute_equity(snap["spot_usdt"], snap["spot_base"], price,
                            snap["fut"]["wallet"], snap["fut"]["upnl"])
    base = {"run_at": _now_iso(), "phase": state["phase"], "price": price,
            "equity": equity, "dry_run": dry_run}
    spot_min = spot_mkt["limits"]["cost"]["min"] or 10.0
    short_qty = abs(snap["perp_amt"])
    spot_holding = snap["spot_base"] * price >= spot_min

    if dry_run:
        if short_qty or spot_holding:
            log_row({**base, "action": "would_close", "qty": short_qty or snap["spot_base"],
                     "order_id": "", "note": reason or "dry_run"})
            return {"action": "would_close"}
        return {"action": "none"}

    # 다리 1: 선물 숏 존재 → reduce-only 청산 먼저 (위험 다리 제거)
    if short_qty:
        state["phase"] = "closing_futures"; save_state(state)
        log_row({**base, "phase": "closing_futures", "action": "fut_close_intent",
                 "qty": short_qty, "order_id": "", "note": reason})
        try:
            o = fut_ex.create_market_buy_order(SYMBOL, short_qty, {"reduceOnly": True})
        except Exception as e:
            state["phase"] = "halted_manual"; state["reason"] = "close_futures_failed"
            save_state(state)
            log_row({**base, "phase": "halted_manual", "action": "error", "qty": short_qty,
                     "order_id": "", "note": f"fut_close_failed:{type(e).__name__}"})
            return {"action": "error", "note": "close_futures_failed"}
        log_row({**base, "phase": "closing_futures", "action": "fut_close",
                 "qty": short_qty, "order_id": o.get("id"), "note": reason})

    # 다리 2: 현물 매도 (실패해도 잔여 롱은 양성 — halt만)
    if spot_holding:
        qty = round_amount(snap["spot_base"], spot_mkt["amount_step"])
        state["phase"] = "closing_spot"; save_state(state)
        log_row({**base, "phase": "closing_spot", "action": "spot_sell_intent",
                 "qty": qty, "order_id": "", "note": reason})
        try:
            o2 = spot_ex.create_market_sell_order(SYMBOL, qty)
        except Exception as e:
            state["phase"] = "halted_manual"; state["reason"] = "close_spot_failed"
            save_state(state)
            log_row({**base, "phase": "halted_manual", "action": "error", "qty": qty,
                     "order_id": "", "note": f"spot_sell_failed:{type(e).__name__}"})
            return {"action": "error", "note": "close_spot_failed"}
        log_row({**base, "phase": "closing_spot", "action": "spot_sell",
                 "qty": qty, "order_id": o2.get("id"), "note": reason})

    state["phase"] = "idle"; state["qty"] = 0.0; save_state(state)
    log_row({**base, "phase": "idle", "action": "closed", "qty": 0, "order_id": "",
             "note": reason})
    return {"action": "closed"}
```

- [ ] **Step 4: 통과 확인**

Run: `./.venv/bin/python -m pytest tests/test_carry_executor.py -q`
Expected: PASS (24 passed)

- [ ] **Step 5: Commit**

```bash
git add carry_executor.py tests/test_carry_executor.py
git commit -m "feat(carry): close_carry 청산 — 상태별 위험다리 우선+실패시 halt (Task3)"
```

---

### Task 4: `run_once` 오케스트레이션 (락·phase 분기·킬스위치·크래시 재개·`__main__`)

**Files:**
- Modify: `carry_executor.py` (run_once + `__main__` 추가)
- Modify: `tests/test_carry_executor.py` (오케스트레이션 테스트 추가)

**Interfaces:**
- Consumes: Task 1~3 전부.
- Produces: `run_once(live=False, confirm_open=False, spot_ex=None, fut_ex=None) -> dict`
  - 주입 경로에서도 `_assert_demo_spot`/`_assert_demo_fapi` 실행 (방어심층 — fapi_demo_logger 패턴).

**분기 규칙(설계 doc):**
- `halted_manual` → 아무 주문 없이 로그+반환 (수동 리셋 = 사용자가 state 파일 직접 수정).
- 크래시 재개: `opening_futures`에서 발견 + 숏 없음 → idle 복귀(깨끗). 숏 있음 → `opening_spot`으로 이어서 현물 매수(live일 때만, 헷지 완성 = 노출 축소라 자동 허용). dry면 로그만.
- `closing_*`에서 발견 → close_carry 이어서.
- `open`(또는 다리 존재): ① 정합 체크 → 깨지면 **주문 없이** `halted_manual` ② equity DD −10% ③ margin 가드 → ②③은 reason 저장 후 close_carry 1회 → `halted_manual`.
- `idle`: `live and confirm_open`일 때만 open_carry. dry-run이면 open_carry가 would_open 로그.
- state 저장(high_water 갱신 포함)은 live일 때만 (demo_executor 패턴).

- [ ] **Step 1: 실패하는 테스트 작성**

```python
def _run(spot, fut, live=False, confirm_open=False):
    return ce.run_once(live=live, confirm_open=confirm_open, spot_ex=spot, fut_ex=fut)


def test_run_once_idle_without_confirm_does_nothing():
    spot, fut = FakeSpot(), FakeFut()
    res = _run(spot, fut, live=True, confirm_open=False)
    assert res["action"] == "none"
    assert fut.orders == [] and spot.orders == []


def test_run_once_idle_confirm_open_opens():
    spot, fut = FakeSpot(), FakeFut()
    res = _run(spot, fut, live=True, confirm_open=True)
    assert res["action"] == "opened"
    assert ce.load_state()["phase"] == "open"


def test_run_once_dry_run_never_orders():
    spot, fut = FakeSpot(), FakeFut()
    res = _run(spot, fut, live=False, confirm_open=True)
    assert res["action"] == "would_open"
    assert fut.orders == [] and spot.orders == []
    assert ce.load_state()["phase"] == "idle"


def test_run_once_halted_blocks_everything():
    s = ce.load_state(); s["phase"] = "halted_manual"; s["reason"] = "x"; ce.save_state(s)
    spot, fut = FakeSpot(), FakeFut(perp_amt=-0.05)
    res = _run(spot, fut, live=True, confirm_open=True)
    assert res["action"] == "halted"
    assert fut.orders == [] and spot.orders == []


def test_run_once_open_healthy_noop():
    s = ce.load_state(); s["phase"] = "open"; s["qty"] = 0.05; ce.save_state(s)
    spot, fut = FakeSpot(usdt=17000.0, base=0.05), FakeFut(perp_amt=-0.05)
    res = _run(spot, fut, live=True)
    assert res["action"] == "none"
    assert fut.orders == [] and spot.orders == []
    assert ce.load_state()["phase"] == "open"


def test_run_once_leg_mismatch_halts_without_orders():
    s = ce.load_state(); s["phase"] = "open"; s["qty"] = 0.05; ce.save_state(s)
    spot, fut = FakeSpot(usdt=17000.0, base=0.02), FakeFut(perp_amt=-0.05)   # 0.03 어긋남
    res = _run(spot, fut, live=True)
    assert res["action"] == "halted"
    assert fut.orders == [] and spot.orders == []     # 자동 보정 금지 (Codex)
    st = ce.load_state()
    assert st["phase"] == "halted_manual" and st["reason"] == "leg_mismatch"


def test_run_once_dd_breach_closes_and_halts():
    s = ce.load_state(); s["phase"] = "open"; s["qty"] = 0.05
    s["high_water"] = 30000.0; ce.save_state(s)       # equity ≈ 17000+3000+10000=30000 근처
    spot, fut = FakeSpot(usdt=13000.0, base=0.05), FakeFut(wallet=10000.0, upnl=-500.0,
                                                            perp_amt=-0.05)
    # equity = 13000 + 3000 + 10000 - 500 = 25500 → 30000 대비 -15% < -10% → 발동
    res = _run(spot, fut, live=True)
    assert res["action"] == "kill_switch"
    assert fut.orders[0][2].get("reduceOnly") is True # 청산 실행됨
    assert spot.orders[0][0] == "sell"
    st = ce.load_state()
    assert st["phase"] == "halted_manual" and "drawdown" in st["reason"]


def test_run_once_margin_guard_closes_and_halts():
    s = ce.load_state(); s["phase"] = "open"; s["qty"] = 0.05; ce.save_state(s)
    spot, fut = FakeSpot(usdt=17000.0, base=0.05), FakeFut(wallet=10000.0, available=4000.0,
                                                            perp_amt=-0.05)   # 0.4 < 0.5
    res = _run(spot, fut, live=True)
    assert res["action"] == "kill_switch"
    st = ce.load_state()
    assert st["phase"] == "halted_manual" and st["reason"] == "margin_guard"


def test_run_once_resume_opening_futures_no_short_resets_idle():
    s = ce.load_state(); s["phase"] = "opening_futures"; s["qty"] = 0.05; ce.save_state(s)
    spot, fut = FakeSpot(), FakeFut(perp_amt=0.0)     # 숏 안 열렸음 = 아무 일 없음
    res = _run(spot, fut, live=True)
    assert res["action"] == "reset_idle"
    assert ce.load_state()["phase"] == "idle"
    assert fut.orders == [] and spot.orders == []


def test_run_once_resume_opening_spot_completes_hedge():
    s = ce.load_state(); s["phase"] = "opening_spot"; s["qty"] = 0.05; ce.save_state(s)
    spot, fut = FakeSpot(), FakeFut(perp_amt=-0.05)   # 숏만 있고 현물 없음
    res = _run(spot, fut, live=True)
    assert res["action"] == "resumed_open"
    assert spot.orders == [("buy", 0.05)]             # 헷지 완성 (노출 축소라 자동 허용)
    assert ce.load_state()["phase"] == "open"


def test_run_once_resume_closing_continues_close():
    s = ce.load_state(); s["phase"] = "closing_spot"; s["qty"] = 0.05; ce.save_state(s)
    spot, fut = FakeSpot(usdt=17000.0, base=0.05), FakeFut(perp_amt=0.0)  # 선물은 이미 닫힘
    res = _run(spot, fut, live=True)
    assert res["action"] == "closed"
    assert spot.orders == [("sell", 0.05)]
    assert ce.load_state()["phase"] == "idle"


def test_run_once_rejects_mainnet_injected_exchange():
    spot = FakeSpot()
    spot.urls = {"api": {"public": "https://api.binance.com/api"}}   # mainnet 주입 시도
    with pytest.raises(RuntimeError):
        ce.run_once(live=False, spot_ex=spot, fut_ex=FakeFut())
```

- [ ] **Step 2: 실패 확인**

Run: `./.venv/bin/python -m pytest tests/test_carry_executor.py -q`
Expected: FAIL — `AttributeError: ... no attribute 'run_once'`

- [ ] **Step 3: 구현** — `carry_executor.py`에 추가

```python
def _snapshot(spot_ex, fut_ex):
    usdt, base = _balances(spot_ex)
    fut = parse_fut_account(fut_ex.fapiPrivateV2GetAccount())
    perp = perp_position_amt(fut_ex.fapiPrivateV2GetPositionRisk({"symbol": FUT_SYMBOL}))
    price = float(fut_ex.fapiPublicGetPremiumIndex({"symbol": FUT_SYMBOL})["markPrice"])
    return {"spot_usdt": usdt, "spot_base": base, "price": price, "fut": fut,
            "perp_amt": perp}


def run_once(live=False, confirm_open=False, spot_ex=None, fut_ex=None):
    os.makedirs("paper", exist_ok=True)
    lock_file = open(LOCK_PATH, "w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("[carry] 다른 실행 중 — skip"); lock_file.close(); return {"skip": "lock"}
    try:
        spot_ex = spot_ex or make_spot_exchange()
        fut_ex = fut_ex or make_fapi_exchange()
        _assert_demo_spot(spot_ex); _assert_demo_fapi(fut_ex)   # 주입 경로도 차단(방어심층)
        spot_mkt = fetch_market_filters(spot_ex)
        fut_mkt = fetch_fut_filters(fut_ex)
        snap = _snapshot(spot_ex, fut_ex)
        state = load_state()
        dry_run = not live
        price = snap["price"]
        equity = compute_equity(snap["spot_usdt"], snap["spot_base"], price,
                                snap["fut"]["wallet"], snap["fut"]["upnl"])
        base = {"run_at": _now_iso(), "phase": state["phase"], "price": price,
                "equity": equity, "dry_run": dry_run, "qty": state.get("qty", 0.0),
                "order_id": ""}

        # 0) halted → 수동 리셋 전 아무것도 안 함
        if state["phase"] == "halted_manual":
            log_row({**base, "action": "halted", "note": state.get("reason", "")})
            print(f"[carry] HALTED({state.get('reason')}) — 수동 리셋 필요")
            return {"action": "halted", "reason": state.get("reason")}

        # 1) 크래시 재개 (직전 실행이 중간 phase에서 죽음)
        if state["phase"] == "opening_futures":
            if abs(snap["perp_amt"]) == 0:            # 숏 안 열림 → 깨끗한 초기화
                state["phase"] = "idle"; state["qty"] = 0.0
                if live: save_state(state)
                log_row({**base, "phase": "idle", "action": "reset_idle", "note": "resume"})
                return {"action": "reset_idle"}
            state["phase"] = "opening_spot"           # 숏 확인됨 → 현물 다리 이어서

        if state["phase"] == "opening_spot":
            filled = abs(snap["perp_amt"])
            if filled == 0:                           # 숏도 사라짐 → 정합 체크로 진행
                state["phase"] = "open"
            elif dry_run:
                log_row({**base, "action": "resume_pending", "note": "opening_spot(dry)"})
                return {"action": "resume_pending"}
            else:
                qty = round_amount(filled, spot_mkt["amount_step"])
                log_row({**base, "phase": "opening_spot", "action": "spot_buy_intent",
                         "qty": qty, "note": "resume"})
                try:
                    o = spot_ex.create_market_buy_order(SYMBOL, qty)
                except Exception as e:
                    state["phase"] = "halted_manual"; state["reason"] = "resume_spot_failed"
                    save_state(state)
                    log_row({**base, "phase": "halted_manual", "action": "error",
                             "qty": qty, "note": f"resume:{type(e).__name__}"})
                    return {"action": "error"}
                state["phase"] = "open"; state["qty"] = filled; save_state(state)
                log_row({**base, "phase": "open", "action": "resumed_open", "qty": qty,
                         "order_id": o.get("id"), "note": "resume"})
                return {"action": "resumed_open"}

        if state["phase"] in ("closing_futures", "closing_spot"):
            res = close_carry(spot_ex, fut_ex, state, snap, spot_mkt, fut_mkt,
                              dry_run, reason="resume_close")
            return {"action": res["action"]}

        # 2) 포지션 존재 시 건강 체크 (정합 → DD → margin)
        has_legs = abs(snap["perp_amt"]) > 0 or \
            snap["spot_base"] * price >= (spot_mkt["limits"]["cost"]["min"] or 10.0)
        if state["phase"] == "open" or has_legs:
            fut_min = fut_mkt["limits"]["cost"]["min"] or 100.0
            if leg_mismatch(snap["spot_base"], snap["perp_amt"], price,
                            max(spot_mkt["limits"]["cost"]["min"] or 10.0, fut_min)):
                state["phase"] = "halted_manual"; state["reason"] = "leg_mismatch"
                if live: save_state(state)            # 자동 보정 금지 — 탐지+정지만
                log_row({**base, "phase": "halted_manual", "action": "halted",
                         "note": "leg_mismatch"})
                print("[carry] LEG MISMATCH — halt, 수동확인 필요")
                return {"action": "halted", "reason": "leg_mismatch"}

            breach = update_high_water_and_breach(equity, state, dd_limit=DD_LIMIT)
            guard = margin_breach(snap["fut"]["available"], snap["fut"]["wallet"])
            if breach or guard:
                reason = f"drawdown<=-{int(DD_LIMIT*100)}%" if breach else "margin_guard"
                state["reason"] = reason
                if live: save_state(state)            # 상태 먼저 저장 → 청산 1회
                close_carry(spot_ex, fut_ex, state, snap, spot_mkt, fut_mkt,
                            dry_run, reason=reason)
                state["phase"] = "halted_manual"
                if live: save_state(state)
                print(f"[carry] KILL-SWITCH({reason}) — 청산+정지")
                return {"action": "kill_switch", "reason": reason}

        # 3) idle → 신규 진입은 live+confirm_open일 때만 (dry는 would_open 로그)
        if state["phase"] == "idle":
            if confirm_open:
                res = open_carry(spot_ex, fut_ex, state, snap, spot_mkt, fut_mkt, dry_run)
                return {"action": res["action"]}
            log_row({**base, "action": "none", "note": "no_confirm_open"})
            if live: save_state(state)                # high_water 등 유지
            return {"action": "none"}

        # 4) open & healthy → 무주문 (감사 로그만)
        log_row({**base, "action": "none", "note": "healthy"})
        if live: save_state(state)
        print(f"[carry] phase={state['phase']} equity={equity:.2f} "
              f"{'(dry-run)' if dry_run else ''}")
        return {"action": "none", "phase": state["phase"]}
    finally:
        fcntl.flock(lock_file, fcntl.LOCK_UN); lock_file.close()


if __name__ == "__main__":
    load_env()
    live = "--live" in sys.argv
    confirm_open = "--confirm-open" in sys.argv
    if confirm_open and not live:
        print("[carry] --confirm-open은 --live와 함께만 유효 (dry-run으로 진행)")
    if live:                                          # 주문 전 양쪽 demo 연결/키 검증
        se = make_spot_exchange(); _assert_demo_spot(se); se.private_get_account()
        fe = make_fapi_exchange(); fe.fapiPrivateV2GetAccount()
        print("[carry] spot+fut demo 인증 확인됨 — LIVE 모드")
        run_once(live=True, confirm_open=confirm_open, spot_ex=se, fut_ex=fe)
    else:
        run_once(live=False, confirm_open=confirm_open)
```

- [ ] **Step 4: 통과 확인**

Run: `./.venv/bin/python -m pytest tests/test_carry_executor.py -q`
Expected: PASS (36 passed)

- [ ] **Step 5: 전체 테스트 회귀 확인**

Run: `./.venv/bin/python -m pytest -q`
Expected: PASS (기존 107 + 신규 36 = 143 passed) — 기존 테스트 깨짐 0

- [ ] **Step 6: Commit**

```bash
git add carry_executor.py tests/test_carry_executor.py
git commit -m "feat(carry): run_once 오케스트레이션 — phase 분기·2층 킬스위치·크래시 재개·__main__ (Task4)"
```

---

### Task 5: dry-run 실환경 검증 + 문서 갱신

**Files:**
- Modify: `docs/design/README.md` (상태 갱신)
- 실행 검증만 (코드 변경 없음 예상)

**Interfaces:**
- Consumes: Task 1~4 완성된 `carry_executor.py`.

- [ ] **Step 1: 실환경 dry-run 1회 (주문 0 보장 — Codex 합의 체크리스트 "demo/live 변경은 최소 1회 실환경 dry 검증")**

Run: `cd /Users/test/workspace/quant-trading-bot && ./.venv/bin/python carry_executor.py`
Expected: `[carry] phase=idle ...` 또는 `action=none` 출력, `paper/carry_orders.csv`에 `would_*`/`none` 행 1개, **주문 없음**. 예외 발생 시(예: fapi 스키마 불일치) 원인 수정 후 재실행.

- [ ] **Step 2: dry-run 결과 확인**

Run: `tail -2 paper/carry_orders.csv && cat paper/carry_state.json`
Expected: `dry_run=True` 행, state는 `phase=idle` 유지 (dry-run은 state 저장 안 함 — 파일이 없으면 그것도 정상).

- [ ] **Step 3: 설계 README 인덱스 상태 갱신**

`docs/design/README.md`의 7b-carry-executor 행을 "설계 완료 (구현 중 …)"에서:

```markdown
| 7b-carry-executor | 캐리 양다리 demo 실행기 (숏 퍼프+롱 현물, 부분실패 보상) | 구현 완료 (dry-run 검증 — 첫 --live·cron은 48h 게이트 통과 후 사용자와) | [phase-7b-carry-executor.md](phase-7b-carry-executor.md) |
```

- [ ] **Step 4: Commit**

```bash
git add docs/design/README.md
git commit -m "docs(design): 7b-carry-executor 구현완료(dry-run 검증) 인덱스 갱신 (Task5)"
```

---

## 플랜 밖 (구현 후 별도 진행 — 이 플랜에 포함하지 않음)

- opus 최종 리뷰 + Codex 크로스 리뷰 → ff-merge → push (기존 Phase당 워크플로).
- **48h 게이트 판정(7/4경, 사용자와 함께)** → 통과 시 `--live --confirm-open` 첫 진입 1회(사용자 입회) → cron `15 * * * *` 등록(`cd` 접두어 + `--live`, confirm-open 없이).
- ETH 확장, 포트폴리오 결합(7c)은 별도 Phase.
