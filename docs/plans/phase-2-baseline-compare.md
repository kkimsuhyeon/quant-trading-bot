# Phase 2 baseline 전략 비교 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement task-by-task. Steps use checkbox (`- [ ]`).

> 실행 계획(how)이지 설계 정본이 아님. 설계 정본: [`docs/design/phase-2-baseline-compare.md`](../design/phase-2-baseline-compare.md).

**Goal:** 평균회귀 전략 2개(RSI 과매도 반등, 볼린저 하단 반등)를 독립 부품으로 추가하고, 기존 SMA(추세추종)와 같은 BTC 데이터로 비교한다.

**Architecture:** 하네스(`backtest.py`)·데이터(`fetch.py`)는 불변. 전략은 `strategies/`에 부품으로 추가. 지표는 직접 계산(새 의존성 없음). 손절은 전략 안에서 `self.buy(sl=...)`로 지정.

**Tech Stack:** Python, pandas, backtesting(FractionalBacktest), pytest, Jupyter. (pandas-ta 미사용 — Python 3.9 미지원.)

## Global Constraints

- 지표 **직접 계산**(헬퍼 함수). 새 라이브러리 추가 금지.
- 손절: 두 전략 공통 `stop_loss_pct=0.05`, `self.buy(sl=price*(1-stop_loss_pct))`. ⚠️ `trade_on_close=False`라 sl 기준은 **신호 캔들 종가**(실제 진입은 다음 봉 시가) → "신호 종가 기준 -5% proxy". **손절값 스윕/최적화 금지.**
- `commission=0.001`, `spread=0.0`, `trade_on_close=False` — 기존 `run_backtest` 기본값 그대로. **하네스 수정 금지.**
- 각 전략: `use_sentiment=False` 스위치 자리 유지(미구현, 주석).
- 가설 문서(`notes/hypothesis_*.md`)는 **전략 백테스트 전에** 작성(가드레일 6).
- pytest는 항상 `python -m pytest`(repo 루트)로 실행. venv: `source .venv/bin/activate`.
- 데이터: BTC만. 비용/하네스/데이터 모두 Phase 1과 동일.

---

### Task 1: RSI 과매도 반등 전략

**Files:**
- Create: `notes/hypothesis_rsi_reversion.md`
- Create: `strategies/rsi_reversion.py`
- Test: `tests/test_strategies.py`

**Interfaces:**
- Consumes: `backtest.run_backtest` (기존).
- Produces: `strategies.rsi_reversion.RsiReversion` — `Strategy` 서브클래스. 속성 `rsi_period=14, oversold=30, exit_level=50, stop_loss_pct=0.05, use_sentiment=False`.

- [ ] **Step 1: 가설 문서 작성 (백테스트 전)**

`notes/hypothesis_rsi_reversion.md`:
```markdown
# 가설 — RSI 과매도 반등

- **시장에 대한 믿음**: 과도하게 팔려(RSI<30) 단기적으로 과매도면, 평균으로 단기 반등할 확률이 높다.
- **진입 규칙**: RSI(14) < 30 이고 포지션 없음 → 매수.
- **청산 규칙**: RSI(14) > 50 → 청산. 또는 신호 캔들 종가 기준 -5% 손절(proxy).
- **버릴 기준**: OOS(Phase 3)에서 Buy & Hold를 못 이기거나, **Phase 3 OOS/민감도 검토**(예: 손절 3/5/8%)에서 결과가 무너지면 폐기. (Phase 2에서는 손절값 스윕 안 함.)
- **장세 적합/취약**: 횡보장 유리, 강한 하락 추세에서 "떨어지는 칼날"로 취약(그래서 손절 필수).
```

- [ ] **Step 2: 실패하는 테스트 작성**

`tests/test_strategies.py`:
```python
import numpy as np
import pandas as pd
from backtest import run_backtest
from strategies.rsi_reversion import RsiReversion


def _dip_recover(n=150):
    """저변동 → 급락(과매도/밴드돌파) → 회복. 평균회귀 진입/청산을 유발."""
    idx = pd.date_range("2020-01-01", periods=n, freq="1h", tz="UTC")
    seg = np.concatenate([
        np.linspace(100, 102, 50),   # 완만 상승 (저변동 → 좁은 밴드)
        np.linspace(102, 72, 30),    # 급락 (RSI<30, 볼린저 하단 돌파)
        np.linspace(72, 108, 70),    # 회복 (RSI>50, 종가>중심선 → 청산)
    ])
    close = pd.Series(seg, index=idx)
    return pd.DataFrame({"Open": close, "High": close, "Low": close,
                         "Close": close, "Volume": 1000.0}, index=idx)


def test_rsi_reversion_trades_and_stats():
    _, stats = run_backtest(_dip_recover(), RsiReversion)
    assert stats["# Trades"] > 0
    for key in ["Return [%]", "Sharpe Ratio", "Max. Drawdown [%]", "# Trades"]:
        assert key in stats.index
```

- [ ] **Step 3: 실패 확인**

