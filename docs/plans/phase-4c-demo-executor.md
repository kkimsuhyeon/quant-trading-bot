# Phase 4c — 현물 demo 실행 엔진 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`).

**Goal:** Keltner(BTC/USDT 4h) 신호대로 바이낸스 현물 demo에 시장가 주문을 내는 안전한 실행 엔진 `demo_executor.py`. dry-run 기본, 하드 킬스위치, 주문 중복방지, 감사 로그.

**Architecture:** 새 모듈 1개. `paper_trade`의 `fetch_live`/`desired_position`/`_is_stale` 재사용, 전략·하네스 불변. 상태는 `paper/demo_state.json`, 감사는 `paper/demo_orders.csv`(둘 다 gitignore).

**Tech Stack:** Python 3.13, ccxt, pandas, pytest. `.venv/bin/python -m pytest`.

## Global Constraints
- 새 파일 `demo_executor.py` + `tests/test_demo_executor.py`만. 전략/하네스/paper_trade 수정 금지(재사용만).
- **여전히 demo(가짜 돈), 레버리지 0(현물).** 자동 테스트는 **fake exchange**로만 — 실제 네트워크/실주문 절대 금지.
- 기본 `dry_run=True`. 실제 주문은 `--live` 명시 시에만, 그리고 **`--live` 전 demo `fetch_balance`/account 성공 assert**.
- 시장가 **매수는 quoteOrderQty(cost)**, 매도는 base 수량. precision/min-notional는 `load_markets()` 기반.
- **dust**(`base*price < min_notional`)는 미보유 취급. **킬스위치**: equity 고점 대비 −15% → halted 저장(먼저) + 1회 청산 + 수동 리셋 전 재진입 금지. **주문 결과 불명확/중복 위험** 시 자동 재주문 금지, `manual_check_required`.
- 엔드포인트 `BINANCE_DEMO_BASE_URL`(기본 `https://demo-api.binance.com`). 키 `.env`의 `BINANCE_TESTNET_API_KEY/SECRET`.
- **주문 호출(create_market_*)은 반드시 try/except로 감쌀 것 (Codex 3):** 예외(timeout/불명확 체결) 시 `state['halted']=True, reason='order_error_manual_check'` 저장 + 감사로그(action='order_error') + **자동 재주문 금지**(반환 action='error'). 다음 실행은 halted라 신규진입 안 함. → Task 2 reconcile에 포함하고 테스트(주문 raise하는 FakeEx → halted 저장·재시도 없음)로 검증.

---

### Task 1: 상태·잔고·dust·킬스위치 (순수 로직)

**Files:** Create `demo_executor.py` (상수 + 함수들), Test `tests/test_demo_executor.py`

**Interfaces — Produces:**
- `load_state(path) -> dict` / `save_state(state, path)`
- `is_holding(base_qty, price, min_notional) -> bool`
- `update_high_water_and_breach(equity, state, dd_limit=0.15) -> bool` (state['high_water'] 갱신, breach 여부 반환)

- [ ] **Step 1: failing tests** — `tests/test_demo_executor.py`
```python
import json
import demo_executor as dx


def test_state_roundtrip(tmp_path):
    p = str(tmp_path / "s.json")
    assert dx.load_state(p)["halted"] is False           # 없으면 기본값
    dx.save_state({"high_water": 100.0, "halted": True, "reason": "x",
                   "last_order_signal_bar_time": "t"}, p)
    s = dx.load_state(p)
    assert s["high_water"] == 100.0 and s["halted"] is True


def test_is_holding_dust():
    assert dx.is_holding(0.001, 60000, 10) is True        # 60 USDT >= 10
    assert dx.is_holding(0.00001, 60000, 10) is False     # 0.6 USDT < 10 = dust


def test_high_water_and_breach():
    st = {"high_water": 0.0}
    assert dx.update_high_water_and_breach(10000, st) is False   # 첫 고점
    assert st["high_water"] == 10000
    assert dx.update_high_water_and_breach(9000, st) is False    # -10% (>-15%)
    assert dx.update_high_water_and_breach(8400, st) is True     # -16% breach
    assert st["high_water"] == 10000                            # 고점 유지
```

- [ ] **Step 2: run, expect fail** — `.venv/bin/python -m pytest tests/test_demo_executor.py -v` → ImportError.

