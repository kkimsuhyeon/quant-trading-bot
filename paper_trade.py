import os
import sys
import fcntl
from datetime import timedelta
import pandas as pd
import ccxt
from backtest import run_backtest, _to_backtesting_format
from fetch import clean_ohlcv
from sentiment import fetch_fng, attach_fng
from strategies.keltner_breakout import KeltnerBreakout
from strategies.regime_filter import RegimeFilter
from strategies.donchian_breakout import DonchianBreakout
from strategies.sma_cross_stop import SmaCrossWithStop

STRATEGIES = {
    "keltner": (KeltnerBreakout, {}),
    "regime": (RegimeFilter, {}),
    "donchian": (DonchianBreakout, {}),
    "sma_stop": (SmaCrossWithStop, {}),
    "keltner_sentiment": (KeltnerBreakout, {"use_sentiment": True}),
    "regime_sentiment": (RegimeFilter, {"use_sentiment": True}),
}
SIGNALS_CSV = "paper/signals.csv"
LOCK_PATH = "paper/.lock"
COLUMNS = ["run_at", "symbol", "timeframe", "strategy", "signal_bar_time",
           "signal_bar_close", "desired_position", "source_rows", "lookback_bars", "strategy_params"]


def _to_live_df(rows):
    df = clean_ohlcv(rows)              # index=timestamp, ohlcv(+sentiment)
    if len(df) > 0:
        df = df.iloc[:-1]              # 마지막 미완성봉 제거 (fetch.py 규칙)
    return _to_backtesting_format(df)


def fetch_live(symbol="BTC/USDT", timeframe="4h", limit=1000, exchange=None):
    exchange = exchange or ccxt.binance()
    rows = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
    return _to_live_df(rows)


def desired_position(df, strategy, **params):
    _, stats = run_backtest(df, strategy, **params)
    return int(stats._strategy.position.size > 0)


def _params_repr(strategy, params=None):
    items = {k: v for k, v in vars(strategy).items()
             if not k.startswith("_") and isinstance(v, (int, float)) and not isinstance(v, bool)}
    if params:
        items.update(params)
    return ",".join(f"{k}={v}" for k, v in sorted(items.items(), key=lambda kv: kv[0]))


def _is_stale(candle_time, now, timeframe="4h", max_bars=2):
    hours = {"1h": 1, "4h": 4}[timeframe]
    return (now - candle_time) > timedelta(hours=hours * (max_bars + 1))


def _existing_keys(csv_path):
    if not os.path.exists(csv_path):
        return set()
    d = pd.read_csv(csv_path, dtype=str)
    return set(zip(d["strategy"], d["symbol"], d["timeframe"], d["signal_bar_time"]))


def _append_signals(df, csv_path=SIGNALS_CSV, now=None, symbol="BTC/USDT",
                    timeframe="4h", strategies=STRATEGIES, dry_run=False):
    if now is None:
        now = pd.Timestamp.now(tz="UTC")
    candle_time = df.index[-1]
    if _is_stale(candle_time, now, timeframe):
        print(f"[paper] STALE: 마지막봉 {candle_time} vs now {now} — skip")
        return []
    bar_iso = candle_time.isoformat()
    existing = _existing_keys(csv_path)
    rows = []
    for name, (strat, params) in strategies.items():
        if (name, symbol, timeframe, bar_iso) in existing:
            continue
        rows.append({
            "run_at": now.isoformat(), "symbol": symbol, "timeframe": timeframe,
            "strategy": name, "signal_bar_time": bar_iso,
            "signal_bar_close": float(df["Close"].iloc[-1]),
            "desired_position": desired_position(df, strat, **params),
            "source_rows": len(df), "lookback_bars": len(df),
            "strategy_params": _params_repr(strat, params),
        })
    summary = ", ".join(f"{r['strategy']}={r['desired_position']}" for r in rows) or "(중복 skip)"
    print(f"[paper] {bar_iso} close={float(df['Close'].iloc[-1]):.2f} | {summary}")
    if rows and not dry_run:
        os.makedirs(os.path.dirname(csv_path) or ".", exist_ok=True)
        header = not os.path.exists(csv_path)
        pd.DataFrame(rows, columns=COLUMNS).to_csv(csv_path, mode="a", header=header, index=False)
    return rows


FUNDING_CSV = "paper/funding.csv"
FUNDING_COLUMNS = ["run_at", "exchange", "symbol", "funding_time", "funding_rate",
                   "mark_price", "index_price", "raw_timestamp"]


def _funding_keys(csv_path):
    if not os.path.exists(csv_path):
        return set()
    d = pd.read_csv(csv_path, dtype=str)
    return set(zip(d["symbol"], d["funding_time"]))


def record_funding(symbols=("BTC/USDT:USDT", "ETH/USDT:USDT"), csv_path=FUNDING_CSV,
                   exchange=None, now=None, dry_run=False):
    exchange = exchange or ccxt.binance()
    if now is None:
        now = pd.Timestamp.now(tz="UTC")
    existing = _funding_keys(csv_path)
    rows = []
    for sym in symbols:
        try:
            fr = exchange.fetch_funding_rate(sym)
        except Exception as e:
            print(f"[funding] {sym} fetch 실패 — skip: {e}")
            continue
        ft_ms = fr.get("fundingTimestamp") or (fr.get("info") or {}).get("nextFundingTime")
        if not ft_ms:                                   # 정산시각 없으면 dedup키 불안정 → 기록 skip(오염 방지)
            print(f"[funding] {sym} funding_time 없음 — skip")
            continue
        funding_time = pd.to_datetime(int(ft_ms), unit="ms", utc=True).isoformat()
        if (sym, funding_time) in existing:
            continue
        rows.append({
            "run_at": now.isoformat(), "exchange": "binance", "symbol": sym,
            "funding_time": funding_time, "funding_rate": fr.get("fundingRate"),
            "mark_price": fr.get("markPrice"), "index_price": fr.get("indexPrice"),
            "raw_timestamp": fr.get("timestamp"),
        })
    if rows and not dry_run:
        os.makedirs(os.path.dirname(csv_path) or ".", exist_ok=True)
        header = not os.path.exists(csv_path)
        pd.DataFrame(rows, columns=FUNDING_COLUMNS).to_csv(csv_path, mode="a", header=header, index=False)
    print(f"[funding] {len(rows)} 기록" + (" (dry-run)" if dry_run else ""))
    return rows


def run_once(dry_run=False, symbol="BTC/USDT", timeframe="4h", **kwargs):
    os.makedirs("paper", exist_ok=True)
    lock_file = open(LOCK_PATH, "w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("[paper] 다른 실행 진행 중 — skip")
        lock_file.close()
        return []
    try:
        df = fetch_live(symbol=symbol, timeframe=timeframe, **kwargs)
        try:
            df = attach_fng(df, fetch_fng())               # D값 D+1부터(t-1 lag)
        except Exception as e:
            print(f"[paper] F&G fetch 실패 — sentiment off로 진행: {e}")
            df = df.copy()
            df["sentiment"] = float("nan")                 # numeric NaN = 필터 off
        result = _append_signals(df, symbol=symbol, timeframe=timeframe, dry_run=dry_run)
        try:
            record_funding(dry_run=dry_run)
        except Exception as e:
            print(f"[funding] 기록 실패(무시): {e}")
        return result
    finally:
        fcntl.flock(lock_file, fcntl.LOCK_UN)
        lock_file.close()


if __name__ == "__main__":
    run_once(dry_run="--dry-run" in sys.argv)
