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


def _now_iso():
    return pd.Timestamp.now(tz="UTC").isoformat()


def open_carry(spot_ex, fut_ex, state, snap, spot_mkt, fut_mkt, dry_run):
    """진입: 선물 숏 먼저(불안정한 다리) → 체결량 확인 → 동수량 현물 매수.
    실패 처리: 선물 실패=깨끗한 중단 / 현물 실패=선물 reduce-only 보상 / 보상 실패=naked halt."""
    price = snap["price"]
    equity = compute_equity(snap["spot_usdt"], snap["spot_base"], price,
                            snap["fut"]["wallet"], snap["fut"]["upnl"])
    base = {"run_at": _now_iso(), "phase": state["phase"], "price": price,
            "equity": equity, "dry_run": dry_run}
    spot_min = spot_mkt["limits"]["cost"]["min"] or 10.0

    # precheck: 기존 포지션 없어야 진입 (perp 0 + 현물 dust만)
    if snap["perp_amt"] != 0 or snap["spot_base"] * price >= spot_min:
        log_row({**base, "action": "skip", "qty": 0, "order_id": "", "note": "position_exists"})
        return {"action": "skip", "note": "position_exists"}
    if not snap["fut"]["can_trade"]:
        log_row({**base, "action": "skip", "qty": 0, "order_id": "", "note": "cannot_trade"})
        return {"action": "skip", "note": "cannot_trade"}

    notional = min(snap["fut"]["available"] * FUT_FRAC, snap["spot_usdt"] * SPOT_FRAC)
    qty = round_amount(round_amount(notional / price, fut_mkt["amount_step"]),
                       spot_mkt["amount_step"])
    if qty * price < max(spot_min, fut_mkt["limits"]["cost"]["min"] or 100.0):
        log_row({**base, "action": "skip", "qty": qty, "order_id": "", "note": "below_min_notional"})
        return {"action": "skip", "note": "below_min_notional"}

    if dry_run:
        log_row({**base, "action": "would_open", "qty": qty, "order_id": "", "note": "dry_run"})
        return {"action": "would_open", "qty": qty}

    # 다리 1: 선물 숏 (intent 저장 → 주문)
    state["phase"] = "opening_futures"; state["qty"] = qty; save_state(state)
    log_row({**base, "phase": "opening_futures", "action": "fut_sell_intent", "qty": qty,
             "order_id": "", "note": ""})
    try:
        o = fut_ex.create_market_sell_order(SYMBOL, qty)
    except Exception as e:
        state["phase"] = "idle"; state["qty"] = 0.0; save_state(state)   # 아무 일도 안 일어남
        log_row({**base, "phase": "idle", "action": "aborted_futures", "qty": qty,
                 "order_id": "", "note": f"{type(e).__name__}"})
        return {"action": "aborted_futures"}
    log_row({**base, "phase": "opening_futures", "action": "fut_sell", "qty": qty,
             "order_id": o.get("id"), "note": ""})

    # 실제 체결량 확인 → 그 수량으로 현물 매수
    filled = abs(perp_position_amt(fut_ex.fapiPrivateV2GetPositionRisk({"symbol": FUT_SYMBOL})))
    spot_qty = round_amount(filled, spot_mkt["amount_step"])
    state["phase"] = "opening_spot"; state["qty"] = filled; save_state(state)
    log_row({**base, "phase": "opening_spot", "action": "spot_buy_intent", "qty": spot_qty,
             "order_id": "", "note": ""})
    try:
        o2 = spot_ex.create_market_buy_order(SYMBOL, spot_qty)
    except Exception as e:
        # 다리 2 실패 → 보상: 선물 reduce-only 청산. 성공해도 halt (자동 재시도 금지 — Codex)
        # 보상 주문 *전에* 선저장 — 크래시 시 디스크가 halted_manual+compensating이라 사람이 확인
        state["phase"] = "halted_manual"; state["reason"] = "spot_failed_compensating"
        save_state(state)
        log_row({**base, "phase": "opening_spot", "action": "compensate_intent", "qty": filled,
                 "order_id": "", "note": f"spot_buy_failed:{type(e).__name__}"})
        try:
            oc = fut_ex.create_market_buy_order(SYMBOL, filled, {"reduceOnly": True})
            state["reason"] = "spot_failed_compensated"
            state["qty"] = 0.0; save_state(state)
            log_row({**base, "phase": "halted_manual", "action": "compensated", "qty": filled,
                     "order_id": oc.get("id"), "note": ""})
            return {"action": "compensated"}
        except Exception as e2:
            state["phase"] = "halted_manual"; state["reason"] = "spot_failed_compensation_failed"
            state["naked_exposure"] = True; save_state(state)
            log_row({**base, "phase": "halted_manual", "action": "error", "qty": filled,
                     "order_id": "", "note": f"naked_short:{type(e2).__name__}"})
            return {"action": "error", "note": "naked_exposure"}

    state["phase"] = "open"; save_state(state)
    log_row({**base, "phase": "open", "action": "opened", "qty": spot_qty,
             "order_id": o2.get("id"), "note": ""})
    return {"action": "opened", "qty": spot_qty}


