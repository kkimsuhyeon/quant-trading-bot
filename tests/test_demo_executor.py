import json
import os
import tempfile
from datetime import timedelta
import pytest
import pandas as pd
import demo_executor as dx


def _df_uptrend():
    """Keltner 롱 신호를 유발하는 상승추세 4h df (UTC timezone-aware DatetimeIndex)"""
    n = 200
    base = 50000.0
    idx = pd.date_range("2024-01-01", periods=n, freq="4h", tz="UTC")
    closes = [base + i * 100 for i in range(n)]
    opens = [c - 50 for c in closes]
    highs = [c + 200 for c in closes]
    lows = [c - 200 for c in closes]
    vols = [100.0] * n
    df = pd.DataFrame(
        {"Open": opens, "High": highs, "Low": lows, "Close": closes, "Volume": vols},
        index=idx,
    )
    return df


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


# ── Task 2: reconcile 테스트 ──────────────────────────────────────────────────

class FakeEx:
    def __init__(self):
        self.markets = {"BTC/USDT": {"limits": {"cost": {"min": 10}, "amount": {"min": 1e-5}}, "amount_step": 1e-5}}
        self.orders = []
    def amount_to_precision(self, s, a): return round(a, 5)
    def public_get_exchangeinfo(self, params=None):
        return {"symbols": [{"filters": [
            {"filterType": "NOTIONAL", "minNotional": "10.0"},
            {"filterType": "LOT_SIZE", "stepSize": "0.00001", "minQty": "0.00001"},
        ]}]}
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
    r = dx.reconcile(ex, target=0, usdt=100, base_qty=0.5, price=60000,
                     market=ex.markets["BTC/USDT"], bar_iso="b1", state=st, dry_run=False)
    assert ex.orders == [("sell", 0.5)]
    assert r["action"] == "sell"
    assert st["last_order_signal_bar_time"] == "b1"


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


def test_reconcile_order_error_halts_state():
    """create_market_buy_order_with_cost 예외 → state halted, error 반환, 주문 기록 없음"""
    class FakeExError(FakeEx):
        def create_market_buy_order_with_cost(self, s, cost):
            raise Exception("timeout")

    ex = FakeExError()
    st = {"last_order_signal_bar_time": "", "halted": False, "reason": ""}
    r = dx.reconcile(ex, target=1, usdt=10000, base_qty=0.0, price=60000,
                     market=ex.markets["BTC/USDT"], bar_iso="b1", state=st,
                     dry_run=False)
    assert r == {"action": "error"}
    assert st["halted"] is True
    assert st["reason"] == "order_error_manual_check"
    assert ex.orders == []  # 성공한 주문 없음


def test_reconcile_sell_error_halts_state():
    """create_market_sell_order 예외 → state halted, error 반환, 주문 기록 없음"""
    class FakeExSellError(FakeEx):
        def create_market_sell_order(self, s, qty):
            raise Exception("sell_timeout")

    ex = FakeExSellError()
    st = {"last_order_signal_bar_time": "", "halted": False, "reason": ""}
    r = dx.reconcile(ex, target=0, usdt=100, base_qty=0.5, price=60000,
                     market=ex.markets["BTC/USDT"], bar_iso="b1", state=st,
                     dry_run=False)
    assert r["action"] == "error"
    assert st["halted"] is True
    assert st["reason"] == "order_error_manual_check"
    assert ex.orders == []  # 성공한 주문 없음


def test_reconcile_halted_guard_skips_order():
    """halted=True 상태에서 reconcile 호출 → 주문 없음, action=error, note=halted"""
    ex = FakeEx()
    st = {"halted": True, "reason": "prior_halt", "last_order_signal_bar_time": ""}
    r = dx.reconcile(ex, target=1, usdt=10000, base_qty=0.0, price=60000,
                     market=ex.markets["BTC/USDT"], bar_iso="b1", state=st,
                     dry_run=False)
    assert ex.orders == []
    assert r["action"] == "error"
    assert r.get("note") == "halted"


# ── Task 3: run_once 테스트 ───────────────────────────────────────────────────

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
                    now=df.index[-1] + timedelta(hours=4))
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
                    now=df.index[-1] + timedelta(hours=4))
    assert ex.orders == [] and r["halted"] is True     # halted면 신규진입 금지


# ── Fix A: dry-run 브리치 → halted 저장 안 함 ────────────────────────────────

def test_run_once_kill_switch_dry_run_no_state_mutation(tmp_path, monkeypatch):
    # dry-run(live=False) 브리치: demo_state.json의 halted는 False 유지 (side-effect-free), 주문도 없음
    monkeypatch.chdir(tmp_path)
    ex = FakeEx()
    ex.private_get_account = lambda: {"balances": [{"asset": "USDT", "free": "100"},
                                                   {"asset": "BTC", "free": "0.1"}]}
    ex.load_markets = lambda: ex.markets
    dx.save_state({"high_water": 12000.0, "halted": False, "reason": "",
                   "last_order_signal_bar_time": ""}, dx.STATE_PATH)
    df = _df_uptrend()
    r = dx.run_once(live=False, exchange=ex, fetch=lambda **k: df,
                    now=df.index[-1] + timedelta(hours=4))
    assert dx.load_state(dx.STATE_PATH)["halted"] is False  # dry-run: 상태 저장 안 함
    assert ex.orders == []                                  # dry-run: 청산 주문 없음
    assert r["halted"] is True                              # 반환값에는 would_halt 표시