- [ ] **Step 3: implement** — `demo_executor.py` (상단)
```python
import os
import sys
import json
import fcntl
import pandas as pd
import ccxt
from paper_trade import fetch_live, desired_position, _is_stale
from strategies.keltner_breakout import KeltnerBreakout

DEMO_BASE = os.environ.get("BINANCE_DEMO_BASE_URL", "https://demo-api.binance.com")
STATE_PATH = "paper/demo_state.json"
ORDERS_CSV = "paper/demo_orders.csv"
LOCK_PATH = "paper/.demo_lock"
SYMBOL = "BTC/USDT"
BASE_ASSET = "BTC"
DD_LIMIT = 0.15
BUY_FRAC = 0.95


def load_state(path=STATE_PATH):
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {"high_water": 0.0, "halted": False, "reason": "", "last_order_signal_bar_time": ""}


def save_state(state, path=STATE_PATH):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        json.dump(state, f, indent=2)


def is_holding(base_qty, price, min_notional):
    return base_qty * price >= min_notional          # dust 미만은 미보유


def update_high_water_and_breach(equity, state, dd_limit=DD_LIMIT):
    hw = max(state.get("high_water", 0.0), equity)
    state["high_water"] = hw
    return hw > 0 and (equity / hw - 1) <= -dd_limit
```

- [ ] **Step 4: run, expect pass** — `.venv/bin/python -m pytest tests/test_demo_executor.py -v` (3 passed). 전체 `-q` 회귀 green.

- [ ] **Step 5: commit** — `git add demo_executor.py tests/test_demo_executor.py && git commit -m "feat(demo): 상태/dust/킬스위치 순수로직 (Phase 4c Task1)"`

---

### Task 2: reconcile + 주문 + 감사로그 + 중복방지

**Files:** Modify `demo_executor.py`, `tests/test_demo_executor.py`

**Interfaces — Produces:**
- `log_order(row, path=ORDERS_CSV)`
- `reconcile(exchange, target, usdt, base_qty, price, market, bar_iso, state, dry_run) -> dict` (주문 결정·실행, 멱등/dust/중복방지 포함)
  - market = `exchange.markets[SYMBOL]` (limits 포함). 매수=`create_market_buy_order_with_cost(SYMBOL, cost)`, 매도=`create_market_sell_order(SYMBOL, qty)`.

- [ ] **Step 1: failing tests** (append). FakeExchange는 네트워크 없이 주문 기록만.
```python
class FakeEx:
    def __init__(self):
        self.markets = {"BTC/USDT": {"limits": {"cost": {"min": 10}, "amount": {"min": 1e-5}}}}
        self.orders = []
    def amount_to_precision(self, s, a): return round(a, 5)
    def create_market_buy_order_with_cost(self, s, cost):
        self.orders.append(("buy", cost)); return {"id": "1", "status": "closed"}
    def create_market_sell_order(self, s, qty):
        self.orders.append(("sell", qty)); return {"id": "2", "status": "closed"}


def test_reconcile_buys_when_target_long_and_flat(tmp_path):
    ex = FakeEx(); st = {"last_order_signal_bar_time": ""}
    r = dx.reconcile(ex, target=1, usdt=10000, base_qty=0.0, price=60000,
                     market=ex.markets["BTC/USDT"], bar_iso="b1", state=st,
                     dry_run=False)
    assert ex.orders == [("buy", 9500.0)]                 # 10000*0.95 cost
    assert r["action"] == "buy" and st["last_order_signal_bar_time"] == "b1"


def test_reconcile_sells_all_when_target_flat_and_holding(tmp_path):
    ex = FakeEx(); st = {"last_order_signal_bar_time": ""}
    dx.reconcile(ex, target=0, usdt=100, base_qty=0.5, price=60000,
                 market=ex.markets["BTC/USDT"], bar_iso="b1", state=st, dry_run=False)
    assert ex.orders == [("sell", 0.5)]


def test_reconcile_idempotent_when_already_in_state():
    ex = FakeEx()
    # 이미 롱(보유) + target 롱 → 무주문
    r = dx.reconcile(ex, target=1, usdt=100, base_qty=0.5, price=60000,
                     market=ex.markets["BTC/USDT"], bar_iso="b1", state={"last_order_signal_bar_time": ""},
                     dry_run=False)
    assert ex.orders == [] and r["action"] == "none"


def test_reconcile_dust_not_holding():
    ex = FakeEx()
    # target 현금 + dust만 보유(0.6 USDT < min 10) → 매도 skip
    r = dx.reconcile(ex, target=0, usdt=100, base_qty=0.00001, price=60000,
                     market=ex.markets["BTC/USDT"], bar_iso="b1", state={"last_order_signal_bar_time": ""},
                     dry_run=False)
    assert ex.orders == [] and r["action"] in ("none", "dust_skip")


def test_reconcile_dry_run_no_order():
    ex = FakeEx()
    dx.reconcile(ex, target=1, usdt=10000, base_qty=0.0, price=60000,
                 market=ex.markets["BTC/USDT"], bar_iso="b1", state={"last_order_signal_bar_time": ""},
                 dry_run=True)
    assert ex.orders == []
```

