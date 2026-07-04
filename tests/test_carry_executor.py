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


def test_assert_demo_spot_ignores_dapi_fapi_hosts():
    # 실제 ccxt binance urls["api"]에는 dapi/fapi도 들어있음 — dapi.binance.com이
    # "api.binance.com"을 부분문자열로 포함해도 오탐하면 안 됨 (실환경 dry-run 발견)
    class Ex:
        urls = {"api": {"public": "https://demo-api.binance.com/api",
                        "sapi": "https://demo-api.binance.com/sapi/v1",
                        "dapiPublic": "https://dapi.binance.com/dapi/v1",
                        "fapiPublic": "https://fapi.binance.com/fapi/v1"}}
    ce._assert_demo_spot(Ex())                        # no raise (fapi 가드는 _assert_demo_fapi 몫)


def test_assert_demo_spot_raises_on_mainnet_sapi():
    class Ex:
        urls = {"api": {"sapi": "https://api.binance.com/sapi/v1"}}
    with pytest.raises(RuntimeError):
        ce._assert_demo_spot(Ex())


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


# Task 2: open_carry 진입 테스트용 헬퍼 및 Fake 거래소

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

    def privatePostOrder(self, params):
        qty = params["quantity"]
        if params["side"] == "BUY":
            if self.fail_buy: raise RuntimeError("spot buy failed")
            self.base += qty; self.usdt -= qty * PRICE
        else:
            if self.fail_sell: raise RuntimeError("spot sell failed")
            self.base -= qty; self.usdt += qty * PRICE
        self.orders.append((params["side"].lower(), qty))
        return {"orderId": f"s{len(self.orders)}"}


class FakeFut:
    def __init__(self, wallet=10000.0, available=10000.0, upnl=0.0, perp_amt=0.0,
                 fail_sell=False, fail_reduce=False, fill_on_fail=False):
        self.urls = {"api": {"fapiPublic": "https://demo-fapi.binance.com/fapi",
                             "fapiPrivate": "https://demo-fapi.binance.com/fapi"}}
        self.wallet, self.available, self.upnl = wallet, available, upnl
        self.perp_amt = perp_amt
        self.fail_sell, self.fail_reduce = fail_sell, fail_reduce
        self.fill_on_fail = fill_on_fail                  # 타임아웃인데 실제론 체결됐던 경우 시뮬
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

    def fapiPrivatePostOrder(self, params):
        if params["side"] == "SELL":
            if self.fail_sell:
                if self.fill_on_fail:                      # 타임아웃 응답만 못 받았을 뿐 체결은 됨
                    self.perp_amt -= params["quantity"]
                raise RuntimeError("fut sell failed")
            self.perp_amt -= params["quantity"]
        else:
            if self.fail_reduce: raise RuntimeError("fut reduce failed")
            self.perp_amt += params["quantity"]
        self.orders.append((params["side"].lower(), params["quantity"],
                            {k: v for k, v in params.items() if k == "reduceOnly"}))
        return {"orderId": f"f{len(self.orders)}"}


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


def test_open_futures_fail_leaves_opening_futures_for_next_run():
    spot, fut = FakeSpot(), FakeFut(fail_sell=True)
    state = ce.load_state()
    spot_mkt, fut_mkt = _mkts()
    res = ce.open_carry(spot, fut, state, _snap(spot, fut), spot_mkt, fut_mkt, dry_run=False)
    assert res["action"] == "futures_order_unknown"
    assert spot.orders == []                          # 현물은 손도 안 댐
    assert ce.load_state()["phase"] == "opening_futures"  # 재개가 다음 run에서 해소 (idle 아님)


def test_open_futures_timeout_actually_filled_resumes_to_open():
    # 클라이언트는 예외를 봤지만 거래소엔 숏이 실제로 체결된 케이스 (네트워크 타임아웃)
    spot, fut = FakeSpot(), FakeFut(fail_sell=True, fill_on_fail=True)
    state = ce.load_state()
    spot_mkt, fut_mkt = _mkts()
    res = ce.open_carry(spot, fut, state, _snap(spot, fut), spot_mkt, fut_mkt, dry_run=False)
    assert res["action"] == "futures_order_unknown"

    # 다음 run_once가 재스냅샷하면 숏이 보임 → 현물 다리로 이어서 완료
    res2 = ce.run_once(live=True, spot_ex=spot, fut_ex=fut)
    assert res2["action"] == "resumed_open"
    assert spot.orders == [("buy", 0.05)]
    assert ce.load_state()["phase"] == "open"


