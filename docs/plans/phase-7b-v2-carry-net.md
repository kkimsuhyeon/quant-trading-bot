# Phase 7b-v2 — 캐리 net 타당성 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** gross 캐리(v1)에 결정적 비용/haircut을 얹어 net 손익을 계산하는 헬퍼 3개를 `carry.py`에 추가한다 — net 손익곡선, 최악 90일 rolling 수익, 음수 펀딩 레짐 지표.

**Architecture:** 하네스/전략 불변. `carry.py`(고정 도구)에 함수 3개 추가. `net_carry_pnl`은 v1 `carry_pnl`을 재사용(funding에서 haircut drag를 뺀 뒤 호출 = DRY). 시나리오 비교는 노트북에서.

**Tech Stack:** Python 3.13, pandas(>=2,<3), pytest. `.venv/bin/python -m pytest`.

## Global Constraints
- 하네스(`backtest.py`)·전략 파일 수정 금지. `carry.py`에만 추가. v1 함수(`carry_pnl`/`carry_metrics`/`funding_stats`) 시그니처 변경 금지.
- net 모델: `net = gross_funding 누적 − 4-leg 수수료(1회) − 연 haircut 누적차감`. **1x 무레버리지만.**
- haircut/수수료는 **사전 고정 시나리오**(호출 인자), 코드에 임계 sweep/최적화 넣지 않음.
- 테스트는 synthetic만(data/·네트워크 비의존). 기존 전체 테스트 회귀 없게(현재 63 passed).

---

### Task 1: net_carry 헬퍼 3종 (`carry.py`)

**Files:**
- Modify: `carry.py` (함수 3개 추가; 기존 함수 불변)
- Test: `tests/test_carry.py` (기존 — 6개 보존 + 신규 4개 추가)

**Interfaces:**
- Consumes: 기존 `carry.py`의 `carry_pnl(funding, notional=1.0, spot_fee=0.001, perp_fee=0.0005)`.
- Produces:
  - `net_carry_pnl(funding, notional=1.0, spot_fee=0.001, perp_fee=0.0005, annual_haircut=0.02, periods_per_year=1095) -> pd.Series`
  - `rolling_worst_return(equity, window=270) -> float`
  - `negative_funding_stats(funding) -> dict` (키: `longest_neg_streak`, `neg_total`, `neg_ratio`)

- [ ] **Step 1: Write the failing tests** — `tests/test_carry.py`에 아래 4개 추가(기존 6개는 그대로 둔다)

```python
def test_net_carry_zero_haircut_equals_gross():
    # haircut 0이면 net == gross (v1과 동일)
    funding = pd.Series([0.001, -0.0005, 0.002, 0.0], index=pd.date_range("2021-01-01", periods=4, freq="8h", tz="UTC"))
    from carry import carry_pnl, net_carry_pnl
    pd.testing.assert_series_equal(net_carry_pnl(funding, annual_haircut=0.0), carry_pnl(funding))


def test_net_carry_drag_exact():
    # funding 전부 0, periods_per_year=3, haircut 0.03 → 매 기간 drag 0.01
    funding = pd.Series([0.0, 0.0, 0.0], index=pd.date_range("2021-01-01", periods=3, freq="8h", tz="UTC"))
    from carry import net_carry_pnl
    eq = net_carry_pnl(funding, annual_haircut=0.03, periods_per_year=3)  # leg_fee=0.0015
    # cumsum(-0.01)=[-0.01,-0.02,-0.03]; 1+cumsum-leg_fee, 마지막 -leg_fee 추가
    assert abs(eq.iloc[-1] - (1 - 0.03 - 2 * 0.0015)) < 1e-9   # 0.967


def test_net_carry_haircut_monotonic():
    # 양의 펀딩에서 haircut↑일수록 최종 net↓
    funding = pd.Series([0.001] * 100, index=pd.date_range("2021-01-01", periods=100, freq="8h", tz="UTC"))
    from carry import net_carry_pnl
    e2 = net_carry_pnl(funding, annual_haircut=0.02).iloc[-1]
    e6 = net_carry_pnl(funding, annual_haircut=0.06).iloc[-1]
    assert e6 < e2


def test_rolling_worst_and_negative_stats():
    from carry import rolling_worst_return, negative_funding_stats
    eq = pd.Series([100., 100., 80., 100.], index=pd.date_range("2021-01-01", periods=4, freq="8h", tz="UTC"))
    assert round(rolling_worst_return(eq, window=2), 4) == -0.2     # 80/100-1

    f = pd.Series([0.001, -0.002, -0.003, 0.001, -0.001])
    s = negative_funding_stats(f)
    assert s["longest_neg_streak"] == 2                            # idx1,2 연속
    assert abs(s["neg_total"] - (-0.006)) < 1e-9
    assert s["neg_ratio"] == 0.6                                   # 3/5
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_carry.py -v`
Expected: FAIL — `ImportError: cannot import name 'net_carry_pnl' from 'carry'` (등 신규 함수 없음).

- [ ] **Step 3: Implement** — `carry.py` 끝에 함수 3개 추가(기존 함수는 건드리지 않는다)

```python
def net_carry_pnl(funding, notional=1.0, spot_fee=0.001, perp_fee=0.0005,
                  annual_haircut=0.02, periods_per_year=1095):
    """v1 gross 캐리에 연 haircut을 매 기간 균등 차감한 net 손익곡선. carry_pnl 재사용(DRY)."""
    drag = annual_haircut / periods_per_year          # 매 8h basis/슬리피지 haircut
    return carry_pnl(funding - drag, notional=notional, spot_fee=spot_fee, perp_fee=perp_fee)


def rolling_worst_return(equity, window=270):
    """최악 window-기간 수익률(기본 270 = 90일*3, 8h봉). equity[t]/equity[t-window]-1 의 최소."""
    return (equity / equity.shift(window) - 1).min()


def negative_funding_stats(funding):
    """음수 펀딩 레짐 지표: 최장 연속 음수 개수 / 음수 구간 합 / 음수 비율."""
    neg = funding < 0
    longest = streak = 0
    for v in neg:
        streak = streak + 1 if v else 0
        longest = max(longest, streak)
    return {
        "longest_neg_streak": longest,
        "neg_total": funding[neg].sum(),
        "neg_ratio": neg.mean(),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_carry.py -v`
Expected: PASS (10 passed = 기존 6 + 신규 4). 전체 회귀: `.venv/bin/python -m pytest -q` → 모두 PASS.

- [ ] **Step 5: Commit**

```bash
git add carry.py tests/test_carry.py
git commit -m "feat(carry): net 타당성 헬퍼 (net_carry_pnl/rolling_worst_return/negative_funding_stats)"
```