- [ ] **Step 2: run, expect fail** (reconcile/log_order 없음).

- [ ] **Step 3: implement** (append to `demo_executor.py`)
```python
def log_order(row, path=ORDERS_CSV):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    header = not os.path.exists(path)
    cols = ["run_at", "action", "target", "base_qty", "price", "equity", "cost_or_qty",
            "order_id", "bar_iso", "dry_run", "note"]
    pd.DataFrame([{c: row.get(c) for c in cols}], columns=cols).to_csv(
        path, mode="a", header=header, index=False)


def reconcile(exchange, target, usdt, base_qty, price, market, bar_iso, state, dry_run):
    min_notional = market["limits"]["cost"]["min"] or 0
    holding = is_holding(base_qty, price, min_notional)
    equity = usdt + base_qty * price
    base = {"run_at": pd.Timestamp.now(tz="UTC").isoformat(), "target": target,
            "base_qty": base_qty, "price": price, "equity": equity, "bar_iso": bar_iso,
            "dry_run": dry_run}

    # 멱등: 목표와 현재가 같으면 무주문
    if (target == 1 and holding) or (target == 0 and not holding):
        action = "dust_skip" if (target == 0 and base_qty > 0 and not holding) else "none"
        log_order({**base, "action": action, "order_id": "", "cost_or_qty": "", "note": ""})
        return {"action": action}

    if dry_run:
        action = "would_buy" if target == 1 else "would_sell"
        log_order({**base, "action": action, "order_id": "", "cost_or_qty": "", "note": "dry_run"})
        return {"action": "buy" if target == 1 else "sell", "dry_run": True}

    if target == 1:                                  # 진입: quoteOrderQty(cost) 매수
        cost = round(usdt * BUY_FRAC, 2)
        if cost < min_notional:
            log_order({**base, "action": "skip_min_notional", "order_id": "", "cost_or_qty": cost, "note": ""})
            return {"action": "none", "note": "below_min_notional"}
        log_order({**base, "action": "buy_intent", "order_id": "", "cost_or_qty": cost, "note": ""})
        o = exchange.create_market_buy_order_with_cost(SYMBOL, cost)
        state["last_order_signal_bar_time"] = bar_iso
        log_order({**base, "action": "buy", "order_id": o.get("id"), "cost_or_qty": cost, "note": ""})
        return {"action": "buy", "order": o}
    else:                                            # 청산: base 전량 매도
        qty = exchange.amount_to_precision(SYMBOL, base_qty)
        log_order({**base, "action": "sell_intent", "order_id": "", "cost_or_qty": qty, "note": ""})
        o = exchange.create_market_sell_order(SYMBOL, float(qty))
        state["last_order_signal_bar_time"] = bar_iso
        log_order({**base, "action": "sell", "order_id": o.get("id"), "cost_or_qty": qty, "note": ""})
        return {"action": "sell", "order": o}
```

- [ ] **Step 4: run, expect pass** (5 passed). 전체 회귀 green.
- [ ] **Step 5: commit** — `git commit -m "feat(demo): reconcile 주문(quoteOrderQty 매수/전량 매도)+dust skip+멱등+감사로그 (Task2)"`

---

### Task 3: run_once 오케스트레이션 (엔드포인트 검증·킬스위치 순서·락·CLI)

**Files:** Modify `demo_executor.py`, `tests/test_demo_executor.py`

**Interfaces — Produces:**
- `make_exchange() -> ccxt.binance` (DEMO_BASE로 URL 치환, .env 키)
- `run_once(live=False, exchange=None, fetch=None, now=None) -> dict` (의존성 주입 가능 → 테스트)

