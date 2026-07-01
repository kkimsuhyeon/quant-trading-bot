import pytest
import pandas as pd
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