def test_open_spot_fail_compensates_with_reduce_only():
    spot, fut = FakeSpot(fail_buy=True), FakeFut()
    state = ce.load_state()
    spot_mkt, fut_mkt = _mkts()
    res = ce.open_carry(spot, fut, state, _snap(spot, fut), spot_mkt, fut_mkt, dry_run=False)
    assert res["action"] == "compensated"
    # 숏 열림 → 현물 실패 → reduce-only 매수로 숏 닫힘
    assert fut.orders[0][0] == "sell"
    assert fut.orders[1][0] == "buy" and fut.orders[1][2].get("reduceOnly") == "true"
    assert state["phase"] == "halted_manual"          # 보상 성공해도 halt (자동 재시도 금지)
    assert state["naked_exposure"] is False


def test_open_compensation_persists_state_before_order():
    captured = {}

    class SpyFut(FakeFut):
        def fapiPrivatePostOrder(self, params):
            captured["phase"] = ce.load_state()["phase"]   # 보상 주문 시점의 디스크 상태
            return super().fapiPrivatePostOrder(params)

    spot, fut = FakeSpot(fail_buy=True), SpyFut()
    state = ce.load_state()
    spot_mkt, fut_mkt = _mkts()
    res = ce.open_carry(spot, fut, state, _snap(spot, fut), spot_mkt, fut_mkt, dry_run=False)
    assert res["action"] == "compensated"
    assert captured["phase"] == "halted_manual"       # 보상 주문 *전에* 선저장 (크래시 일관성)
    assert ce.load_state()["reason"] == "spot_failed_compensated"


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


# Task 3: close_carry 청산 테스트

def test_close_full_position_futures_first():
    spot, fut = FakeSpot(usdt=17000.0, base=0.05), FakeFut(perp_amt=-0.05)
    state = ce.load_state(); state["phase"] = "open"; state["qty"] = 0.05
    spot_mkt, fut_mkt = _mkts()
    res = ce.close_carry(spot, fut, state, _snap(spot, fut), spot_mkt, fut_mkt,
                         dry_run=False, reason="test")
    assert res["action"] == "closed"
    assert fut.orders[0][0] == "buy" and fut.orders[0][2].get("reduceOnly") == "true"
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
    assert fut.orders[0][2].get("reduceOnly") == "true" # 선물은 이미 닫힘
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


def test_close_futures_only_closes_reduce_only():
    spot, fut = FakeSpot(usdt=20000.0, base=0.0), FakeFut(perp_amt=-0.05)   # 현물 다리 없음
    state = ce.load_state(); state["phase"] = "open"; state["qty"] = 0.05
    spot_mkt, fut_mkt = _mkts()
    res = ce.close_carry(spot, fut, state, _snap(spot, fut), spot_mkt, fut_mkt, dry_run=False)
    assert res["action"] == "closed"
    assert fut.orders == [("buy", 0.05, {"reduceOnly": "true"})]
    assert spot.orders == []                          # 팔 현물 없음
    assert state["phase"] == "idle" and state["qty"] == 0.0


def test_close_persists_state_before_each_order():
    captured = {}

    class SpyFut(FakeFut):
        def fapiPrivatePostOrder(self, params):
            captured["fut_phase"] = ce.load_state()["phase"]   # 선물 청산 주문 시점의 디스크 상태
            return super().fapiPrivatePostOrder(params)

    class SpySpot(FakeSpot):
        def privatePostOrder(self, params):
            captured["spot_phase"] = ce.load_state()["phase"]  # 현물 매도 주문 시점의 디스크 상태
            return super().privatePostOrder(params)

    spot, fut = SpySpot(usdt=17000.0, base=0.05), SpyFut(perp_amt=-0.05)
    state = ce.load_state(); state["phase"] = "open"; state["qty"] = 0.05
    spot_mkt, fut_mkt = _mkts()
    res = ce.close_carry(spot, fut, state, _snap(spot, fut), spot_mkt, fut_mkt, dry_run=False)
    assert res["action"] == "closed"
    assert captured["fut_phase"] == "closing_futures"  # 주문 *전에* 선저장 (크래시 일관성)
    assert captured["spot_phase"] == "closing_spot"
    assert state["phase"] == "idle"


