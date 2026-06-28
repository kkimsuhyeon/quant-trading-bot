import os
import sys
import fcntl
from datetime import timedelta
import pandas as pd
import ccxt
from backtest import run_backtest, _to_backtesting_format
from fetch import clean_ohlcv
from strategies.keltner_breakout import KeltnerBreakout
from strategies.regime_filter import RegimeFilter
from strategies.donchian_breakout import DonchianBreakout
from strategies.sma_cross_stop import SmaCrossWithStop

STRATEGIES = {
    "keltner": KeltnerBreakout,
    "regime": RegimeFilter,
    "donchian": DonchianBreakout,
    "sma_stop": SmaCrossWithStop,
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


def desired_position(df, strategy):
    _, stats = run_backtest(df, strategy)
    return int(stats._strategy.position.size > 0)


def _params_repr(strategy):
    items = {k: v for k, v in vars(strategy).items()
             if not k.startswith("_") and isinstance(v, (int, float)) and not isinstance(v, bool)}
    return ",".join(f"{k}={v}" for k, v in sorted(items.items()))


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
    for name, strat in strategies.items():
        if (name, symbol, timeframe, bar_iso) in existing:
            continue
        rows.append({
            "run_at": now.isoformat(), "symbol": symbol, "timeframe": timeframe,
            "strategy": name, "signal_bar_time": bar_iso,
            "signal_bar_close": float(df["Close"].iloc[-1]),
            "desired_position": desired_position(df, strat),
            "source_rows": len(df), "lookback_bars": len(df),
            "strategy_params": _params_repr(strat),
        })
    summary = ", ".join(f"{r['strategy']}={r['desired_position']}" for r in rows) or "(중복 skip)"
    print(f"[paper] {bar_iso} close={float(df['Close'].iloc[-1]):.2f} | {summary}")
    if rows and not dry_run:
        os.makedirs(os.path.dirname(csv_path) or ".", exist_ok=True)
        header = not os.path.exists(csv_path)
        pd.DataFrame(rows, columns=COLUMNS).to_csv(csv_path, mode="a", header=header, index=False)
    return rows


def run_once(dry_run=False, **kwargs):
    os.makedirs("paper", exist_ok=True)
    lock_file = open(LOCK_PATH, "w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("[paper] 다른 실행 진행 중 — skip")
        lock_file.close()
        return []
    try:
        return _append_signals(fetch_live(**kwargs), dry_run=dry_run)
    finally:
        fcntl.flock(lock_file, fcntl.LOCK_UN)
        lock_file.close()


if __name__ == "__main__":
    run_once(dry_run="--dry-run" in sys.argv)
