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
