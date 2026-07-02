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
