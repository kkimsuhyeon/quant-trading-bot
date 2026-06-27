# Phase 2b 전략 확장 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`).
> 실행 계획(how). 설계 정본: [`docs/design/phase-2b-more-strategies.md`](../design/phase-2b-more-strategies.md).

**Goal:** 추세/모멘텀 계열 3전략(Donchian 돌파, 시계열 모멘텀, MACD 교차)을 독립 부품으로 추가하고, 기존 3전략과 함께 6개를 같은 BTC 데이터로 비교한다.

**Architecture:** 하네스/데이터/기존 전략 불변. 각 전략은 `strategies/`에 추가, 지표 직접 계산, 고정 -5% 손절.

**Tech Stack:** Python 3.13, pandas<3, backtesting(FractionalBacktest), pytest.

## Global Constraints

- 각 전략: Backtesting.py `Strategy` 상속, `stop_loss_pct=0.05`, `self.buy(sl=price*(1-stop_loss_pct))`(신호 종가 기준 proxy), `use_sentiment=False`(주석 슬롯).
- 지표 직접 계산(헬퍼 함수, pandas-ta 금지). Donchian 채널은 `.shift(1)`로 현재 봉 제외(룩어헤드 방지).
- `run_backtest` 기본값(commission=0.001, spread=0.0, trade_on_close=False) 그대로. **하네스/기존 전략 수정 금지.**
- 가설 문서(`notes/hypothesis_*.md`)는 전략 백테스트 전 작성.
- pytest는 `python -m pytest`(repo 루트), venv: `source .venv/bin/activate`. 손절값 스윕 금지.

---

### Task 1: Donchian 돌파 전략

**Files:** Create `notes/hypothesis_donchian_breakout.md`, `strategies/donchian_breakout.py`; Test `tests/test_trend_strategies.py`

**Interfaces:** Produces `strategies.donchian_breakout.DonchianBreakout` (attrs `entry_n=20, exit_n=10, stop_loss_pct=0.05, use_sentiment=False`).

- [ ] **Step 1: 가설 문서**

`notes/hypothesis_donchian_breakout.md`:
```markdown
# 가설 — Donchian 돌파

- **시장에 대한 믿음**: 일정 기간(20봉) 최고가를 돌파하면 새로운 상승 추세가 시작될 확률이 높다(터틀 트레이딩).
- **진입 규칙**: 종가 > 과거 20봉 최고가(현재 봉 제외) 이고 포지션 없음 → 매수.
- **청산 규칙**: 종가 < 과거 10봉 최저가(현재 봉 제외) → 청산. 또는 신호 캔들 종가 기준 -5% 손절(proxy).
- **버릴 기준**: Phase 3 OOS/민감도에서 Buy & Hold 미달 또는 결과 붕괴 시 폐기.
- **장세 적합/취약**: 강한 추세장 유리, 횡보장에서 거짓 돌파(휩쏘)로 취약.
```

- [ ] **Step 2: 실패 테스트**

`tests/test_trend_strategies.py`:
```python
import numpy as np
import pandas as pd
from backtest import run_backtest
from strategies.donchian_breakout import DonchianBreakout, DONCHIAN_HIGH, DONCHIAN_LOW

STATS_KEYS = ["Return [%]", "Sharpe Ratio", "Max. Drawdown [%]", "# Trades"]


def _oscillating(n=500):
    """진폭 큰 사인파: 추세/모멘텀 전략의 진입·청산을 반복 유발."""
    idx = pd.date_range("2020-01-01", periods=n, freq="1h", tz="UTC")
    close = pd.Series(120 + 40 * np.sin(np.linspace(0, 8 * np.pi, n)), index=idx)
    return pd.DataFrame({"Open": close, "High": close * 1.01, "Low": close * 0.99,
                         "Close": close, "Volume": 1000.0}, index=idx)


def test_donchian_trades_and_stats():
    _, stats = run_backtest(_oscillating(), DonchianBreakout)
    assert stats["# Trades"] > 0
    for k in STATS_KEYS:
        assert k in stats.index


def test_donchian_channels_exclude_current_bar():
    # 룩어헤드 가드: 채널은 현재 봉을 제외한 과거 n봉으로 계산되어야 한다.
    high = [10, 11, 12, 100]
    low = [10, 9, 8, 1]
    assert DONCHIAN_HIGH(high, 3)[-1] == 12   # 현재 봉의 100이 섞이면 안 됨
    assert DONCHIAN_LOW(low, 3)[-1] == 8      # 현재 봉의 1이 섞이면 안 됨
```