def close_carry(spot_ex, fut_ex, state, snap, spot_mkt, fut_mkt, dry_run, reason=""):
    """청산: 위험 다리(선물 숏) 먼저 reduce-only → 현물 매도. 실패 시 halt, 재시도 금지."""
    price = snap["price"]
    equity = compute_equity(snap["spot_usdt"], snap["spot_base"], price,
                            snap["fut"]["wallet"], snap["fut"]["upnl"])
    base = {"run_at": _now_iso(), "phase": state["phase"], "price": price,
            "equity": equity, "dry_run": dry_run}
    spot_min = spot_mkt["limits"]["cost"]["min"] or 10.0
    short_qty = abs(snap["perp_amt"])
    spot_holding = snap["spot_base"] * price >= spot_min

    if dry_run:
        if short_qty or spot_holding:
            log_row({**base, "action": "would_close", "qty": short_qty or snap["spot_base"],
                     "order_id": "", "note": reason or "dry_run"})
            return {"action": "would_close"}
        return {"action": "none"}

    # 다리 1: 선물 숏 존재 → reduce-only 청산 먼저 (위험 다리 제거)
    if short_qty:
        state["phase"] = "closing_futures"; save_state(state)
        log_row({**base, "phase": "closing_futures", "action": "fut_close_intent",
                 "qty": short_qty, "order_id": "", "note": reason})
        try:
            o = fut_ex.create_market_buy_order(SYMBOL, short_qty, {"reduceOnly": True})
        except Exception as e:
            state["phase"] = "halted_manual"; state["reason"] = "close_futures_failed"
            save_state(state)
            log_row({**base, "phase": "halted_manual", "action": "error", "qty": short_qty,
                     "order_id": "", "note": f"fut_close_failed:{type(e).__name__}"})
            return {"action": "error", "note": "close_futures_failed"}
        log_row({**base, "phase": "closing_futures", "action": "fut_close",
                 "qty": short_qty, "order_id": o.get("id"), "note": reason})

    # 다리 2: 현물 매도 (실패해도 잔여 롱은 양성 — halt만)
    if spot_holding:
        qty = round_amount(snap["spot_base"], spot_mkt["amount_step"])
        state["phase"] = "closing_spot"; save_state(state)
        log_row({**base, "phase": "closing_spot", "action": "spot_sell_intent",
                 "qty": qty, "order_id": "", "note": reason})
        try:
            o2 = spot_ex.create_market_sell_order(SYMBOL, qty)
        except Exception as e:
            state["phase"] = "halted_manual"; state["reason"] = "close_spot_failed"
            save_state(state)
            log_row({**base, "phase": "halted_manual", "action": "error", "qty": qty,
                     "order_id": "", "note": f"spot_sell_failed:{type(e).__name__}"})
            return {"action": "error", "note": "close_spot_failed"}
        log_row({**base, "phase": "closing_spot", "action": "spot_sell",
                 "qty": qty, "order_id": o2.get("id"), "note": reason})

    state["phase"] = "idle"; state["qty"] = 0.0; save_state(state)
    log_row({**base, "phase": "idle", "action": "closed", "qty": 0, "order_id": "",
             "note": reason})
    return {"action": "closed"}
