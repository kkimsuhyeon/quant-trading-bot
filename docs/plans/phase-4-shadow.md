# Phase 4 1단계 섀도우 — 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`).

**Goal:** 검증된 4전략을 라이브 BTC/USDT 4h에 전진 적용해 "지금 들고 있을 포지션"을 멱등 로그로 기록하고(`paper_trade.py`), 오프라인으로 백테스트와 비교(`paper_report.py`).

**Architecture:** 하네스급 신규 도구. `run_backtest`로 전략 시그널 재사용(재구현 X). 네트워크/시간 의존을 함수 인자로 주입해 오프라인 테스트. append-only long-format CSV가 단일 진실원천.

**Tech Stack:** Python 3.13, ccxt(공개), pandas(>=2,<3), Backtesting.py, pytest, fcntl(파일락).

설계: `docs/design/phase-4-shadow.md`

## Global Constraints
- `.venv` Python 3.13, `pandas>=2,<3`. 테스트 `.venv/bin/python -m pytest`.
- **하네스/전략 미수정**: `backtest.py`, `strategies/*` 불변. 재사용만.
- **테스트는 네트워크/실시간 비의존**: ccxt 호출·현재시각을 인자로 주입(`exchange`, `df`, `now`). `data/` 의존 금지(synthetic).
- 포지션 판정: `int(stats._strategy.position.size > 0)` (검증됨; private API라 테스트 필수).
- 로그 컬럼(순서 고정): `run_at, symbol, timeframe, strategy, signal_bar_time, signal_bar_close, desired_position, source_rows, lookback_bars, strategy_params`.
- 멱등키 = (`strategy`, `symbol`, `timeframe`, `signal_bar_time`); ISO8601 문자열로 저장·비교.
- `paper/`는 `.gitignore`.

---

### Task 1: `paper_trade.py` 코어 — `_to_live_df` / `desired_position` / `fetch_live` / `_params_repr`

**Files:**
- Create: `paper_trade.py`
- Modify: `.gitignore` (추가: `paper/`)
- Test: `tests/test_paper_trade.py`

**Interfaces:**
- Consumes: `backtest.run_backtest`, `backtest._to_backtesting_format`, `fetch.clean_ohlcv`; 전략 4개.
- Produces:
  - `_to_live_df(rows) -> DataFrame` (OHLC 포맷, 마지막 미완성봉 제거)
  - `desired_position(df, strategy) -> int` (1/0)
  - `fetch_live(symbol="BTC/USDT", timeframe="4h", limit=1000, exchange=None) -> DataFrame`
  - `_params_repr(strategy) -> str`
  - `STRATEGIES: dict[str, type]`, `COLUMNS: list[str]`, `SIGNALS_CSV`, `LOCK_PATH`

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_paper_trade.py`
```python
import numpy as np
import pandas as pd
from paper_trade import _to_live_df, desired_position, _params_repr, STRATEGIES
from strategies.regime_filter import RegimeFilter


def _raw_rows(n=400):
    # ccxt 형식 raw rows: [ts_ms, o, h, l, c, v]. 마지막 200봉 상승(끝 롱 유발).
    closes = np.concatenate([np.linspace(100, 80, 200), np.linspace(80, 160, 200)])
    base = 1_600_000_000_000
    return [[base + i * 4 * 3600 * 1000, c, c * 1.01, c * 0.99, c, 1000.0]
            for i, c in enumerate(closes[:n])]


def test_to_live_df_drops_incomplete_and_formats():
    rows = _raw_rows(10)
    out = _to_live_df(rows)
    assert len(out) == 9                      # 마지막 미완성봉 제거
    assert {"Open", "High", "Low", "Close", "Volume"} <= set(out.columns)


def test_desired_position_long_when_uptrend_end():
    df = _to_live_df(_raw_rows(400))          # 끝이 상승 → SMA200 위 → 롱
    assert desired_position(df, RegimeFilter) == 1


def test_desired_position_flat_when_downtrend_end():
    closes = np.linspace(200, 80, 400)        # 단조 하락 → 끝 현금
    base = 1_600_000_000_000
    rows = [[base + i * 4 * 3600 * 1000, c, c * 1.01, c * 0.99, c, 1000.0]
            for i, c in enumerate(closes)]
    df = _to_live_df(rows)
    assert desired_position(df, RegimeFilter) == 0


def test_params_repr_excludes_sentiment():
    r = _params_repr(RegimeFilter)
    assert "sma_n=200" in r
    assert "use_sentiment" not in r


def test_strategies_has_four():
    assert set(STRATEGIES) == {"keltner", "regime", "donchian", "sma_stop"}