- [ ] **Step 3: 실패 확인** — `python -m pytest tests/test_trend_strategies.py -v` → FAIL (import 없음).

- [ ] **Step 4: 구현**

`strategies/donchian_breakout.py`:
```python
import pandas as pd
from backtesting import Strategy


def DONCHIAN_HIGH(high, n):
    return pd.Series(high).rolling(n).max().shift(1).values   # 현재 봉 제외 → 룩어헤드 방지


def DONCHIAN_LOW(low, n):
    return pd.Series(low).rolling(n).min().shift(1).values


class DonchianBreakout(Strategy):
    entry_n = 20
    exit_n = 10
    stop_loss_pct = 0.05
    use_sentiment = False

    def init(self):
        self.upper = self.I(DONCHIAN_HIGH, self.data.High, self.entry_n)
        self.lower = self.I(DONCHIAN_LOW, self.data.Low, self.exit_n)
        # sentiment 자리 (Phase 5):
        # if self.use_sentiment: self.sentiment = self.data.sentiment

    def next(self):
        price = self.data.Close[-1]
        if not self.position:
            if price > self.upper[-1]:                 # 상단 돌파 → 매수
                self.buy(sl=price * (1 - self.stop_loss_pct))
        else:
            if price < self.lower[-1]:                 # 하단 이탈 → 청산
                self.position.close()
```

