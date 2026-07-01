FAPI_DEMO_HOST = "demo-fapi.binance.com"
FAPI_MAINNET_HOST = "fapi.binance.com"
SYMBOLS = [("BTCUSDT", "BTC/USDT"), ("ETHUSDT", "ETH/USDT")]

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
