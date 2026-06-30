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