- [ ] **Step 1: failing tests** (append) — FakeEx 확장 + 주입.
```python
def test_run_once_kill_switch_halts_and_flattens(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ex = FakeEx()
    ex.private_get_account = lambda: {"balances": [{"asset": "USDT", "free": "100"},
                                                   {"asset": "BTC", "free": "0.1"}]}
    ex.load_markets = lambda: ex.markets
    # 고점 12000 저장 → 현재 equity ~ 100 + 0.1*60000=6100 → -49% breach
    dx.save_state({"high_water": 12000.0, "halted": False, "reason": "",
                   "last_order_signal_bar_time": ""}, dx.STATE_PATH)
    df = _df_uptrend()                       # 헬퍼: Keltner 롱 유발 4h df
    r = dx.run_once(live=True, exchange=ex, fetch=lambda **k: df,
                    now=df.index[-1] + pd.Timedelta(hours=4))
    st = dx.load_state(dx.STATE_PATH)
    assert st["halted"] is True
    assert ("sell", 0.1) in ex.orders        # 보유분 1회 청산
    assert r["halted"] is True


def test_run_once_skips_when_already_halted(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ex = FakeEx(); ex.private_get_account = lambda: {"balances": []}; ex.load_markets = lambda: ex.markets
    dx.save_state({"high_water": 1.0, "halted": True, "reason": "prev",
                   "last_order_signal_bar_time": ""}, dx.STATE_PATH)
    df = _df_uptrend()
    r = dx.run_once(live=True, exchange=ex, fetch=lambda **k: df,
                    now=df.index[-1] + pd.Timedelta(hours=4))
    assert ex.orders == [] and r["halted"] is True     # halted면 신규진입 금지
```
(헬퍼 `_df_uptrend()`는 paper_trade `_to_live_df`로 상승추세 4h df 생성 — Task1 테스트 상단에 추가.)

- [ ] **Step 2: run, expect fail.**

- [ ] **Step 3: implement** (append)
```python
def make_exchange():
    ex = ccxt.binance({"apiKey": os.environ.get("BINANCE_TESTNET_API_KEY"),
                       "secret": os.environ.get("BINANCE_TESTNET_API_SECRET")})
    for k in list(ex.urls["api"]):
        if isinstance(ex.urls["api"][k], str):
            ex.urls["api"][k] = ex.urls["api"][k].replace("https://api.binance.com", DEMO_BASE)
    return ex


def _balances(exchange):
    acct = exchange.private_get_account()             # demo는 /api/v3/account 사용(fetch_balance는 sapi라 X)
    b = {x["asset"]: float(x["free"]) for x in acct["balances"]}
    return b.get("USDT", 0.0), b.get(BASE_ASSET, 0.0)


def run_once(live=False, exchange=None, fetch=None, now=None):
    os.makedirs("paper", exist_ok=True)
    lock_file = open(LOCK_PATH, "w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("[demo] 다른 실행 중 — skip"); lock_file.close(); return {"skip": "lock"}
    try:
        exchange = exchange or make_exchange()
        fetch = fetch or fetch_live
        markets = exchange.load_markets()
        market = markets[SYMBOL] if isinstance(markets, dict) and SYMBOL in markets else exchange.markets[SYMBOL]
        if now is None:
            now = pd.Timestamp.now(tz="UTC")

        df = fetch(symbol=SYMBOL, timeframe="4h")
        if _is_stale(df.index[-1], now, "4h"):
            print("[demo] STALE — skip"); return {"skip": "stale"}

        usdt, base_qty = _balances(exchange)
        price = float(df["Close"].iloc[-1])
        equity = usdt + base_qty * price
        state = load_state()

        if state.get("halted"):
            print(f"[demo] HALTED({state.get('reason')}) — 수동 리셋 전 거래 안 함")
            return {"halted": True, "reason": state.get("reason")}

        breach = update_high_water_and_breach(equity, state)
        if breach:                                    # 상태 먼저 저장 → 1회 청산
            state["halted"] = True; state["reason"] = f"drawdown<=-{int(DD_LIMIT*100)}%"
            save_state(state)
            if is_holding(base_qty, price, market["limits"]["cost"]["min"] or 0) and live:
                exchange.create_market_sell_order(SYMBOL, float(exchange.amount_to_precision(SYMBOL, base_qty)))
            print("[demo] KILL-SWITCH 발동 — 청산+정지"); return {"halted": True}

        bar_iso = df.index[-1].isoformat()
        target = desired_position(df, KeltnerBreakout)
        res = reconcile(exchange, target, usdt, base_qty, price, market, bar_iso, state, dry_run=not live)
        save_state(state)
        print(f"[demo] target={target} action={res.get('action')} equity={equity:.2f} {'(dry-run)' if not live else ''}")
        return {"target": target, **res, "halted": False}
    finally:
        fcntl.flock(lock_file, fcntl.LOCK_UN); lock_file.close()


if __name__ == "__main__":
    live = "--live" in sys.argv
    if live:                                          # --live 전 demo 연결/키 검증
        ex = make_exchange()
        ex.private_get_account()                      # 실패 시 예외로 즉시 중단(주문 전)
        print("[demo] demo 계정 인증 확인됨 — LIVE 모드")
    run_once(live=live)
```

- [ ] **Step 4: run, expect pass** (전체 green, pristine).
- [ ] **Step 5: commit** — `git commit -m "feat(demo): run_once 오케스트레이션(엔드포인트 검증·킬스위치 순서·락·dry-run/--live CLI) (Task3)"`