# Task 4: run_once 오케스트레이션 테스트

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
    assert fut.orders[0][2].get("reduceOnly") == "true" # 청산 실행됨
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
    assert ce.load_state()["phase"] == "halted_manual"     # 재개 청산은 원인불명 → halt 종결


def test_run_once_rejects_mainnet_injected_exchange():
    spot = FakeSpot()
    spot.urls = {"api": {"public": "https://api.binance.com/api"}}   # mainnet 주입 시도
    with pytest.raises(RuntimeError):
        ce.run_once(live=False, spot_ex=spot, fut_ex=FakeFut())


# 리뷰 Important 3건 회귀 테스트

def test_run_once_kill_switch_never_persists_idle(monkeypatch):
    persisted = []
    real_save = ce.save_state

    def spy_save(state, path=ce.STATE_PATH):
        persisted.append(state["phase"])                  # 디스크에 쓰인 phase 전부 기록
        real_save(state, path)

    monkeypatch.setattr(ce, "save_state", spy_save)
    s = ce.load_state(); s["phase"] = "open"; s["qty"] = 0.05
    s["high_water"] = 30000.0; real_save(s)
    spot, fut = FakeSpot(usdt=13000.0, base=0.05), FakeFut(wallet=10000.0, upnl=-500.0,
                                                            perp_amt=-0.05)
    res = _run(spot, fut, live=True)
    assert res["action"] == "kill_switch"
    assert "idle" not in persisted                        # 킬스위치 중 idle이 디스크에 절대 안 남음
    assert ce.load_state()["phase"] == "halted_manual"


def test_run_once_resume_already_hedged_no_rebuy():
    s = ce.load_state(); s["phase"] = "opening_spot"; s["qty"] = 0.05; ce.save_state(s)
    spot, fut = FakeSpot(usdt=17000.0, base=0.05), FakeFut(perp_amt=-0.05)  # 양다리 이미 완성
    res = _run(spot, fut, live=True)
    assert res["action"] == "resumed_open"
    assert spot.orders == [] and fut.orders == []         # 중복 매수 금지
    assert ce.load_state()["phase"] == "open"


def test_run_once_resume_persists_state_before_spot_order():
    captured = {}

    class SpySpot(FakeSpot):
        def privatePostOrder(self, params):
            captured["phase"] = ce.load_state()["phase"]  # 재개 매수 주문 시점의 디스크 상태
            return super().privatePostOrder(params)

    # opening_futures 폴스루로 진입 — 픽스 전에는 메모리 phase 변경이 미저장이라 디스크가
    # opening_futures인 채 주문이 나감 (선저장 회귀를 실제로 잡는 셋업)
    s = ce.load_state(); s["phase"] = "opening_futures"; s["qty"] = 0.05; ce.save_state(s)
    spot, fut = SpySpot(base=0.0), FakeFut(perp_amt=-0.05)
    res = _run(spot, fut, live=True)
    assert res["action"] == "resumed_open"
    assert captured["phase"] == "opening_spot"            # 주문 *전에* 선저장 (크래시 일관성)
    assert ce.load_state()["phase"] == "open"


def test_run_once_unexpected_long_perp_halts():
    # abs(perp_amt)로만 보면 롱도 헷지처럼 보일 수 있음 — 이 엔진은 숏-only 상태공간이라 halt
    s = ce.load_state(); s["phase"] = "open"; s["qty"] = 0.05; ce.save_state(s)
    spot, fut = FakeSpot(usdt=17000.0, base=0.05), FakeFut(perp_amt=0.05)
    res = _run(spot, fut, live=True)
    assert res["action"] == "halted"
    assert res["reason"] == "unexpected_long_perp"
    assert fut.orders == [] and spot.orders == []
    assert ce.load_state()["phase"] == "halted_manual"
