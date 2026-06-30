# Phase 4b — 섀도우 cron 확장 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** 기존 섀도우 cron(`paper_trade.py`)에 (1) sentiment 신호 나란히 로깅, (2) 라이브 펀딩 기록기를 추가한다. 여전히 주문 없음(섀도우).

**Architecture:** `paper_trade.py`만 확장. 전략은 use_sentiment를 이미 보유(수정 안 함). F&G는 `sentiment.py`(7b-v2), 펀딩은 ccxt. 각 구간 독립 실패-안전.

**Tech Stack:** Python 3.13, pandas, ccxt, pytest. `.venv/bin/python -m pytest`.

## Global Constraints
- `paper_trade.py`와 `tests/test_paper_trade.py`만 수정. 하네스·전략 파일 수정 금지.
- 주문 실행 없음(섀도우). 기존 `signals.csv` 스키마·멱등키(strategy,symbol,timeframe,bar) 유지 — sentiment 변형은 **이름 분리**(regime_sentiment/keltner_sentiment)로 구분.
- sentiment 변형은 Regime/Keltner만(use_sentiment 배선된 2종). strategy_params에 use_sentiment=True 기록.
- 펀딩 dedup 키 = **(symbol, funding_time)**. funding_time은 `fundingTimestamp`(없으면 info의 nextFundingTime), ISO string.
- F&G/펀딩 fetch 실패는 graceful(신호 로깅 안 깨짐). sentiment 컬럼은 항상 numeric float(실패 시 NaN=off).
- 테스트는 synthetic만(네트워크 비의존; 라이브 fetch_fng/fetch_funding_rate는 유닛테스트 제외).

---

### Task 1: sentiment 신호 나란히 로깅

**Files:**
- Modify: `paper_trade.py`
- Test: `tests/test_paper_trade.py` (기존 — 보존하고 추가)

**Interfaces:**
- Consumes: `from sentiment import fetch_fng, attach_fng`; 전략 `use_sentiment` 클래스 속성.
- Produces: `STRATEGIES: dict[str, tuple[type, dict]]`; `desired_position(df, strategy, **params)`; `_params_repr(strategy, params=None)`.

- [ ] **Step 1: Write the failing test** — `tests/test_paper_trade.py`에 추가

```python
def test_desired_position_sentiment_blocks_on_greed():
    # 상승 추세 + 전 구간 극탐욕 → use_sentiment=True면 현금(0), False면 보유(1)
    import pandas as pd
    from paper_trade import desired_position, _to_live_df
    n = 320
    close = [100.0] * 220 + [100.0 + i for i in range(1, n - 220 + 1)]
    rows = [[i * 14400000, c, c * 1.01, c * 0.99, c, 1000.0] for i, c in enumerate(close)]
    df = _to_live_df(rows)
    df["sentiment"] = 90.0                       # 전 구간 극탐욕(float)
    from strategies.regime_filter import RegimeFilter
    assert desired_position(df, RegimeFilter, use_sentiment=True) == 0
    assert desired_position(df, RegimeFilter, use_sentiment=False) == 1


def test_params_repr_includes_use_sentiment():
    from paper_trade import _params_repr
    from strategies.regime_filter import RegimeFilter
    r = _params_repr(RegimeFilter, {"use_sentiment": True})
    assert "use_sentiment=True" in r
    assert "sentiment_threshold=75" in r          # 클래스 속성(int)도 포함


def test_strategies_has_sentiment_variants():
    from paper_trade import STRATEGIES
    assert "regime_sentiment" in STRATEGIES and "keltner_sentiment" in STRATEGIES
    assert STRATEGIES["regime_sentiment"][1] == {"use_sentiment": True}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_paper_trade.py -k "sentiment or params_repr" -v`
Expected: FAIL (STRATEGIES는 tuple 아님 / desired_position params 미지원 / _params_repr 시그니처).

- [ ] **Step 3: Implement** — `paper_trade.py` 수정

