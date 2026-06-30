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


def log_order(row, path=ORDERS_CSV):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    header = not os.path.exists(path)
    cols = ["run_at", "action", "target", "base_qty", "price", "equity", "cost_or_qty",
            "order_id", "bar_iso", "dry_run", "note"]
    pd.DataFrame([{c: row.get(c) for c in cols}], columns=cols).to_csv(
        path, mode="a", header=header, index=False)


def reconcile(exchange, target, usdt, base_qty, price, market, bar_iso, state, dry_run):
    if state.get("halted"):
        log_order({"run_at": pd.Timestamp.now(tz="UTC").isoformat(), "target": target,
                   "base_qty": base_qty, "price": price, "equity": usdt + base_qty * price,
                   "bar_iso": bar_iso, "dry_run": dry_run,
                   "action": "halted_skip", "order_id": "", "cost_or_qty": "", "note": "halted"})
        return {"action": "error", "note": "halted"}
    min_notional = market["limits"]["cost"]["min"] or 10.0
    holding = is_holding(base_qty, price, min_notional)
    equity = usdt + base_qty * price
    base = {"run_at": pd.Timestamp.now(tz="UTC").isoformat(), "target": target,
            "base_qty": base_qty, "price": price, "equity": equity, "bar_iso": bar_iso,
            "dry_run": dry_run}

    # 멱등: 목표와 현재가 같으면 무주문
    if (target == 1 and holding) or (target == 0 and not holding):
        action = "dust_skip" if (target == 0 and base_qty > 0 and not holding) else "none"
        log_order({**base, "action": action, "order_id": "", "cost_or_qty": "", "note": ""})
        return {"action": action}

    if dry_run:
        action = "would_buy" if target == 1 else "would_sell"
        log_order({**base, "action": action, "order_id": "", "cost_or_qty": "", "note": "dry_run"})
        return {"action": "buy" if target == 1 else "sell", "dry_run": True}

    if target == 1:                                  # 진입: quoteOrderQty(cost) 매수
        cost = round(usdt * BUY_FRAC, 2)
        if cost < min_notional:
            log_order({**base, "action": "skip_min_notional", "order_id": "", "cost_or_qty": cost, "note": ""})
            return {"action": "none", "note": "below_min_notional"}
        log_order({**base, "action": "buy_intent", "order_id": "", "cost_or_qty": cost, "note": ""})
        try:
            o = exchange.create_market_buy_order_with_cost(SYMBOL, cost)
        except Exception:
            state["halted"] = True
            state["reason"] = "order_error_manual_check"
            log_order({**base, "action": "order_error", "order_id": "", "cost_or_qty": cost, "note": "buy_failed"})
            return {"action": "error"}
        state["last_order_signal_bar_time"] = bar_iso
        log_order({**base, "action": "buy", "order_id": o.get("id"), "cost_or_qty": cost, "note": ""})
        return {"action": "buy", "order": o}
    else:                                            # 청산: base 전량 매도
        qty = exchange.amount_to_precision(SYMBOL, base_qty)
        log_order({**base, "action": "sell_intent", "order_id": "", "cost_or_qty": qty, "note": ""})
        try:
            o = exchange.create_market_sell_order(SYMBOL, float(qty))
        except Exception:
            state["halted"] = True
            state["reason"] = "order_error_manual_check"
            log_order({**base, "action": "order_error", "order_id": "", "cost_or_qty": qty, "note": "sell_failed"})
            return {"action": "error"}
        state["last_order_signal_bar_time"] = bar_iso
        log_order({**base, "action": "sell", "order_id": o.get("id"), "cost_or_qty": qty, "note": ""})
        return {"action": "sell", "order": o}
