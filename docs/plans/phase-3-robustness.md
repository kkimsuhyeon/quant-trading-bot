# Phase 3 견고성 검증 — 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 후보 전략(Donchian/SMA 4h)의 견고성을 검증할 재사용 도구 모듈 `robustness.py`를 TDD로 만든다.

**Architecture:** `backtest.py`처럼 고정된 하네스급 도구. `backtest.run_backtest`를 재사용하고 전략/하네스는 수정하지 않는다. 순수 데이터 분할 함수(Task 1) + 백테스트 구동 함수(Task 2)로 나눈다. 실데이터 분석·결론·노트북은 모듈 완성 후 컨트롤러가 수행(계획 범위 밖).

**Tech Stack:** Python 3.13, pandas(>=2,<3), Backtesting.py(FractionalBacktest), pytest.

설계 상세: `docs/design/phase-3-robustness.md`

## Global Constraints

- Python 3.13 + `.venv`. 테스트 실행은 `python -m pytest` (venv 파이썬).
- 의존성 `pandas>=2,<3` 고정 (FractionalBacktest가 pandas 3.0 Copy-on-Write와 비호환).
- **하네스/전략 미수정**: `backtest.py`, `strategies/*` 를 건드리지 않는다. `robustness.py`는 `run_backtest`를 호출만 한다.
- **테스트는 synthetic 데이터만 사용**, `data/*.parquet` 에 의존 금지 (gitignore라 CI/클론 환경에 없음). 기존 테스트(`tests/test_trend_strategies.py`)의 사인파 패턴을 따른다.
- 지표 키는 Backtesting.py stats 인덱스명 그대로: `"Return [%]"`, `"Buy & Hold Return [%]"`, `"Sharpe Ratio"`, `"Max. Drawdown [%]"`, `"Win Rate [%]"`, `"# Trades"`.
- 모듈은 범용·고정. 전략 특화 로직(fast<slow 필터 등)을 모듈에 넣지 않는다.

---

### Task 1: 데이터 분할 헬퍼 (`train_test_split`, `time_segments`, `buy_hold`)

**Files:**
- Create: `robustness.py`
- Test: `tests/test_robustness.py`

**Interfaces:**
- Consumes: 없음 (pandas만 사용, 백테스트 비의존)
- Produces:
  - `train_test_split(df, train_frac=0.7) -> (train_df, test_df)` — 시간순 분할
  - `time_segments(df, k=5) -> list[DataFrame]` — 연속 K등분
  - `buy_hold(df) -> dict` — `{"Return [%]": float, "Max. Drawdown [%]": float}` (종가 기준)
  - `METRIC_KEYS: list[str]` — 위 Global Constraints의 지표 키 리스트

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_robustness.py`:
```python
import numpy as np
import pandas as pd
from robustness import train_test_split, time_segments, buy_hold


def _price_df(n=100):
    idx = pd.date_range("2020-01-01", periods=n, freq="4h", tz="UTC")
    close = pd.Series(np.linspace(100, 200, n), index=idx)   # 단조 상승
    return pd.DataFrame({"Open": close, "High": close * 1.01, "Low": close * 0.99,
                         "Close": close, "Volume": 1000.0}, index=idx)


def test_train_test_split_ratio_and_order():
    df = _price_df(100)
    train, test = train_test_split(df, train_frac=0.7)
    assert len(train) == 70
    assert len(test) == 30
    assert len(train) + len(test) == len(df)        # 행 보존
    assert train.index[-1] < test.index[0]          # 시간순(누수 없음)


def test_time_segments_contiguous_cover():
    df = _price_df(100)
    segs = time_segments(df, k=5)
    assert len(segs) == 5
    assert sum(len(s) for s in segs) == len(df)     # 전부 커버, 중복 없음
    for a, b in zip(segs, segs[1:]):
        assert a.index[-1] < b.index[0]             # 연속


def test_buy_hold_return_and_mdd_monotone():
    df = _price_df(100)                              # 100 -> 200
    bh = buy_hold(df)
    assert round(bh["Return [%]"], 2) == 100.0
    assert round(bh["Max. Drawdown [%]"], 4) == 0.0


def test_buy_hold_drawdown_on_dip():
    idx = pd.date_range("2020-01-01", periods=3, freq="4h", tz="UTC")
    close = pd.Series([100.0, 50.0, 75.0], index=idx)   # 최저점 -50%
    df = pd.DataFrame({"Open": close, "High": close, "Low": close,
                       "Close": close, "Volume": 1000.0}, index=idx)
    assert round(buy_hold(df)["Max. Drawdown [%]"], 2) == -50.0
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_robustness.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'robustness'`

- [ ] **Step 3: 최소 구현**

`robustness.py`:
```python
import pandas as pd

METRIC_KEYS = ["Return [%]", "Buy & Hold Return [%]", "Sharpe Ratio",
               "Max. Drawdown [%]", "Win Rate [%]", "# Trades"]


def train_test_split(df, train_frac=0.7):
    n = int(len(df) * train_frac)
    return df.iloc[:n], df.iloc[n:]


