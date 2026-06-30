# Phase 5 — sentiment 오버레이 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fear&Greed 지수를 수집·정렬하는 데이터 도구와, 검증된 추세전략(Regime/Keltner)에 "극탐욕이면 현금" 필터를 붙이는 공유 헬퍼를 만들어 baseline vs +sentiment 백테스트 비교가 가능하게 한다.

**Architecture:** 하네스/다른 전략 불변. 신규 `sentiment.py`(F&G 수집+OHLCV 정렬), 신규 `strategies/sentiment_filter.py`(공유 필터 규칙), `RegimeFilter`/`KeltnerBreakout`의 `use_sentiment` 자리 구현. 효과는 노트북에서 baseline vs +sentiment로 판정.

**Tech Stack:** Python 3.13, pandas(>=2,<3), Backtesting.py, pytest. `.venv/bin/python -m pytest`.

## Global Constraints
- 하네스(`backtest.py`)·다른 전략 파일 수정 금지. Regime/Keltner는 **`use_sentiment` 자리만** 손댄다.
- **임계 75 고정**(alternative.me "Extreme Greed" 밴드). 튜닝/sweep 금지.
- 극탐욕(F&G≥75)이면 **현금**(보유 청산 + 신규 진입 차단). **숏 아님.**
- 룩어헤드 차단: F&G의 날짜 D 값은 **D+1부터** 사용(인덱스 +1일 shift) → 4h봉에 **ffill** → 신호는 완성봉, 체결 다음봉(하네스 기본).
- sentiment 컬럼은 **numeric float**. **결측 = 필터 off**(NaN, baseline처럼 동작). 결측 구간 버리지 않음.
- 테스트는 synthetic만(data/·네트워크 비의존). 기존 전체 테스트 회귀 없게(현재 57 passed).

---

### Task 1: F&G 데이터 도구 (`sentiment.py`)

**Files:**
- Create: `sentiment.py`
- Test: `tests/test_sentiment.py` (신규)

**Interfaces:**
- Produces:
  - `fetch_fng(limit=0) -> pd.Series` (일간 UTC 자정 인덱스 → 0~100 float; 네트워크, 유닛테스트 안 함)
  - `attach_fng(df: pd.DataFrame, fng: pd.Series) -> pd.DataFrame` (df에 `sentiment` 컬럼 채워 반환)
  - `save_fng(s, path="data/fng.parquet") -> str`

- [ ] **Step 1: Write the failing test** — `tests/test_sentiment.py`

```python
import pandas as pd
from sentiment import attach_fng


def test_attach_fng_lags_one_day_ffill_and_float():
    # F&G: 01-01=10, 01-02=90 (일간 UTC 자정)
    fng = pd.Series([10.0, 90.0],
                    index=pd.to_datetime(["2021-01-01", "2021-01-02"], utc=True))
    idx = pd.date_range("2021-01-01", "2021-01-03 20:00", freq="4h", tz="UTC")
    df = pd.DataFrame({"Open": 1.0, "High": 1.0, "Low": 1.0, "Close": 1.0, "Volume": 1.0}, index=idx)

    out = attach_fng(df, fng)

    # 01-01 봉: 01-01 값은 01-02부터 사용 → 아직 없음 → NaN (필터 off)
    assert pd.isna(out.loc["2021-01-01 12:00", "sentiment"])
    # 01-02 봉: 01-01 값(01-02 00:00부터 사용) → 10
    assert out.loc["2021-01-02 12:00", "sentiment"] == 10.0
    # 01-03 봉: 01-02 값(01-03 00:00부터 사용) → 90
    assert out.loc["2021-01-03 12:00", "sentiment"] == 90.0
    assert out["sentiment"].dtype == "float64"
    # 원본 df는 안 바뀜
    assert "sentiment" not in df.columns
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_sentiment.py -v`
Expected: FAIL — `ImportError: cannot import name 'attach_fng' from 'sentiment'` (모듈 없음).

- [ ] **Step 3: Implement** — `sentiment.py`

