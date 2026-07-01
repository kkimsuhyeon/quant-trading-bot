import os
import time
import fcntl
import pandas as pd
import ccxt
from demo_executor import load_env

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