# ── Fix B: load_env ──────────────────────────────────────────────────────────

def test_load_env_injects_keys(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("BINANCE_DEMO_API_KEY=mykey\nBINANCE_DEMO_API_SECRET=mysecret\n")
    # os.environ을 격리해 clean-up 보장
    monkeypatch.delenv("BINANCE_DEMO_API_KEY", raising=False)
    monkeypatch.delenv("BINANCE_DEMO_API_SECRET", raising=False)
    dx.load_env(str(env_file))
    assert os.environ.get("BINANCE_DEMO_API_KEY") == "mykey"
    assert os.environ.get("BINANCE_DEMO_API_SECRET") == "mysecret"


def test_load_env_skips_blanks_and_comments(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("# 주석\n\nSOME_KEY=val\n")
    monkeypatch.delenv("SOME_KEY", raising=False)
    dx.load_env(str(env_file))
    assert os.environ.get("SOME_KEY") == "val"


def test_load_env_setdefault_does_not_overwrite(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("MY_VAR=from_file\n")
    monkeypatch.setenv("MY_VAR", "already_set")
    dx.load_env(str(env_file))
    assert os.environ.get("MY_VAR") == "already_set"


def test_load_env_missing_file_is_noop(tmp_path):
    # 파일 없으면 조용히 무시
    dx.load_env(str(tmp_path / "nonexistent.env"))  # exception 없어야 함


# ── Fix C: kill-switch 청산 예외 처리 ────────────────────────────────────────

def test_run_once_kill_switch_sell_exception_halts_gracefully(tmp_path, monkeypatch):
    """kill-switch 발동 시 create_market_sell_order 예외 → halted=True, reason=liquidation_failed, 주문 미기록, 크래시 없음"""
    monkeypatch.chdir(tmp_path)

    class FakeExSellFail(FakeEx):
        def create_market_sell_order(self, s, qty):
            raise Exception("network_error")

    ex = FakeExSellFail()
    ex.private_get_account = lambda: {"balances": [{"asset": "USDT", "free": "100"},
                                                   {"asset": "BTC", "free": "0.1"}]}
    ex.load_markets = lambda: ex.markets
    dx.save_state({"high_water": 12000.0, "halted": False, "reason": "",
                   "last_order_signal_bar_time": ""}, dx.STATE_PATH)
    df = _df_uptrend()
    # 예외가 발생해도 크래시 없이 반환
    r = dx.run_once(live=True, exchange=ex, fetch=lambda **k: df,
                    now=df.index[-1] + timedelta(hours=4))
    st = dx.load_state(dx.STATE_PATH)
    assert st["halted"] is True
    assert "liquidation_failed" in st["reason"]
    assert r["halted"] is True
    # audit log에 kill_switch_intent 행이 기록돼야 함
    import os as _os
    assert _os.path.exists(dx.ORDERS_CSV)
    import pandas as _pd
    log = _pd.read_csv(dx.ORDERS_CSV)
    assert "kill_switch_intent" in log["action"].values


# ── Fix D: last_order_signal_bar_time 같은 봉 중복 가드 ──────────────────────

def test_reconcile_same_bar_dedup_skips_order():
    """state에 이미 해당 bar_iso가 기록돼 있으면 reconcile이 주문 없이 반환"""
    ex = FakeEx()
    st = {"last_order_signal_bar_time": "b1", "halted": False}
    r = dx.reconcile(ex, target=1, usdt=10000, base_qty=0.0, price=60000,
                     market=ex.markets["BTC/USDT"], bar_iso="b1", state=st,
                     dry_run=False)
    assert ex.orders == []
    assert r["action"] == "none"
    assert r.get("note") == "already_acted_this_bar"


# ── fetch_market_filters / round_amount 단위 테스트 ──────────────────────────

def test_fetch_market_filters_parses_canned_response():
    ex = FakeEx()
    m = dx.fetch_market_filters(ex, symbol="BTCUSDT")
    assert m["limits"]["cost"]["min"] == 10.0
    assert m["limits"]["amount"]["min"] == 1e-5
    assert m["amount_step"] == 1e-5


def test_round_amount_floors_to_step():
    assert dx.round_amount(0.123456, 1e-5) == pytest.approx(0.12345)
    assert dx.round_amount(0.5, 1e-5) == pytest.approx(0.5)


def test_round_amount_zero_step_passthrough():
    assert dx.round_amount(0.123456, 0) == 0.123456
