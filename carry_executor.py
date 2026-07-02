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