Run: `python -m pytest tests/test_strategies.py -v`
Expected: FAIL (`cannot import name 'RsiReversion'`).

- [ ] **Step 4: 전략 구현**

`strategies/rsi_reversion.py`:
```python
import pandas as pd
from backtesting import Strategy


def RSI(close, n):
    s = pd.Series(close)
    delta = s.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / n, min_periods=n, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / n, min_periods=n, adjust=False).mean()
    rs = avg_gain / avg_loss
    return (100 - 100 / (1 + rs)).values


class RsiReversion(Strategy):
    rsi_period = 14
    oversold = 30
    exit_level = 50
    stop_loss_pct = 0.05
    use_sentiment = False

    def init(self):
        self.rsi = self.I(RSI, self.data.Close, self.rsi_period)
        # sentiment 자리 (Phase 5):
        # if self.use_sentiment:
        #     self.sentiment = self.data.sentiment

    def next(self):
        price = self.data.Close[-1]
        if not self.position:
            if self.rsi[-1] < self.oversold:                 # 과매도 → 매수
                self.buy(sl=price * (1 - self.stop_loss_pct))  # -5% 손절
        else:
            if self.rsi[-1] > self.exit_level:               # 중립 복귀 → 청산
                self.position.close()
        # sentiment 자리 (Phase 5, 비활성)
```

- [ ] **Step 5: 통과 확인**

Run: `python -m pytest tests/test_strategies.py -v`
Expected: 1 passed. (만약 `# Trades == 0`이면 `_dip_recover` 급락 구간을 더 가파르게 조정 — 의도는 "과매도 진입이 실제로 발생"이다.)

- [ ] **Step 6: Commit**

```bash
git add notes/hypothesis_rsi_reversion.md strategies/rsi_reversion.py tests/test_strategies.py
git commit -m "feat: add RSI oversold reversion strategy with 5% stop"
```

---

### Task 2: 볼린저 하단 반등 전략

**Files:**
- Create: `notes/hypothesis_bollinger_reversion.md`
- Create: `strategies/bollinger_reversion.py`
- Modify: `tests/test_strategies.py`

**Interfaces:**
- Produces: `strategies.bollinger_reversion.BollingerReversion` — 속성 `bb_period=20, bb_std=2, stop_loss_pct=0.05, use_sentiment=False`.

- [ ] **Step 1: 가설 문서 작성**

`notes/hypothesis_bollinger_reversion.md`:
```markdown
# 가설 — 볼린저 하단 반등

- **시장에 대한 믿음**: 가격이 볼린저 하단(평균-2σ) 아래로 벗어나면 통계적으로 과도한 이탈이라, 중심선(평균)으로 회귀할 확률이 높다.
- **진입 규칙**: 종가 < 하단밴드(20,2σ) 이고 포지션 없음 → 매수.
- **청산 규칙**: 종가 > 중심선(20 SMA) → 청산. 또는 신호 캔들 종가 기준 -5% 손절(proxy).
- **버릴 기준**: OOS(Phase 3)에서 Buy & Hold를 못 이기거나 파라미터 민감도에서 무너지면 폐기.
- **장세 적합/취약**: 횡보장 유리, 추세 하락에서 밴드를 타고 계속 내려가면 취약(손절 필수).
```

- [ ] **Step 2: 실패하는 테스트 작성**

`tests/test_strategies.py`에 추가:
```python
from strategies.bollinger_reversion import BollingerReversion


def test_bollinger_reversion_trades_and_stats():
    _, stats = run_backtest(_dip_recover(), BollingerReversion)
    assert stats["# Trades"] > 0
    for key in ["Return [%]", "Sharpe Ratio", "Max. Drawdown [%]", "# Trades"]:
        assert key in stats.index
```

- [ ] **Step 3: 실패 확인**

Run: `python -m pytest tests/test_strategies.py::test_bollinger_reversion_trades_and_stats -v`
Expected: FAIL (`cannot import name 'BollingerReversion'`).

- [ ] **Step 4: 전략 구현**

`strategies/bollinger_reversion.py`:
```python
import pandas as pd
from backtesting import Strategy


def SMA(close, n):
    return pd.Series(close).rolling(n).mean().values


def BB_LOWER(close, n, k):
    s = pd.Series(close)
    mid = s.rolling(n).mean()
    std = s.rolling(n).std()
    return (mid - k * std).values


class BollingerReversion(Strategy):
    bb_period = 20
    bb_std = 2
    stop_loss_pct = 0.05
    use_sentiment = False

    def init(self):
        self.mid = self.I(SMA, self.data.Close, self.bb_period)
        self.lower = self.I(BB_LOWER, self.data.Close, self.bb_period, self.bb_std)
        # sentiment 자리 (Phase 5):
        # if self.use_sentiment:
        #     self.sentiment = self.data.sentiment

    def next(self):
        price = self.data.Close[-1]
        if not self.position:
            if price < self.lower[-1]:                       # 하단 돌파 → 매수
                self.buy(sl=price * (1 - self.stop_loss_pct))  # -5% 손절
        else:
            if price > self.mid[-1]:                          # 중심선 복귀 → 청산
                self.position.close()
        # sentiment 자리 (Phase 5, 비활성)
```

