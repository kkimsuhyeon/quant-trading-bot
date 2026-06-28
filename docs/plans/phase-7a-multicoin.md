# Phase 7a 다코인 포트폴리오 — 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`).

**Goal:** 코인별 단일자산 백테스트 결과를 동일비중으로 결합해 "다코인 분산이 BTC 단독보다 매끈한가"를 볼 고정 도구 `portfolio.py`를 TDD로 만든다.

**Architecture:** `backtest.run_backtest`를 코인별로 호출해 equity curve를 모으고(상장 전 = 현금), 초기 동일자본 buy-and-hold식으로 합산. 하네스/전략/robustness 미수정. 실데이터 다코인 분석·결론·노트북은 모듈 완성 후 컨트롤러가 수행.

**Tech Stack:** Python 3.13, pandas(>=2,<3), Backtesting.py, pytest.

설계: `docs/design/phase-7a-multicoin.md`

## Global Constraints
- `.venv` Python 3.13, `pandas>=2,<3`. 테스트 `.venv/bin/python -m pytest`.
- **하네스/전략/robustness 미수정** (`backtest.py`, `strategies/*`, `robustness.py`). 재사용만.
- 테스트는 **synthetic 데이터 주입**, `data/*.parquet`·네트워크 비의존.
- **동일비중 고정** (가중치 최적화 금지). 상장 전(데이터 시작 전) 구간 = 그 코인 몫은 **현금 보유**(타 코인 재분배 금지 = 누수 방지).
- 매봉 리밸런싱 없음 (초기 동일자본 배정 후 방치 = buy-and-hold식 합산).

---

### Task 1: `portfolio.py` — equity 추출 (`equity_curve`, `per_coin_equity`)

**Files:**
- Create: `portfolio.py`
- Test: `tests/test_portfolio.py`

**Interfaces:**
- Consumes: `backtest.run_backtest(df, strategy, **params) -> (bt, stats)`; `stats["_equity_curve"]["Equity"]` = 시간축 equity Series.
- Produces:
  - `equity_curve(df, strategy, **params) -> pd.Series` (시간 인덱스 equity)
  - `per_coin_equity(data_by_symbol, strategy, **params) -> pd.DataFrame` (열=심볼, 합집합 시간축, 상장 전=NaN)

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_portfolio.py`
```python
import numpy as np
import pandas as pd
from portfolio import equity_curve, per_coin_equity
from strategies.sma_cross import SmaCross


def _osc(n=400, start="2021-01-01"):
    idx = pd.date_range(start, periods=n, freq="4h", tz="UTC")
    close = pd.Series(120 + 40 * np.sin(np.linspace(0, 8 * np.pi, n)), index=idx)
    return pd.DataFrame({"Open": close, "High": close * 1.01, "Low": close * 0.99,
                         "Close": close, "Volume": 1000.0}, index=idx)


def test_equity_curve_series_starts_near_cash():
    eq = equity_curve(_osc(), SmaCross)
    assert isinstance(eq, pd.Series)
    assert len(eq) > 0
    assert 9000 < eq.iloc[0] < 11000          # 초기 자본 ~10,000


def test_per_coin_equity_aligns_and_marks_inactive():
    data = {"A/USDT": _osc(400, "2021-01-01"), "B/USDT": _osc(300, "2021-03-01")}
    out = per_coin_equity(data, SmaCross)
    assert set(out.columns) == {"A/USDT", "B/USDT"}
    assert pd.isna(out["B/USDT"].iloc[0])     # B는 늦게 시작 → 앞 구간 NaN(미참여)
```

- [ ] **Step 2: 실패 확인**
Run: `.venv/bin/python -m pytest tests/test_portfolio.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'portfolio'`

- [ ] **Step 3: 구현** — `portfolio.py`
```python
import pandas as pd
from backtest import run_backtest


def equity_curve(df, strategy, **params):
    _, stats = run_backtest(df, strategy, **params)
    return stats["_equity_curve"]["Equity"]


def per_coin_equity(data_by_symbol, strategy, **params):
    cols = {sym: equity_curve(df, strategy, **params) for sym, df in data_by_symbol.items()}
    return pd.DataFrame(cols)
```

- [ ] **Step 4: 통과 확인**
Run: `.venv/bin/python -m pytest tests/test_portfolio.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: 커밋**
```bash
git add portfolio.py tests/test_portfolio.py
git commit -m "feat(portfolio): 코인별 equity 추출 (equity_curve/per_coin_equity)"
```

---

### Task 2: `portfolio.py` — 결합·지표 (`combine_equal_weight`, `portfolio_metrics`, `return_correlation`)

**Files:**
- Modify: `portfolio.py` (함수 추가)
- Test: `tests/test_portfolio.py` (추가)

