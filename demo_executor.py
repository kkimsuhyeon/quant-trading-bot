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