- [ ] **Step 5: 통과 확인**

Run: `python -m pytest tests/test_strategies.py -v`
Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add notes/hypothesis_bollinger_reversion.md strategies/bollinger_reversion.py tests/test_strategies.py
git commit -m "feat: add Bollinger lower-band reversion strategy with 5% stop"
```

---

### Task 3: 3전략 비교 노트북 + 문서

**Files:**
- Create: `research/2026-06-27_phase2_compare.ipynb`
- Create: `docs/strategies/rsi_reversion.md`, `docs/strategies/bollinger_reversion.md`
- Modify: `docs/strategies/README.md`, `docs/design/README.md`

**Interfaces:** Consumes `load_data`, `run_backtest`, 세 전략 클래스.

- [ ] **Step 1: 비교 노트북 작성 + 실행**

`research/2026-06-27_phase2_compare.ipynb` 셀:

셀 1 (경로 정규화 + import):
```python
import os, sys
if os.path.basename(os.getcwd()) == "research":
    os.chdir("..")
sys.path.insert(0, os.getcwd())
import pandas as pd
from backtest import load_data, run_backtest
from strategies.sma_cross import SmaCross
from strategies.rsi_reversion import RsiReversion
from strategies.bollinger_reversion import BollingerReversion
```
셀 2 (3전략 실행 + 비교표):
```python
df = load_data("BTC/USDT", "1h")
strategies = {"SMA(trend)": SmaCross, "RSI(rev)": RsiReversion, "Bollinger(rev)": BollingerReversion}
runs = {name: run_backtest(df, strat) for name, strat in strategies.items()}
keys = ["Return [%]", "Buy & Hold Return [%]", "Sharpe Ratio", "Max. Drawdown [%]", "Win Rate [%]", "# Trades"]
table = pd.DataFrame({name: stats[keys] for name, (bt, stats) in runs.items()})
table
```
셀 3 (수익곡선 겹쳐 그리기):
```python
import matplotlib.pyplot as plt
plt.figure(figsize=(12, 6))
for name, (bt, stats) in runs.items():
    eq = stats["_equity_curve"]["Equity"]
    plt.plot(eq.index, eq.values, label=name)
plt.title("Phase 2: 자본 곡선 비교 (BTC/USDT 1h)")
plt.ylabel("Equity [$]"); plt.legend(); plt.grid(True)
plt.show()
```

실행: `jupyter nbconvert --to notebook --execute --inplace research/2026-06-27_phase2_compare.ipynb`
확인: 셀 2 표에 3전략 지표가 모두 값으로 나오고(`# Trades > 0`), 셀 3 그래프에 곡선 3개가 그려진다. 비교표의 실제 숫자를 다음 Step 문서에 옮긴다.

- [ ] **Step 2: 전략 설명 문서 작성 (실제 결과 반영)**

`docs/strategies/rsi_reversion.md`, `docs/strategies/bollinger_reversion.md`를 [`sma_cross.md`](../../docs/strategies/sma_cross.md) 구조(요약·믿음·지표·규칙·파라미터·장세·결과·관련)로 작성. **결과 표는 셀 2 실제 숫자**를 넣는다. 각 문서 상단에 `notes/hypothesis_*.md` 링크.

- [ ] **Step 3: 인덱스 갱신**

`docs/strategies/README.md` 표에 RSI·볼린저 2줄 추가(유형=평균회귀, 상태=검증 중).
`docs/design/README.md` 표에서 Phase 2 상태를 "설계 완료" → 실제 진행에 맞게 갱신 + `phase-2-baseline-compare.md` 링크.

- [ ] **Step 4: 출력 비우고 Commit**

```bash
jupyter nbconvert --clear-output --inplace research/2026-06-27_phase2_compare.ipynb
git add research/ docs/strategies/ docs/design/README.md
git commit -m "docs: add Phase 2 strategy comparison notebook and strategy docs"
```

---

## 완료 기준 (전체)

1. `python -m pytest -q` — 전체 테스트 통과(기존 7 + 신규 2 = 9).
2. 비교 노트북: 3전략 비교표(`# Trades > 0`) + 수익곡선 3개.
3. 가설 문서 2개, 전략 설명 문서 2개, 인덱스 갱신 완료.
4. 손절 -5% 두 전략 적용, 하네스 미수정, sentiment 스위치 유지.

## Self-Review 메모

- 스펙 커버리지: 설계 §3→T1/T2, §4(손절)→T1/T2 `self.buy(sl=)`, §5(비교)→T3, §7(가설문서)→T1/T2 Step1. 모두 매핑.
- placeholder 없음(결과 숫자는 T3 Step1 실행 후 채움 — 의도된 순서).
- 타입 일관성: `RsiReversion`/`BollingerReversion`/`RSI`/`SMA`/`BB_LOWER` 명칭 태스크 간 일치.