```

- [ ] **Step 2: 실패 확인**
Run: `.venv/bin/python -m pytest tests/test_paper_trade.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'paper_trade'`

- [ ] **Step 3: 구현** — `paper_trade.py`
```python
import os
import sys
import fcntl
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
```
(Task 2에서 `_is_stale`, `_append_signals`, `run_once`, `__main__` 추가.)

- [ ] **Step 4: `.gitignore`에 `paper/` 추가** (기존 줄 보존, 한 줄 append)

- [ ] **Step 5: 통과 확인**
Run: `.venv/bin/python -m pytest tests/test_paper_trade.py -v`
Expected: PASS (5 passed)

- [ ] **Step 6: 커밋**
```bash
git add paper_trade.py tests/test_paper_trade.py .gitignore
git commit -m "feat(paper): 섀도우 코어 (fetch_live/desired_position/_to_live_df)"
```

---

### Task 2: `paper_trade.py` — `_is_stale` / `_append_signals` / `run_once`

**Files:**
- Modify: `paper_trade.py` (함수 추가)
- Test: `tests/test_paper_trade.py` (추가)

**Interfaces:**
- Consumes: Task 1의 `desired_position`, `_params_repr`, `STRATEGIES`, `COLUMNS`, `fetch_live`.
- Produces:
  - `_is_stale(candle_time, now, timeframe="4h", max_bars=2) -> bool`
  - `_append_signals(df, csv_path=SIGNALS_CSV, now=None, symbol="BTC/USDT", timeframe="4h", strategies=STRATEGIES, dry_run=False) -> list[dict]`
  - `run_once(dry_run=False, **kwargs) -> list[dict]`

- [ ] **Step 1: 실패 테스트 작성** (`tests/test_paper_trade.py` 하단에 추가)
```python
import os
from paper_trade import _is_stale, _append_signals


def test_is_stale():
    now = pd.Timestamp("2026-01-02 00:00:00", tz="UTC")
    assert _is_stale(pd.Timestamp("2026-01-01 00:00:00", tz="UTC"), now) is True   # 24h 전 = stale
    assert _is_stale(pd.Timestamp("2026-01-01 20:00:00", tz="UTC"), now) is False  # 4h 전 = 정상


def test_append_signals_schema_and_idempotency(tmp_path):
    df = _to_live_df(_raw_rows(400))
    now = pd.Timestamp("2026-01-01 00:00:00", tz="UTC")
    # df 마지막봉을 now 근처로 맞춰 stale 회피: now를 df 마지막봉 +4h로 설정
    now = df.index[-1] + pd.Timedelta(hours=4)
    csv = str(tmp_path / "signals.csv")
    rows1 = _append_signals(df, csv_path=csv, now=now)
    assert len(rows1) == 4                                  # 4전략
    saved = pd.read_csv(csv)
    assert list(saved.columns) == COLUMNS_EXPECTED
    assert set(saved["strategy"]) == {"keltner", "regime", "donchian", "sma_stop"}
    rows2 = _append_signals(df, csv_path=csv, now=now)      # 같은 봉 재실행
    assert rows2 == []                                     # 멱등: 중복 skip
    assert len(pd.read_csv(csv)) == 4                       # 행 수 그대로


def test_append_signals_dry_run_writes_nothing(tmp_path):
    df = _to_live_df(_raw_rows(400))
    now = df.index[-1] + pd.Timedelta(hours=4)
    csv = str(tmp_path / "signals.csv")
    rows = _append_signals(df, csv_path=csv, now=now, dry_run=True)
    assert len(rows) == 4
    assert not os.path.exists(csv)


def test_append_signals_stale_skips(tmp_path):
    df = _to_live_df(_raw_rows(400))
    now = df.index[-1] + pd.Timedelta(days=5)              # 너무 오래됨
    csv = str(tmp_path / "signals.csv")
    assert _append_signals(df, csv_path=csv, now=now) == []
    assert not os.path.exists(csv)
```
테스트 상단에 `from paper_trade import COLUMNS as COLUMNS_EXPECTED` 추가(혹은 직접 리스트 비교).

- [ ] **Step 2: 실패 확인**
Run: `.venv/bin/python -m pytest tests/test_paper_trade.py -v`
Expected: FAIL — `ImportError: cannot import name '_is_stale'`

- [ ] **Step 3: 구현** (`paper_trade.py`에 추가)
```python
def _is_stale(candle_time, now, timeframe="4h", max_bars=2):
    hours = {"1h": 1, "4h": 4}[timeframe]
    return (now - candle_time) > pd.Timedelta(hours=hours * (max_bars + 1))


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
        return []
    try:
        return _append_signals(fetch_live(**kwargs), dry_run=dry_run)
    finally:
        fcntl.flock(lock_file, fcntl.LOCK_UN)
        lock_file.close()


if __name__ == "__main__":
    run_once(dry_run="--dry-run" in sys.argv)
