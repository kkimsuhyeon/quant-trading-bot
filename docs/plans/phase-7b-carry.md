# Phase 7b carry v1 — 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`).

**Goal:** 펀딩 시계열에서 always-on 델타중립 캐리의 손익곡선·지표·분포를 계산하는 고정 도구 `carry.py`를 TDD로 만든다.

**Architecture:** 백테스트 엔진이 아니라 펀딩 Series 계산(robustness/portfolio처럼 고정 도구). 하네스/전략 미수정. 펀딩 데이터 수집·실데이터 분석·결론·노트북은 모듈 완성 후 컨트롤러가 수행.

**Tech Stack:** Python 3.13, pandas(>=2,<3), pytest.

설계: `docs/design/phase-7b-carry.md`

## Global Constraints
- `.venv` Python 3.13, `pandas>=2,<3`. 테스트 `.venv/bin/python -m pytest`.
- **하네스/전략/robustness/portfolio 미수정.** carry.py는 독립 도구.
- 테스트는 **synthetic 펀딩 Series 주입**, `data/`·네트워크 비의존.
- **always-on 모델**: P&L = 누적 펀딩 − 4-leg 수수료(진입 2 legs + 청산 2 legs, 1회씩). 보유 중 리밸런싱 수수료 없음. 가격 손익은 중립 가정(무시).
- 8h 펀딩 → 연율화 `periods_per_year = 3*365 = 1095`.
- 금지: 임계 최적화, 레버리지, 청산/basis 모델링, 복리 최적화, conditional 진입.

---

### Task 1: `carry.py` — `carry_pnl` / `carry_metrics` / `funding_stats`

**Files:**
- Create: `carry.py`
- Test: `tests/test_carry.py`

**Interfaces:**
- Consumes: pandas만 (펀딩 = 8h realized funding rate Series, 시간 인덱스).
- Produces:
  - `carry_pnl(funding, notional=1.0, spot_fee=0.001, perp_fee=0.0005) -> pd.Series` (델타중립 캐리 equity 곡선)
  - `carry_metrics(equity, funding, periods_per_year=1095) -> dict` (`"Return [%]"`, `"Ann Return [%]"`, `"Sharpe"`, `"MDD [%]"`)
  - `funding_stats(funding) -> dict` (`"mean"`, `"median"`, `"p5"`, `"p95"`, `"neg_ratio"`)

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_carry.py`
```python
import numpy as np
import pandas as pd
from carry import carry_pnl, carry_metrics, funding_stats


def _funding(values, start="2021-06-01"):
    idx = pd.date_range(start, periods=len(values), freq="8h", tz="UTC")
    return pd.Series(values, index=idx, dtype=float)


def test_carry_pnl_accrues_funding_minus_fees():
    f = _funding([0.0005] * 100)                       # 매기 +0.0005, 100기
    eq = carry_pnl(f)                                  # notional=1, fee 0.001+0.0005
    # 누적펀딩 0.05, 4-leg 수수료 = 2*(0.001+0.0005)=0.003 → 최종 ≈ 1+0.05-0.003 = 1.047
    assert abs(eq.iloc[-1] - 1.047) < 1e-6
    # 첫 기: 1+0.0005 - 진입수수료 0.0015 = 0.999
    assert abs(eq.iloc[0] - 0.999) < 1e-6


def test_carry_pnl_fees_can_exceed_small_funding():
    f = _funding([0.0001, -0.0001, 0.0001])            # 누적 0.0001, 수수료 0.003
    eq = carry_pnl(f)
    assert eq.iloc[-1] < 1.0                            # 수수료가 펀딩보다 커서 순손실


def test_carry_metrics_keys_and_mdd():
    f = _funding([0.001, -0.002, 0.001, 0.001])
    eq = carry_pnl(f)
    m = carry_metrics(eq, f)
    assert {"Return [%]", "Ann Return [%]", "Sharpe", "MDD [%]"} <= set(m)
    assert m["MDD [%]"] <= 0                            # 낙폭은 음수(또는 0)


def test_funding_stats_neg_ratio():
    f = _funding([0.001, -0.001, -0.001, 0.001])        # 음수 2/4 = 0.5
    s = funding_stats(f)
    assert round(s["neg_ratio"], 2) == 0.5
    assert {"mean", "median", "p5", "p95", "neg_ratio"} <= set(s)
```

- [ ] **Step 2: 실패 확인**
Run: `.venv/bin/python -m pytest tests/test_carry.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'carry'`

- [ ] **Step 3: 구현** — `carry.py`
```python
import pandas as pd


def carry_pnl(funding, notional=1.0, spot_fee=0.001, perp_fee=0.0005):
    leg_fee = notional * (spot_fee + perp_fee)          # 한 쪽(진입 or 청산) = 2 legs
    equity = notional * (1 + funding.cumsum()) - leg_fee   # 진입 수수료(2 legs) 전체 반영
    equity.iloc[-1] -= leg_fee                            # 청산 수수료(2 legs) 마지막에
    return equity


def carry_metrics(equity, funding, periods_per_year=1095):
    ret = (equity.iloc[-1] / equity.iloc[0] - 1) * 100
    n = len(equity)
    ann = ((equity.iloc[-1] / equity.iloc[0]) ** (periods_per_year / n) - 1) * 100 if n > 0 else 0.0
    mdd = (equity / equity.cummax() - 1).min() * 100
    sharpe = (funding.mean() / funding.std()) * (periods_per_year ** 0.5) if funding.std() > 0 else 0.0
    return {"Return [%]": ret, "Ann Return [%]": ann, "Sharpe": sharpe, "MDD [%]": mdd}


def funding_stats(funding):
    return {
        "mean": funding.mean(),
        "median": funding.median(),
        "p5": funding.quantile(0.05),
        "p95": funding.quantile(0.95),
        "neg_ratio": (funding < 0).mean(),
    }
```

- [ ] **Step 4: 통과 확인**
Run: `.venv/bin/python -m pytest tests/test_carry.py -v`
Expected: PASS (4 passed)
전체 회귀: `.venv/bin/python -m pytest -q` → 기존 47 + 신규 4 = 51 passed.

- [ ] **Step 5: 커밋**
```bash
git add carry.py tests/test_carry.py
git commit -m "feat(carry): 펀딩 캐리 손익/지표/분포 (carry_pnl/carry_metrics/funding_stats)"
```

---

## 컨트롤러 후속 (모듈 완성 후, 계획 범위 밖)
1. BTC/ETH perp 펀딩 히스토리 8h 5년 수집(ccxt `fetch_funding_rate_history` 페이지네이션, since 명시) → `data/` 저장.
2. carry_pnl로 BTC/ETH 캐리 손익곡선 + carry_metrics + funding_stats + 연도별 표.
3. **상관**: carry 수익률 vs (Regime/Keltner equity 수익률, BTC 가격 수익률) — 공통 timestamp 리샘플. (델타중립이면 ~0이어야 = 핵심.)
4. 결과/판정을 `docs/design/phase-7b-carry.md`에 추가 (gross-ish·실거래 아님·바로 Phase4 후보 아님 명시).
5. 노트북 `research/2026-06-29_phase7b_carry.ipynb`.
6. final 리뷰 + Codex 크로스리뷰 → merge/push → 결론 보고.