```python
import json
import urllib.request

import pandas as pd


def fetch_fng(limit=0):
    """alternative.me Fear&Greed 일간 지수 → Series(일간 UTC 자정 → 0~100 float)."""
    url = f"https://api.alternative.me/fng/?limit={limit}&format=json"
    with urllib.request.urlopen(url, timeout=30) as r:
        data = json.load(r)["data"]
    idx = pd.to_datetime([int(x["timestamp"]) for x in data], unit="s", utc=True)
    return pd.Series([float(x["value"]) for x in data], index=idx).sort_index()


def attach_fng(df, fng):
    """OHLCV df의 sentiment 컬럼을 F&G로 채워 반환.
    D 값은 D+1부터 사용(인덱스 +1일 shift) → df 인덱스로 ffill → numeric float.
    df 시작 전 결측은 NaN(= 필터 off). 원본 df는 변경하지 않는다."""
    avail = fng.sort_index().copy()
    avail.index = avail.index.shift(1, freq="D")               # D 값은 D+1 00:00 UTC부터 사용 가능
    s = avail.reindex(avail.index.union(df.index)).ffill().reindex(df.index)
    out = df.copy()
    out["sentiment"] = pd.to_numeric(s, errors="coerce").astype("float64")
    return out


def save_fng(s, path="data/fng.parquet"):
    import os
    os.makedirs("data", exist_ok=True)
    s.to_frame("fng").to_parquet(path)
    return path
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_sentiment.py -v`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add sentiment.py tests/test_sentiment.py
git commit -m "feat(sentiment): Fear&Greed 수집 + OHLCV 정렬(attach_fng, t-1 lag/ffill/float/결측NaN)"
```

---

### Task 2: 공유 필터 헬퍼 + Regime/Keltner 배선

**Files:**
- Create: `strategies/sentiment_filter.py`
- Modify: `strategies/regime_filter.py`, `strategies/keltner_breakout.py`
- Test: `tests/test_sentiment_filter.py` (신규)

**Interfaces:**
- Consumes: `from sentiment import attach_fng` (테스트 데이터 준비용; 전략 자체는 `self.data.sentiment` 컬럼만 읽음)
- Produces: `sentiment_risk_off(use_sentiment: bool, sentiment_value: float, threshold: float = 75) -> bool` (극탐욕이면 True=현금)

- [ ] **Step 1: Write the failing test** — `tests/test_sentiment_filter.py`

```python
import pandas as pd
from backtest import run_backtest
from strategies.sentiment_filter import sentiment_risk_off
from strategies.regime_filter import RegimeFilter
from strategies.keltner_breakout import KeltnerBreakout


def _flat_then_ramp(sentiment, flat=220, ramp=100):
    # flat 구간(추세 없음) 뒤 ramp(상승) → Regime·Keltner 둘 다 매수·수익 내는 합성 데이터
    close = pd.Series([100.0] * flat + [100.0 + i for i in range(1, ramp + 1)], dtype="float64")
    idx = pd.date_range("2021-01-01", periods=len(close), freq="4h", tz="UTC")
    close.index = idx
    return pd.DataFrame({"Open": close, "High": close * 1.01, "Low": close * 0.99,
                         "Close": close, "Volume": 1000.0, "sentiment": float(sentiment)}, index=idx)


def test_sentiment_risk_off_rule():
    assert sentiment_risk_off(False, 90) is False          # 스위치 off → 항상 False
    assert sentiment_risk_off(True, 90) is True            # 극탐욕 → 현금
    assert sentiment_risk_off(True, 50) is False           # 탐욕 아님 → 정상
    assert sentiment_risk_off(True, 75) is True            # 경계 ≥75 포함
    assert sentiment_risk_off(True, float("nan")) is False # 결측 → 필터 off


def test_regime_always_greed_stays_cash():
    df = _flat_then_ramp(sentiment=90.0)                   # 전 구간 극탐욕
    _, on = run_backtest(df, RegimeFilter, use_sentiment=True)
    _, off = run_backtest(df, RegimeFilter, use_sentiment=False)
    assert round(on["Return [%]"], 6) == 0.0               # 전부 차단 → 현금, 무수익
    assert off["Return [%]"] > 0                           # baseline은 상승 탑승


def test_regime_no_greed_matches_baseline():
    df = _flat_then_ramp(sentiment=50.0)                   # 극탐욕 없음
    _, on = run_backtest(df, RegimeFilter, use_sentiment=True)
    _, off = run_backtest(df, RegimeFilter, use_sentiment=False)
    assert on["Return [%]"] == off["Return [%]"]           # 필터 비발동 → 동일


def test_keltner_always_greed_stays_cash():
    df = _flat_then_ramp(sentiment=90.0)
    _, on = run_backtest(df, KeltnerBreakout, use_sentiment=True)
    _, off = run_backtest(df, KeltnerBreakout, use_sentiment=False)
    assert round(on["Return [%]"], 6) == 0.0
    assert off["Return [%]"] > 0