```

- [ ] **Step 4: 통과 확인**
Run: `.venv/bin/python -m pytest tests/test_paper_trade.py -v`
Expected: PASS (9 passed)
이어서 전체: `.venv/bin/python -m pytest -q` → 기존 30 + 신규 9 = 39 passed.

- [ ] **Step 5: 커밋**
```bash
git add paper_trade.py tests/test_paper_trade.py
git commit -m "feat(paper): run_once (멱등 append/staleness/file lock/dry-run)"
```

---

### Task 3: `paper_report.py` — 오프라인 분석 (proxy 곡선 + 시그널 비교)

**Files:**
- Create: `paper_report.py`
- Test: `tests/test_paper_report.py`

**Interfaces:**
- Consumes: `paper_trade.COLUMNS`, pandas.
- Produces:
  - `load_signals(csv_path) -> DataFrame` (멱등키 중복 시 마지막만, signal_bar_time 정렬)
  - `proxy_equity(sig, strategy, cash=10_000, commission=0.001) -> DataFrame` (전진 페이퍼 수익곡선: 0→1 진입(종가 proxy), 1→0 청산, 수수료 반영)

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_paper_report.py`
```python
import pandas as pd
from paper_report import load_signals, proxy_equity


def _signals_csv(tmp_path):
    # 한 전략(regime)에 대해 4개 봉: 0,1,1,0 (한 번 진입했다가 청산)
    times = pd.date_range("2026-01-01", periods=4, freq="4h", tz="UTC")
    rows = []
    for t, close, pos in zip(times, [100, 110, 120, 90], [0, 1, 1, 0]):
        rows.append({"run_at": t.isoformat(), "symbol": "BTC/USDT", "timeframe": "4h",
                     "strategy": "regime", "signal_bar_time": t.isoformat(),
                     "signal_bar_close": close, "desired_position": pos,
                     "source_rows": 1000, "lookback_bars": 1000, "strategy_params": "sma_n=200"})
    p = str(tmp_path / "signals.csv")
    pd.DataFrame(rows).to_csv(p, index=False)
    return p


def test_load_signals_dedups_last(tmp_path):
    p = _signals_csv(tmp_path)
    # 마지막 봉 중복 추가(다른 run_at)
    extra = pd.read_csv(p).tail(1)
    extra.to_csv(p, mode="a", header=False, index=False)
    sig = load_signals(p)
    assert len(sig[sig["strategy"] == "regime"]) == 4        # 중복 제거


def test_proxy_equity_realizes_pnl(tmp_path):
    sig = load_signals(_signals_csv(tmp_path))
    eq = proxy_equity(sig, "regime")
    # 110에 진입 → 90에 청산: 손실. 최종 자본 < 시작.
    assert eq["equity"].iloc[-1] < 10_000
    assert "equity" in eq.columns
```

- [ ] **Step 2: 실패 확인**
Run: `.venv/bin/python -m pytest tests/test_paper_report.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'paper_report'`

- [ ] **Step 3: 구현** — `paper_report.py`
```python
import pandas as pd


def load_signals(csv_path):
    df = pd.read_csv(csv_path)
    df = df.sort_values("signal_bar_time")
    df = df.drop_duplicates(["strategy", "symbol", "timeframe", "signal_bar_time"], keep="last")
    return df.reset_index(drop=True)


def proxy_equity(sig, strategy, cash=10_000, commission=0.001):
    s = sig[sig["strategy"] == strategy].sort_values("signal_bar_time").reset_index(drop=True)
    equity = cash
    units = 0.0
    prev_pos = 0
    out = []
    for _, r in s.iterrows():
        price = float(r["signal_bar_close"])
        pos = int(r["desired_position"])
        if prev_pos == 0 and pos == 1:                 # 진입(종가 proxy 체결)
            spend = equity * (1 - commission)
            units = spend / price
            equity = 0.0
        elif prev_pos == 1 and pos == 0:               # 청산
            equity = units * price * (1 - commission)
            units = 0.0
        mark = equity + units * price                  # mark-to-market
        out.append({"signal_bar_time": r["signal_bar_time"], "position": pos, "equity": mark})
        prev_pos = pos
    return pd.DataFrame(out)
```

- [ ] **Step 4: 통과 확인**
Run: `.venv/bin/python -m pytest tests/test_paper_report.py -v`
Expected: PASS (2 passed)
전체: `.venv/bin/python -m pytest -q` → 41 passed.

- [ ] **Step 5: 커밋**
```bash
git add paper_report.py tests/test_paper_report.py
git commit -m "feat(paper): paper_report (proxy 수익곡선 + 시그널 로그 로딩)"
```

---

## 컨트롤러 후속 (구현 후)
- `paper_trade.py --dry-run` 1회 실제 실행해 라이브 fetch + 4전략 현재 포지션 출력 확인(sanity).
- cron 셋업 안내를 설계 문서/README에 명시(설계 문서의 cron 블록).
- 노트북/결과는 데이터가 쌓인 뒤(수 주) — 지금은 도구만.
- final 리뷰 + Codex 크로스리뷰 → merge/push → 사용자 보고(+ cron 등록은 사용자 안내).