**Interfaces:**
- Consumes: Task 1의 `per_coin_equity` 출력(열=심볼 equity DataFrame).
- Produces:
  - `combine_equal_weight(equities, cash=10_000) -> pd.Series` (초기 동일자본 합산 포트 equity)
  - `portfolio_metrics(equity) -> dict` (`"Return [%]"`, `"Max. Drawdown [%]"`, `"Sharpe Ratio"`)
  - `return_correlation(equities) -> pd.DataFrame` (코인별 equity 수익률 상관행렬)

- [ ] **Step 1: 실패 테스트 작성** (`tests/test_portfolio.py` 하단에 추가)
```python
from portfolio import combine_equal_weight, portfolio_metrics, return_correlation


def test_combine_equal_weight_sums_contributions():
    idx = pd.date_range("2021-01-01", periods=4, freq="4h", tz="UTC")
    eq = pd.DataFrame({"A": [100., 150., 200., 200.], "B": [100., 100., 100., 100.]}, index=idx)
    port = combine_equal_weight(eq, cash=1000)          # 코인당 500 배정
    assert abs(port.iloc[0] - 1000) < 1e-6              # 500*(100/100)+500
    assert abs(port.iloc[-1] - 1500) < 1e-6             # 500*(200/100)+500


def test_combine_inactive_coin_held_as_cash():
    idx = pd.date_range("2021-01-01", periods=3, freq="4h", tz="UTC")
    eq = pd.DataFrame({"A": [100., 110., 120.], "B": [np.nan, 100., 200.]}, index=idx)
    port = combine_equal_weight(eq, cash=1000)
    assert abs(port.iloc[0] - 1000) < 1e-6             # A 500 + B 미참여(현금 500)
    assert abs(port.iloc[-1] - 1600) < 1e-6            # A 500*1.2=600 + B 500*2=1000


def test_portfolio_metrics_return_and_mdd():
    idx = pd.date_range("2021-01-01", periods=3, freq="4h", tz="UTC")
    eq = pd.Series([100., 50., 75.], index=idx)
    m = portfolio_metrics(eq)
    assert round(m["Return [%]"], 1) == -25.0
    assert round(m["Max. Drawdown [%]"], 1) == -50.0


def test_return_correlation_perfect():
    idx = pd.date_range("2021-01-01", periods=5, freq="4h", tz="UTC")
    a = pd.Series([1., 2., 3., 4., 5.], index=idx)
    c = return_correlation(pd.DataFrame({"A": a, "B": a * 2}))
    assert round(c.loc["A", "B"], 4) == 1.0
```

- [ ] **Step 2: 실패 확인**
Run: `.venv/bin/python -m pytest tests/test_portfolio.py -v`
Expected: FAIL — `ImportError: cannot import name 'combine_equal_weight'`

- [ ] **Step 3: 구현** (`portfolio.py`에 추가)
```python
def combine_equal_weight(equities, cash=10_000):
    n = equities.shape[1]
    alloc = cash / n
    contribs = {}
    for col in equities.columns:
        e = equities[col]
        first = e.dropna().iloc[0]
        # 상장 후: alloc*(e/first). 상장 전(선행 NaN): 현금 alloc 보유. 내부 결측: ffill.
        contribs[col] = (alloc * e / first).ffill().fillna(alloc)
    return pd.DataFrame(contribs).sum(axis=1)


def portfolio_metrics(equity):
    ret = (equity.iloc[-1] / equity.iloc[0] - 1) * 100
    mdd = (equity / equity.cummax() - 1).min() * 100
    r = equity.pct_change().dropna()
    bars_per_year = 6 * 365                     # 4h봉: 하루 6개 (크립토 24/7)
    sharpe = (r.mean() / r.std()) * (bars_per_year ** 0.5) if r.std() > 0 else 0.0
    return {"Return [%]": ret, "Max. Drawdown [%]": mdd, "Sharpe Ratio": sharpe}


def return_correlation(equities):
    return equities.pct_change().corr()
```

- [ ] **Step 4: 통과 확인**
Run: `.venv/bin/python -m pytest tests/test_portfolio.py -v`
Expected: PASS (6 passed)
전체 회귀: `.venv/bin/python -m pytest -q` → 기존 41 + 신규 6 = 47 passed.

- [ ] **Step 5: 커밋**
```bash
git add portfolio.py tests/test_portfolio.py
git commit -m "feat(portfolio): 동일비중 결합 + 지표 + 상관행렬"
```

---

## 컨트롤러 후속 (모듈 완성 후, 계획 범위 밖)
1. 유니버스 8~10 코인 4h 데이터 수집 (fetch 호출).
2. Regime(1순위)로 BTC단독 vs 다코인 포트 vs alt바스켓 비교 (MDD/Sharpe/총수익), 상관행렬, 5구간 방어. Keltner로 반복(분산효과가 전략 바꿔도 유지되나).
3. 결과/판정을 `docs/design/phase-7a-multicoin.md`에 추가 (survivor-bias·1~2코인 의존 여부 명시).
4. 노트북 `research/2026-06-29_phase7a_multicoin.ipynb`.
5. final 리뷰 + Codex 크로스리뷰 → merge/push → 결론 보고.