def test_keltner_no_greed_matches_baseline():
    df = _flat_then_ramp(sentiment=50.0)
    _, on = run_backtest(df, KeltnerBreakout, use_sentiment=True)
    _, off = run_backtest(df, KeltnerBreakout, use_sentiment=False)
    assert on["Return [%]"] == off["Return [%]"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_sentiment_filter.py -v`
Expected: FAIL — `ImportError: cannot import name 'sentiment_risk_off'` (헬퍼 없음).

- [ ] **Step 3a: Implement helper** — `strategies/sentiment_filter.py`

```python
import pandas as pd


def sentiment_risk_off(use_sentiment, sentiment_value, threshold=75):
    """극탐욕(F&G ≥ threshold)이면 True(=현금/리스크오프). 스위치 off나 결측이면 False."""
    if not use_sentiment:
        return False
    if sentiment_value is None or pd.isna(sentiment_value):
        return False                      # 결측 = 필터 off (baseline처럼)
    return bool(sentiment_value >= threshold)
```

- [ ] **Step 3b: Wire into `strategies/regime_filter.py`**

Add import + `sentiment_threshold` 클래스 속성, `next()` 맨 앞에 필터 가드. 최종 형태:
```python
import pandas as pd
from backtesting import Strategy
from strategies.sentiment_filter import sentiment_risk_off


def SMA(series, n):
    return pd.Series(series).rolling(n).mean().values


class RegimeFilter(Strategy):
    sma_n = 200
    stop_loss_pct = 0.05
    use_sentiment = False
    sentiment_threshold = 75

    def init(self):
        self.sma = self.I(SMA, self.data.Close, self.sma_n)

    def next(self):
        if sentiment_risk_off(self.use_sentiment, self.data.sentiment[-1], self.sentiment_threshold):
            if self.position:
                self.position.close()       # 극탐욕 → 현금(청산), 신규 진입도 안 함
            return
        price = self.data.Close[-1]
        if not self.position:
            if price > self.sma[-1]:                # 장기 MA 위 → 보유
                self.buy(sl=price * (1 - self.stop_loss_pct))
        elif price < self.sma[-1]:                  # 장기 MA 아래 → 현금
            self.position.close()
```

- [ ] **Step 3c: Wire into `strategies/keltner_breakout.py`**

동일 패턴. import + `sentiment_threshold = 75` + `next()` 맨 앞 가드. 최종 `next()`/헤더:
```python
import pandas as pd
from backtesting import Strategy
from strategies.sentiment_filter import sentiment_risk_off


def EMA(series, n):
    return pd.Series(series).ewm(span=n, adjust=False).mean().values


def ATR(high, low, close, n):
    high, low, close = pd.Series(high), pd.Series(low), pd.Series(close)
    prev = close.shift(1)
    tr = pd.concat([high - low, (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean().values   # Wilder ATR


class KeltnerBreakout(Strategy):
    ema_n = 20
    atr_n = 20
    atr_mult = 2.0
    stop_loss_pct = 0.05
    use_sentiment = False
    sentiment_threshold = 75

    def init(self):
        self.ema = self.I(EMA, self.data.Close, self.ema_n)
        self.atr = self.I(ATR, self.data.High, self.data.Low, self.data.Close, self.atr_n)

    def next(self):
        if sentiment_risk_off(self.use_sentiment, self.data.sentiment[-1], self.sentiment_threshold):
            if self.position:
                self.position.close()
            return
        price = self.data.Close[-1]
        upper = self.ema[-1] + self.atr_mult * self.atr[-1]
        if not self.position:
            if price > upper:                       # 상단 밴드 돌파 → 매수
                self.buy(sl=price * (1 - self.stop_loss_pct))
        elif price < self.ema[-1]:                  # 중심선(EMA) 하향 이탈 → 청산
            self.position.close()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_sentiment_filter.py -v`
Expected: PASS (5 passed). 전체 회귀: `.venv/bin/python -m pytest -q` → 모두 PASS.

- [ ] **Step 5: Commit**

```bash
git add strategies/sentiment_filter.py strategies/regime_filter.py strategies/keltner_breakout.py tests/test_sentiment_filter.py
git commit -m "feat(sentiment): 극탐욕 회피 필터 헬퍼 + Regime/Keltner use_sentiment 배선"
```
