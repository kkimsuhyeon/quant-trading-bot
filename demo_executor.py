import math
import os
from decimal import Decimal, ROUND_DOWN
import sys
import json
import fcntl
import pandas as pd
import ccxt
from paper_trade import fetch_live, desired_position, _is_stale
from strategies.keltner_breakout import KeltnerBreakout

DEMO_BASE = os.environ.get("BINANCE_DEMO_BASE_URL", "https://demo-api.binance.com")


def load_env(path=".env"):
    """KEY=VALUE 파싱해서 os.environ에 setdefault로 주입 (이미 있는 값은 덮지 않음)."""
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())
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
    if state.get("last_order_signal_bar_time") == bar_iso:
        return {"action": "none", "note": "already_acted_this_bar"}
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
        qty = round_amount(base_qty, market.get("amount_step", 1e-5))
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


def make_exchange():
    load_env()
    # 키 변수명: BINANCE_DEMO_* 우선, 기존 BINANCE_TESTNET_* 폴백(둘 다 허용). 둘 다 없으면 명시적 오류.
    key = os.environ.get("BINANCE_DEMO_API_KEY") or os.environ.get("BINANCE_TESTNET_API_KEY")
    sec = os.environ.get("BINANCE_DEMO_API_SECRET") or os.environ.get("BINANCE_TESTNET_API_SECRET")
    if not key or not sec:
        raise RuntimeError("API 키 없음 — .env에 BINANCE_DEMO_API_KEY/SECRET (또는 BINANCE_TESTNET_*) 설정 필요")
    ex = ccxt.binance({"apiKey": key, "secret": sec})
    for k in list(ex.urls["api"]):
        if isinstance(ex.urls["api"][k], str):
            ex.urls["api"][k] = ex.urls["api"][k].replace("https://api.binance.com", DEMO_BASE)
    return ex


def fetch_market_filters(exchange, symbol="BTCUSDT"):
    info = exchange.public_get_exchangeinfo({"symbol": symbol})
    fs = {f["filterType"]: f for f in info["symbols"][0]["filters"]}
    notional = fs.get("NOTIONAL") or fs.get("MIN_NOTIONAL") or {}
    lot = fs.get("LOT_SIZE", {})
    min_notional = float(notional.get("minNotional") or notional.get("notional") or 10.0)
    step = float(lot.get("stepSize") or 1e-5)
    min_qty = float(lot.get("minQty") or 1e-5)
    return {"limits": {"cost": {"min": min_notional}, "amount": {"min": min_qty}}, "amount_step": step}


def round_amount(qty, step):
    if not step or step <= 0:
        return qty
    return float(Decimal(str(qty)).quantize(Decimal(str(step)), rounding=ROUND_DOWN))


def _balances(exchange):
    acct = exchange.private_get_account()             # demo는 /api/v3/account 사용(fetch_balance는 sapi라 X)
    b = {x["asset"]: float(x["free"]) for x in acct["balances"]}
    return b.get("USDT", 0.0), b.get(BASE_ASSET, 0.0)


def run_once(live=False, exchange=None, fetch=None, now=None):
    os.makedirs("paper", exist_ok=True)
    lock_file = open(LOCK_PATH, "w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("[demo] 다른 실행 중 — skip"); lock_file.close(); return {"skip": "lock"}
    try:
        exchange = exchange or make_exchange()
        fetch = fetch or fetch_live
        market = fetch_market_filters(exchange)
        if now is None:
            now = pd.Timestamp.now(tz="UTC")

        df = fetch(symbol=SYMBOL, timeframe="4h")
        if _is_stale(df.index[-1], now, "4h"):
            print("[demo] STALE — skip"); return {"skip": "stale"}

        usdt, base_qty = _balances(exchange)
        price = float(df["Close"].iloc[-1])
        equity = usdt + base_qty * price
        state = load_state()

        if state.get("halted"):
            print(f"[demo] HALTED({state.get('reason')}) — 수동 리셋 전 거래 안 함")
            return {"halted": True, "reason": state.get("reason")}

        breach = update_high_water_and_breach(equity, state)
        if breach:                                    # 상태 먼저 저장 → 1회 청산
            state["halted"] = True; state["reason"] = f"drawdown<=-{int(DD_LIMIT*100)}%"
            if live:
                save_state(state)
                if is_holding(base_qty, price, market["limits"]["cost"]["min"] or 10.0):
                    ks_base = {"run_at": pd.Timestamp.now(tz="UTC").isoformat(), "target": 0,
                               "base_qty": base_qty, "price": price, "equity": equity,
                               "bar_iso": "", "dry_run": False}
                    log_order({**ks_base, "action": "kill_switch_intent", "order_id": "",
                               "cost_or_qty": base_qty, "note": "drawdown_breach"})
                    try:
                        o = exchange.create_market_sell_order(
                            SYMBOL, round_amount(base_qty, market.get("amount_step", 1e-5)))
                        log_order({**ks_base, "action": "kill_switch_sell",
                                   "order_id": o.get("id"), "cost_or_qty": base_qty, "note": ""})
                    except Exception:
                        state["reason"] = "liquidation_failed_manual_check"
                        save_state(state)
                        log_order({**ks_base, "action": "order_error", "order_id": "",
                                   "cost_or_qty": base_qty, "note": "kill_switch_sell_failed"})
            else:
                print(f"[demo] KILL-SWITCH would_halt (dry-run) — 상태 저장 생략")
            print("[demo] KILL-SWITCH 발동 — 청산+정지"); return {"halted": True}

        bar_iso = df.index[-1].isoformat()
        target = desired_position(df, KeltnerBreakout)
        res = reconcile(exchange, target, usdt, base_qty, price, market, bar_iso, state, dry_run=not live)
        if live:
            save_state(state)
        print(f"[demo] target={target} action={res.get('action')} equity={equity:.2f} {'(dry-run)' if not live else ''}")
        return {"target": target, **res, "halted": state.get("halted", False)}
    finally:
        fcntl.flock(lock_file, fcntl.LOCK_UN); lock_file.close()


if __name__ == "__main__":
    load_env()
    live = "--live" in sys.argv
    if live:                                          # --live 전 demo 연결/키 검증
        ex = make_exchange()
        ex.private_get_account()                      # 실패 시 예외로 즉시 중단(주문 전)
        print("[demo] demo 계정 인증 확인됨 — LIVE 모드")
    run_once(live=live)