- [ ] **Step 5: 통과 확인** — `python -m pytest tests/test_trend_strategies.py -v` → 2 passed (trades + 채널 룩어헤드 가드). (#Trades==0이면 `_oscillating` 진폭/주기 조정, 의도 유지.)

- [ ] **Step 6: Commit** — `git add notes/hypothesis_donchian_breakout.md strategies/donchian_breakout.py tests/test_trend_strategies.py && git commit -m "feat: add Donchian breakout strategy with 5% stop"`

---

### Task 2: 시계열 모멘텀 전략

**Files:** Create `notes/hypothesis_ts_momentum.md`, `strategies/ts_momentum.py`; Modify `tests/test_trend_strategies.py`

**Interfaces:** Produces `strategies.ts_momentum.TimeSeriesMomentum` (attrs `lookback=30, stop_loss_pct=0.05, use_sentiment=False`).

- [ ] **Step 1: 가설 문서**

`notes/hypothesis_ts_momentum.md`:
```markdown
# 가설 — 시계열 모멘텀

- **시장에 대한 믿음**: 최근 일정 기간(30봉) 수익률이 양(+)이면 그 추세가 단기적으로 이어진다.
- **진입 규칙**: 과거 30봉 수익률(mom) > 0 이고 포지션 없음 → 매수.
- **청산 규칙**: mom <= 0 → 청산. 또는 신호 캔들 종가 기준 -5% 손절(proxy).
- **버릴 기준**: Phase 3 OOS/민감도에서 Buy & Hold 미달 또는 결과 붕괴 시 폐기.
- **장세 적합/취약**: 추세장 유리, 잦은 방향 전환(횡보)에서 취약.
```

- [ ] **Step 2: 실패 테스트** — `tests/test_trend_strategies.py`에 추가 (`_oscillating` 재사용):
```python
from strategies.ts_momentum import TimeSeriesMomentum


def test_ts_momentum_trades_and_stats():
    _, stats = run_backtest(_oscillating(), TimeSeriesMomentum)
    assert stats["# Trades"] > 0
    for k in STATS_KEYS:
        assert k in stats.index
```

- [ ] **Step 3: 실패 확인** — `python -m pytest tests/test_trend_strategies.py::test_ts_momentum_trades_and_stats -v` → FAIL.

- [ ] **Step 4: 구현**

`strategies/ts_momentum.py`:
```python
import pandas as pd
from backtesting import Strategy


def MOMENTUM(close, n):
    s = pd.Series(close)
    return (s / s.shift(n) - 1).values                 # 과거 n봉 수익률


class TimeSeriesMomentum(Strategy):
    lookback = 30
    stop_loss_pct = 0.05
    use_sentiment = False

    def init(self):
        self.mom = self.I(MOMENTUM, self.data.Close, self.lookback)
        # sentiment 자리 (Phase 5):
        # if self.use_sentiment: self.sentiment = self.data.sentiment

    def next(self):
        price = self.data.Close[-1]
        if not self.position:
            if self.mom[-1] > 0:                        # 모멘텀 양 → 매수
                self.buy(sl=price * (1 - self.stop_loss_pct))
        else:
            if self.mom[-1] <= 0:                       # 모멘텀 음 → 청산
                self.position.close()
```

- [ ] **Step 5: 통과 확인** — `python -m pytest tests/test_trend_strategies.py -v` → 2 passed.

- [ ] **Step 6: Commit** — `git add notes/hypothesis_ts_momentum.md strategies/ts_momentum.py tests/test_trend_strategies.py && git commit -m "feat: add time-series momentum strategy with 5% stop"`

---

### Task 3: MACD 교차 전략

**Files:** Create `notes/hypothesis_macd_cross.md`, `strategies/macd_cross.py`; Modify `tests/test_trend_strategies.py`

**Interfaces:** Produces `strategies.macd_cross.MacdCross` (attrs `fast=12, slow=26, sig=9, stop_loss_pct=0.05, use_sentiment=False`).

- [ ] **Step 1: 가설 문서**

`notes/hypothesis_macd_cross.md`:
```markdown
# 가설 — MACD 교차

- **시장에 대한 믿음**: 단기 EMA와 장기 EMA의 차이(MACD)가 시그널선을 상향 돌파하면 상승 모멘텀이 붙는다.
- **진입 규칙**: MACD선이 시그널선을 위로 교차(crossover) → 매수.
- **청산 규칙**: MACD선이 시그널선을 아래로 교차 → 청산. 또는 신호 캔들 종가 기준 -5% 손절(proxy).
- **버릴 기준**: Phase 3 OOS/민감도에서 Buy & Hold 미달 또는 결과 붕괴 시 폐기.
- **장세 적합/취약**: 추세장 유리, 횡보장에서 잦은 교차(휩쏘)로 취약.
```

- [ ] **Step 2: 실패 테스트** — `tests/test_trend_strategies.py`에 추가:
```python
from strategies.macd_cross import MacdCross


def test_macd_trades_and_stats():
    _, stats = run_backtest(_oscillating(), MacdCross)
    assert stats["# Trades"] > 0
    for k in STATS_KEYS:
        assert k in stats.index
```

- [ ] **Step 3: 실패 확인** — `python -m pytest tests/test_trend_strategies.py::test_macd_trades_and_stats -v` → FAIL.

- [ ] **Step 4: 구현**

`strategies/macd_cross.py`:
```python
import pandas as pd
from backtesting import Strategy
from backtesting.lib import crossover


def MACD_LINE(close, fast, slow):
    s = pd.Series(close)
    return (s.ewm(span=fast, adjust=False).mean()
            - s.ewm(span=slow, adjust=False).mean()).values


def MACD_SIGNAL(close, fast, slow, sig):
    s = pd.Series(close)
    macd = (s.ewm(span=fast, adjust=False).mean()
            - s.ewm(span=slow, adjust=False).mean())
    return macd.ewm(span=sig, adjust=False).mean().values


class MacdCross(Strategy):
    fast = 12
    slow = 26
    sig = 9
    stop_loss_pct = 0.05
    use_sentiment = False

    def init(self):
        self.macd = self.I(MACD_LINE, self.data.Close, self.fast, self.slow)
        self.signal = self.I(MACD_SIGNAL, self.data.Close, self.fast, self.slow, self.sig)
        # sentiment 자리 (Phase 5):
        # if self.use_sentiment: self.sentiment = self.data.sentiment

    def next(self):
        price = self.data.Close[-1]
        if crossover(self.macd, self.signal):          # 상향 교차 → 매수
            if not self.position:
                self.buy(sl=price * (1 - self.stop_loss_pct))
        elif crossover(self.signal, self.macd):        # 하향 교차 → 청산
            if self.position:
                self.position.close()
```

- [ ] **Step 5: 통과 확인** — `python -m pytest tests/test_trend_strategies.py -v` → 3 passed.

- [ ] **Step 6: Commit** — `git add notes/hypothesis_macd_cross.md strategies/macd_cross.py tests/test_trend_strategies.py && git commit -m "feat: add MACD crossover strategy with 5% stop"`

---

### Task 4: 6전략 비교 노트북 + 전략 문서 + 인덱스

**Files:** Create `research/2026-06-27_six_strategy_compare.ipynb`, `docs/strategies/donchian_breakout.md`, `docs/strategies/ts_momentum.md`, `docs/strategies/macd_cross.md`; Modify `docs/strategies/README.md`, `docs/design/README.md`

- [ ] **Step 1: 비교 노트북 작성 + 실행**

`research/2026-06-27_six_strategy_compare.ipynb` 셀:

셀 1:
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
from strategies.donchian_breakout import DonchianBreakout
from strategies.ts_momentum import TimeSeriesMomentum
from strategies.macd_cross import MacdCross
```
셀 2:
```python
df = load_data("BTC/USDT", "1h")
strategies = {
    "SMA(trend)": SmaCross, "RSI(rev)": RsiReversion, "Bollinger(rev)": BollingerReversion,
    "Donchian(brk)": DonchianBreakout, "TSMom(mom)": TimeSeriesMomentum, "MACD(trend)": MacdCross,
}
runs = {name: run_backtest(df, s) for name, s in strategies.items()}
keys = ["Return [%]", "Buy & Hold Return [%]", "Sharpe Ratio", "Max. Drawdown [%]", "Win Rate [%]", "# Trades"]
table = pd.DataFrame({name: stats[keys] for name, (bt, stats) in runs.items()})
table
```
셀 3:
```python
import matplotlib.pyplot as plt
plt.figure(figsize=(12, 6))
for name, (bt, stats) in runs.items():
    eq = stats["_equity_curve"]["Equity"]
    plt.plot(eq.index, eq.values, label=name)
plt.title("6전략 자본 곡선 비교 (BTC/USDT 1h)")
plt.ylabel("Equity [$]"); plt.legend(); plt.grid(True); plt.show()
```

실행: `jupyter nbconvert --to notebook --execute --inplace research/2026-06-27_six_strategy_compare.ipynb`. 확인: 6전략 표(#Trades>0) + 곡선 6개. 셀 2 실제 숫자를 다음 Step 문서에 사용.

- [ ] **Step 2: 전략 설명 문서 3개** — `docs/strategies/{donchian_breakout,ts_momentum,macd_cross}.md`를 [`sma_cross.md`](../../docs/strategies/sma_cross.md) 구조(요약·믿음·지표·규칙·파라미터·장세·결과·관련)로 작성. **결과는 셀 2 실제 숫자**, 상단에 해당 `notes/hypothesis_*.md` 링크.

- [ ] **Step 3: 인덱스 갱신** — `docs/strategies/README.md` 표에 3행 추가(Donchian=돌파, TSMom=모멘텀, MACD=추세; 상태=검증 중). `docs/design/README.md`에 phase-2b 행 추가 + 링크.

- [ ] **Step 4: 출력 비우고 Commit** — `jupyter nbconvert --clear-output --inplace research/2026-06-27_six_strategy_compare.ipynb && git add research/ docs/ notes/ && git commit -m "docs: add 6-strategy comparison notebook and trend strategy docs"`

---

## 완료 기준

1. `python -m pytest -q` — 전체 통과(기존 9 + 신규 4 = 13: 전략 3 + Donchian 채널 가드 1).
2. 비교 노트북: 6전략 표(#Trades>0) + 곡선 6개.
3. 가설 문서 3개, 전략 설명 문서 3개, 인덱스 갱신.
4. 하네스/기존 전략 불변, 손절 -5% 적용, sentiment 슬롯 유지.

## Self-Review 메모
- 설계 §2→T1~T3(각 전략), §3→T4(비교/문서). 매핑 완료.
- 룩어헤드: Donchian `.shift(1)`, 나머지 `[-1]`만 사용 + `trade_on_close=False`.
- 명칭 일관성: `DonchianBreakout`/`TimeSeriesMomentum`/`MacdCross`, 헬퍼 `DONCHIAN_HIGH/LOW`,`MOMENTUM`,`MACD_LINE/SIGNAL`.
