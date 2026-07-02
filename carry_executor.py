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


def _snapshot(spot_ex, fut_ex):
    usdt, base = _balances(spot_ex)
    fut = parse_fut_account(fut_ex.fapiPrivateV2GetAccount())
    perp = perp_position_amt(fut_ex.fapiPrivateV2GetPositionRisk({"symbol": FUT_SYMBOL}))
    price = float(fut_ex.fapiPublicGetPremiumIndex({"symbol": FUT_SYMBOL})["markPrice"])
    return {"spot_usdt": usdt, "spot_base": base, "price": price, "fut": fut,
            "perp_amt": perp}


def run_once(live=False, confirm_open=False, spot_ex=None, fut_ex=None):
    os.makedirs("paper", exist_ok=True)
    lock_file = open(LOCK_PATH, "w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("[carry] 다른 실행 중 — skip"); lock_file.close(); return {"skip": "lock"}
    try:
        spot_ex = spot_ex or make_spot_exchange()
        fut_ex = fut_ex or make_fapi_exchange()
        _assert_demo_spot(spot_ex); _assert_demo_fapi(fut_ex)   # 주입 경로도 차단(방어심층)
        spot_mkt = fetch_market_filters(spot_ex)
        fut_mkt = fetch_fut_filters(fut_ex)
        snap = _snapshot(spot_ex, fut_ex)
        state = load_state()
        dry_run = not live
        price = snap["price"]
        equity = compute_equity(snap["spot_usdt"], snap["spot_base"], price,
                                snap["fut"]["wallet"], snap["fut"]["upnl"])
        base = {"run_at": _now_iso(), "phase": state["phase"], "price": price,
                "equity": equity, "dry_run": dry_run, "qty": state.get("qty", 0.0),
                "order_id": ""}

        # 0) halted → 수동 리셋 전 아무것도 안 함
        if state["phase"] == "halted_manual":
            log_row({**base, "action": "halted", "note": state.get("reason", "")})
            print(f"[carry] HALTED({state.get('reason')}) — 수동 리셋 필요")
            return {"action": "halted", "reason": state.get("reason")}

        # 1) 크래시 재개 (직전 실행이 중간 phase에서 죽음)
        if state["phase"] == "opening_futures":
            if abs(snap["perp_amt"]) == 0:            # 숏 안 열림 → 깨끗한 초기화
                state["phase"] = "idle"; state["qty"] = 0.0
                if live: save_state(state)
                log_row({**base, "phase": "idle", "action": "reset_idle", "note": "resume"})
                return {"action": "reset_idle"}
            state["phase"] = "opening_spot"           # 숏 확인됨 → 현물 다리 이어서

        if state["phase"] == "opening_spot":
            filled = abs(snap["perp_amt"])
            if filled == 0:                           # 숏도 사라짐 → 정합 체크로 진행
                state["phase"] = "open"
            elif dry_run:
                log_row({**base, "action": "resume_pending", "note": "opening_spot(dry)"})
                return {"action": "resume_pending"}
            else:
                qty = round_amount(filled, spot_mkt["amount_step"])
                log_row({**base, "phase": "opening_spot", "action": "spot_buy_intent",
                         "qty": qty, "note": "resume"})
                try:
                    o = spot_ex.create_market_buy_order(SYMBOL, qty)
                except Exception as e:
                    state["phase"] = "halted_manual"; state["reason"] = "resume_spot_failed"
                    save_state(state)
                    log_row({**base, "phase": "halted_manual", "action": "error",
                             "qty": qty, "note": f"resume:{type(e).__name__}"})
                    return {"action": "error"}
                state["phase"] = "open"; state["qty"] = filled; save_state(state)
                log_row({**base, "phase": "open", "action": "resumed_open", "qty": qty,
                         "order_id": o.get("id"), "note": "resume"})
                return {"action": "resumed_open"}

        if state["phase"] in ("closing_futures", "closing_spot"):
            res = close_carry(spot_ex, fut_ex, state, snap, spot_mkt, fut_mkt,
                              dry_run, reason="resume_close")
            return {"action": res["action"]}

        # 2) 포지션 존재 시 건강 체크 (정합 → DD → margin)
        has_legs = abs(snap["perp_amt"]) > 0 or \
            snap["spot_base"] * price >= (spot_mkt["limits"]["cost"]["min"] or 10.0)
        if state["phase"] == "open" or has_legs:
            fut_min = fut_mkt["limits"]["cost"]["min"] or 100.0
            if leg_mismatch(snap["spot_base"], snap["perp_amt"], price,
                            max(spot_mkt["limits"]["cost"]["min"] or 10.0, fut_min)):
                state["phase"] = "halted_manual"; state["reason"] = "leg_mismatch"
                if live: save_state(state)            # 자동 보정 금지 — 탐지+정지만
                log_row({**base, "phase": "halted_manual", "action": "halted",
                         "note": "leg_mismatch"})
                print("[carry] LEG MISMATCH — halt, 수동확인 필요")
                return {"action": "halted", "reason": "leg_mismatch"}

            breach = update_high_water_and_breach(equity, state, dd_limit=DD_LIMIT)
            guard = margin_breach(snap["fut"]["available"], snap["fut"]["wallet"])
            if breach or guard:
                reason = f"drawdown<=-{int(DD_LIMIT*100)}%" if breach else "margin_guard"
                state["reason"] = reason
                if live: save_state(state)            # 상태 먼저 저장 → 청산 1회
                close_carry(spot_ex, fut_ex, state, snap, spot_mkt, fut_mkt,
                            dry_run, reason=reason)
                state["phase"] = "halted_manual"
                if live: save_state(state)
                print(f"[carry] KILL-SWITCH({reason}) — 청산+정지")
                return {"action": "kill_switch", "reason": reason}

        # 3) idle → 신규 진입은 live+confirm_open일 때만 (dry는 would_open 로그)
        if state["phase"] == "idle":
            if confirm_open:
                res = open_carry(spot_ex, fut_ex, state, snap, spot_mkt, fut_mkt, dry_run)
                return {"action": res["action"]}
            log_row({**base, "action": "none", "note": "no_confirm_open"})
            if live: save_state(state)                # high_water 등 유지
            return {"action": "none"}

        # 4) open & healthy → 무주문 (감사 로그만)
        log_row({**base, "action": "none", "note": "healthy"})
        if live: save_state(state)
        print(f"[carry] phase={state['phase']} equity={equity:.2f} "
              f"{'(dry-run)' if dry_run else ''}")
        return {"action": "none", "phase": state["phase"]}
    finally:
        fcntl.flock(lock_file, fcntl.LOCK_UN); lock_file.close()


if __name__ == "__main__":
    load_env()
    live = "--live" in sys.argv
    confirm_open = "--confirm-open" in sys.argv
    if confirm_open and not live:
        print("[carry] --confirm-open은 --live와 함께만 유효 (dry-run으로 진행)")
    if live:                                          # 주문 전 양쪽 demo 연결/키 검증
        se = make_spot_exchange(); _assert_demo_spot(se); se.private_get_account()
        fe = make_fapi_exchange(); fe.fapiPrivateV2GetAccount()
        print("[carry] spot+fut demo 인증 확인됨 — LIVE 모드")
        run_once(live=True, confirm_open=confirm_open, spot_ex=se, fut_ex=fe)
    else:
        run_once(live=False, confirm_open=confirm_open)