def time_segments(df, k=5):
    bounds = [len(df) * i // k for i in range(k + 1)]
    return [df.iloc[bounds[i]:bounds[i + 1]] for i in range(k)]


def buy_hold(df):
    close = df["Close"]
    ret = (close.iloc[-1] / close.iloc[0] - 1) * 100
    mdd = (close / close.cummax() - 1).min() * 100
    return {"Return [%]": ret, "Max. Drawdown [%]": mdd}
```
(`itertools` / `backtest.run_backtest` import는 실제 사용하는 Task 2에서 추가한다 — 미사용 import 방지.)

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_robustness.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: 커밋**

```bash
git add robustness.py tests/test_robustness.py
git commit -m "feat(robustness): 데이터 분할 헬퍼 (train_test_split/time_segments/buy_hold)"
```

---

### Task 2: 백테스트 구동 함수 (`evaluate`, `param_sweep`, `walk_forward`)

**Files:**
- Modify: `robustness.py` (함수 3개 추가)
- Test: `tests/test_robustness.py` (테스트 추가)

**Interfaces:**
- Consumes: `backtest.run_backtest(df, strategy, **params) -> (bt, stats)`; Task 1의 `time_segments`, `METRIC_KEYS`
- Produces:
  - `evaluate(df, strategy, metric_keys=METRIC_KEYS, **params) -> dict` — 단일 백테스트의 관심 지표 dict
  - `param_sweep(df, strategy, param_grid, metric_keys=METRIC_KEYS, **fixed) -> DataFrame` — 한 행=파라미터+지표
  - `walk_forward(df, strategy, k=5, metric_keys=METRIC_KEYS, **params) -> DataFrame` — 구간별(segment/start/end+지표)

- [ ] **Step 1: 실패 테스트 작성** (`tests/test_robustness.py` 하단에 추가)

```python
from robustness import evaluate, param_sweep, walk_forward, METRIC_KEYS
from strategies.donchian_breakout import DonchianBreakout


def _oscillating(n=600):
    idx = pd.date_range("2020-01-01", periods=n, freq="4h", tz="UTC")
    close = pd.Series(120 + 40 * np.sin(np.linspace(0, 8 * np.pi, n)), index=idx)
    return pd.DataFrame({"Open": close, "High": close * 1.01, "Low": close * 0.99,
                         "Close": close, "Volume": 1000.0}, index=idx)


def test_evaluate_returns_metric_keys():
    m = evaluate(_oscillating(), DonchianBreakout)
    assert set(METRIC_KEYS) <= set(m)
    assert isinstance(m["Return [%]"], float)


def test_param_sweep_covers_grid():
    grid = {"entry_n": [10, 20], "exit_n": [5, 10]}
    out = param_sweep(_oscillating(), DonchianBreakout, grid)
    assert len(out) == 4                              # 2x2 데카르트곱
    assert {"entry_n", "exit_n"} <= set(out.columns)
    assert "Return [%]" in out.columns


def test_walk_forward_segments():
    out = walk_forward(_oscillating(), DonchianBreakout, k=3)
    assert len(out) == 3
    assert list(out["segment"]) == [0, 1, 2]
    assert {"start", "end"} <= set(out.columns)
    assert out["start"].iloc[0] < out["end"].iloc[-1]
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_robustness.py -v`
Expected: FAIL — `ImportError: cannot import name 'evaluate' from 'robustness'`

- [ ] **Step 3: 최소 구현** (`robustness.py`에 추가)

먼저 파일 상단 import에 두 줄을 추가한다 (기존 `import pandas as pd` 위/주변):
```python
import itertools
from backtest import run_backtest
```

그다음 함수 3개를 추가한다:
```python
def evaluate(df, strategy, metric_keys=METRIC_KEYS, **params):
    _, stats = run_backtest(df, strategy, **params)
    return {k: stats[k] for k in metric_keys}


def param_sweep(df, strategy, param_grid, metric_keys=METRIC_KEYS, **fixed):
    keys = list(param_grid)
    rows = []
    for combo in itertools.product(*(param_grid[k] for k in keys)):
        params = dict(zip(keys, combo))
        rows.append({**params, **evaluate(df, strategy, metric_keys, **{**fixed, **params})})
    return pd.DataFrame(rows)


def walk_forward(df, strategy, k=5, metric_keys=METRIC_KEYS, **params):
    rows = []
    for i, seg in enumerate(time_segments(df, k)):
        m = evaluate(seg, strategy, metric_keys, **params)
        rows.append({"segment": i, "start": seg.index[0], "end": seg.index[-1], **m})
    return pd.DataFrame(rows)
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_robustness.py -v`
Expected: PASS (7 passed)

전체 회귀:
Run: `python -m pytest -q`
Expected: 20 passed (기존 13 + 신규 7)

- [ ] **Step 5: 커밋**

```bash
git add robustness.py tests/test_robustness.py
git commit -m "feat(robustness): 백테스트 구동 함수 (evaluate/param_sweep/walk_forward)"
```

---

## 컨트롤러 후속 (계획 범위 밖, 모듈 완성 후)

모듈이 검증을 통과하면 컨트롤러가:
1. 실데이터(`data/BTC_USDT_4h.parquet`)로 Donchian/SMA에 3축 분석 실행 → 실제 숫자 확보.
2. 탈락 기준(설계 문서)으로 통과/탈락 판정 + 결론을 `docs/design/phase-3-robustness.md`에 추가.
3. 연구 노트북 `research/2026-06-28_phase3_robustness.ipynb` 작성·실행(히트맵/표).
4. SMA 손절 갭을 결론에 Important로 명시.
