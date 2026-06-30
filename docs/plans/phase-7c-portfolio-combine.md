# Phase 7c — 추세+캐리 2-엣지 포트폴리오 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 서로 다른 케이던스의 전략 equity들을 일간 그리드로 가중 결합하는 `combine_sleeves`를 `portfolio.py`에 추가하고, `portfolio_metrics`에 `periods_per_year` 파라미터를 더해 일간 결합곡선을 평가할 수 있게 한다.

**Architecture:** 하네스/전략 불변. `portfolio.py`(고정 도구)에 함수 하나 추가 + 기존 함수에 하위호환 파라미터 하나 추가. 결합 로직은 "일간 리샘플 → 공통창 dropna → 공통창 첫 row 정규화 → 가중 합산" (Codex 자문). 상관/평가는 노트북(별도)에서.

**Tech Stack:** Python 3.13, pandas(>=2,<3), pytest. `.venv/bin/python -m pytest`.

## Global Constraints
- 하네스(`backtest.py`)·전략 파일 수정 금지. `portfolio.py`에만 손댄다.
- `portfolio_metrics` 기본값 `periods_per_year=6*365` 유지(기존 호출 4h봉 호환). 일간엔 365로 호출.
- 정규화는 **각 sleeve 자기 첫값이 아니라 공통창(dropna 후) 첫 row 기준** (Codex 2 — 늦게 시작한 sleeve의 창밖 성과 혼입 방지).
- 임계/비중 최적화 금지. 테스트는 synthetic만 (data/·네트워크 비의존).
- pandas `pct_change(fill_method=None)` 사용(경고/NaN 패딩 방지).

---

### Task 1: `combine_sleeves` + `portfolio_metrics` periods_per_year

**Files:**
- Modify: `portfolio.py` (함수 1개 추가, `portfolio_metrics` 시그니처 1개 변경)
- Test: `tests/test_portfolio.py` (기존 — Phase 7a 테스트 6개 보존 + 신규 4개 추가)

**Interfaces:**
- Consumes: 기존 `portfolio.py`의 import(`pandas as pd`).
- Produces:
  - `combine_sleeves(equities: dict[str, pd.Series], weights: dict[str, float] | None = None, freq="1D", cash=10_000) -> pd.Series`
  - `portfolio_metrics(equity: pd.Series, periods_per_year: int = 6*365) -> dict` (기존 호출 호환)

- [ ] **Step 1: Write the failing tests**

`tests/test_portfolio.py`:
```python
import numpy as np
import pandas as pd
from portfolio import combine_sleeves, portfolio_metrics


def _days(start, n):
    return pd.date_range(start, periods=n, freq="1D", tz="UTC")


def test_combine_identical_equal_weight():
    # 같은 곡선 둘을 등가중 → 결합은 그 곡선(현금 정규화)과 동일 형태
    idx = _days("2021-01-01", 5)
    a = pd.Series([100, 110, 121, 133.1, 146.41], index=idx)
    c = combine_sleeves({"x": a, "y": a}, cash=1000)
    assert abs(c.iloc[0] - 1000) < 1e-6
    assert abs(c.iloc[-1] - 1464.1) < 1e-3   # 1000 * 1.4641


def test_combine_normalizes_to_common_window_not_own_first():
    # a는 공통창 '전'에 2배 뛰지만, 정규화는 공통창 첫 row 기준이라 그 성과는 빠져야 한다
    a = pd.Series([1, 2, 4, 4, 4], index=_days("2021-01-01", 5))
    b = pd.Series([10, 10, 10], index=_days("2021-01-03", 3))   # 늦게 시작, flat
    c = combine_sleeves({"a": a, "b": b}, weights={"a": 0.5, "b": 0.5}, cash=1000)
    assert len(c) == 3                       # 공통창 = 01-03~01-05
    assert abs(c.iloc[0] - 1000) < 1e-6
    assert abs(c.iloc[-1] - 1000) < 1e-6     # a의 창밖 2배 상승은 결합에 반영 안 됨


def test_combine_weights_change_result():
    idx = _days("2021-01-01", 2)
    up = pd.Series([100, 200], index=idx)    # +100%
    flat = pd.Series([100, 100], index=idx)  # flat
    c5050 = combine_sleeves({"u": up, "f": flat}, weights={"u": 0.5, "f": 0.5}, cash=1000)
    c7030 = combine_sleeves({"u": up, "f": flat}, weights={"u": 0.7, "f": 0.3}, cash=1000)
    assert abs(c5050.iloc[-1] - 1500) < 1e-6   # 0.5*2 + 0.5*1 = 1.5
    assert abs(c7030.iloc[-1] - 1700) < 1e-6   # 0.7*2 + 0.3*1 = 1.7


def test_metrics_periods_per_year_scales_sharpe_only():
    rets = np.array([0.02, -0.01] * 50)        # std>0
    eq = pd.Series(100 * np.cumprod(1 + rets), index=_days("2021-01-01", 100))
    m_default = portfolio_metrics(eq)           # 6*365
    m_daily = portfolio_metrics(eq, periods_per_year=365)
    assert abs(m_default["Sharpe Ratio"] / m_daily["Sharpe Ratio"] - 6 ** 0.5) < 1e-6
    assert m_default["Return [%]"] == m_daily["Return [%]"]      # 연율화는 Return/MDD 불변
    assert m_default["Max. Drawdown [%]"] == m_daily["Max. Drawdown [%]"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_portfolio.py -v`
Expected: FAIL — `ImportError: cannot import name 'combine_sleeves'` (및 periods_per_year TypeError).

- [ ] **Step 3: Implement**

`portfolio.py`에 `combine_sleeves` 추가:
```python
def combine_sleeves(equities, weights=None, freq="1D", cash=10_000):
    names = list(equities.keys())
    if weights is None:
        weights = {n: 1 / len(names) for n in names}
    # 1) 각 sleeve 일간 리샘플 → 2) 한 DataFrame → 3) 공통창 dropna
    df = pd.DataFrame({n: equities[n].resample(freq).last() for n in names}).dropna()
    # 4) 공통창 첫 row로 정규화 → 5) cash*weight 가중 합산
    parts = {n: cash * weights[n] * df[n] / df[n].iloc[0] for n in names}
    return pd.DataFrame(parts).sum(axis=1)
```

`portfolio_metrics` 시그니처에 파라미터 추가(본문 `bars_per_year` → 파라미터 사용):
```python
def portfolio_metrics(equity, periods_per_year=6 * 365):
    ret = (equity.iloc[-1] / equity.iloc[0] - 1) * 100
    mdd = (equity / equity.cummax() - 1).min() * 100
    r = equity.pct_change(fill_method=None).dropna()
    sharpe = (r.mean() / r.std()) * (periods_per_year ** 0.5) if r.std() > 0 else 0.0
    return {"Return [%]": ret, "Max. Drawdown [%]": mdd, "Sharpe Ratio": sharpe}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_portfolio.py -v`
Expected: PASS (4 passed). 전체도 회귀 없게: `.venv/bin/python -m pytest -q` → 모두 PASS.

- [ ] **Step 5: Commit**

```bash
git add portfolio.py tests/test_portfolio.py
git commit -m "feat(portfolio): combine_sleeves(케이던스 다른 sleeve 일간 가중결합) + portfolio_metrics periods_per_year"
```