import에 추가:
```python
from sentiment import fetch_fng, attach_fng
```
`STRATEGIES`를 `name -> (strategy, params)`로:
```python
STRATEGIES = {
    "keltner": (KeltnerBreakout, {}),
    "regime": (RegimeFilter, {}),
    "donchian": (DonchianBreakout, {}),
    "sma_stop": (SmaCrossWithStop, {}),
    "keltner_sentiment": (KeltnerBreakout, {"use_sentiment": True}),
    "regime_sentiment": (RegimeFilter, {"use_sentiment": True}),
}
```
`desired_position`에 params 전달:
```python
def desired_position(df, strategy, **params):
    _, stats = run_backtest(df, strategy, **params)
    return int(stats._strategy.position.size > 0)
```
`_params_repr`에 전달 params 병합(use_sentiment 같은 bool도 기록):
```python
def _params_repr(strategy, params=None):
    items = {k: v for k, v in vars(strategy).items()
             if not k.startswith("_") and isinstance(v, (int, float)) and not isinstance(v, bool)}
    if params:
        items.update(params)
    return ",".join(f"{k}={v}" for k, v in sorted(items.items(), key=lambda kv: kv[0]))
```
`_append_signals` 루프를 `(strat, params)` 언팩으로:
```python
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
```
`run_once`에서 F&G 부착(독립 실패-안전, sentiment 항상 float):
```python
        df = fetch_live(symbol=symbol, timeframe=timeframe, **kwargs)
        try:
            df = attach_fng(df, fetch_fng())               # D값 D+1부터(t-1 lag)
        except Exception as e:
            print(f"[paper] F&G fetch 실패 — sentiment off로 진행: {e}")
            df = df.copy()
            df["sentiment"] = float("nan")                 # numeric NaN = 필터 off
        return _append_signals(df, symbol=symbol, timeframe=timeframe, dry_run=dry_run)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_paper_trade.py -v`
Expected: PASS (기존 + 신규). 전체 회귀: `.venv/bin/python -m pytest -q` → 모두 PASS, 출력 pristine.

- [ ] **Step 5: Commit**

```bash
git add paper_trade.py tests/test_paper_trade.py
git commit -m "feat(paper): sentiment 신호 나란히 로깅 (regime/keltner_sentiment 변형 + 라이브 F&G 부착, graceful)"
```

---

### Task 2: 라이브 펀딩 기록기

**Files:**
- Modify: `paper_trade.py`
- Test: `tests/test_paper_trade.py`

**Interfaces:**
- Consumes: ccxt exchange `fetch_funding_rate(symbol)`.
- Produces: `record_funding(symbols=("BTC/USDT:USDT","ETH/USDT:USDT"), csv_path="paper/funding.csv", exchange=None, now=None, dry_run=False) -> list[dict]`.

- [ ] **Step 1: Write the failing test** — `tests/test_paper_trade.py`에 추가 (네트워크 없이 fake exchange 주입)

```python
def test_record_funding_dedups_per_symbol_and_time(tmp_path):
    import pandas as pd
    from paper_trade import record_funding

    class FakeEx:
        def fetch_funding_rate(self, symbol):
            return {"symbol": symbol, "fundingRate": 0.0001, "fundingTimestamp": 1700000000000,
                    "markPrice": 50000.0, "indexPrice": 50010.0, "timestamp": 1700000123000}

    csv = str(tmp_path / "funding.csv")
    now = pd.Timestamp("2026-06-30T00:00:00Z")
    r1 = record_funding(symbols=("BTC/USDT:USDT", "ETH/USDT:USDT"), csv_path=csv, exchange=FakeEx(), now=now)
    assert len(r1) == 2                                   # 두 심볼 기록
    r2 = record_funding(symbols=("BTC/USDT:USDT", "ETH/USDT:USDT"), csv_path=csv, exchange=FakeEx(), now=now)
    assert len(r2) == 0                                   # 같은 (symbol, funding_time) → 멱등 skip
    d = pd.read_csv(csv)
    assert set(d["symbol"]) == {"BTC/USDT:USDT", "ETH/USDT:USDT"}
    assert "funding_time" in d.columns and "funding_rate" in d.columns
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_paper_trade.py -k record_funding -v`
Expected: FAIL — `ImportError: cannot import name 'record_funding'`.

- [ ] **Step 3: Implement** — `paper_trade.py`에 추가

```python
import ccxt  # 이미 import됨

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
        funding_time = pd.to_datetime(int(ft_ms), unit="ms", utc=True).isoformat() if ft_ms else ""
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
```
`run_once`에서 신호 로깅 뒤 **독립 호출**(실패해도 신호 영향 없음):
```python
        result = _append_signals(df, symbol=symbol, timeframe=timeframe, dry_run=dry_run)
        try:
            record_funding(dry_run=dry_run)
        except Exception as e:
            print(f"[funding] 기록 실패(무시): {e}")
        return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_paper_trade.py -v`
Expected: PASS. 전체 회귀: `.venv/bin/python -m pytest -q` → 모두 PASS, pristine.

- [ ] **Step 5: Commit**

```bash
git add paper_trade.py tests/test_paper_trade.py
git commit -m "feat(paper): 라이브 펀딩 기록기 (paper/funding.csv, (symbol,funding_time) 멱등, graceful)"
```
