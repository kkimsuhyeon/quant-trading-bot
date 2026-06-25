# Phase 0 + 1 실험실 구축 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **이 문서는 실행 계획(how-to-build)이지 설계 정본이 아니다.** 설계 정본은
> [`docs/design/phase-0-1-lab.md`](../design/phase-0-1-lab.md). 설계 결정이 바뀌면 그 문서를 먼저 고친다.

**Goal:** ccxt로 BTC/USDT 캔들을 수집·저장하고, Backtesting.py 얇은 하네스에 SMA 교차 전략을 꽂아 파이프라인을 끝까지 한 번 관통시킨다(hello world).

**Architecture:** 수집(`fetch.py`)과 백테스트(`backtest.py`)를 분리하고, 하네스는 고정·전략은 부품(`strategies/`)으로 둔다. 경계 로직(데이터 정리·컬럼 변환·전략 신호)은 합성 데이터로 단위 테스트하고, 라이브 수집·노트북은 수동 smoke로 검증한다.

**Tech Stack:** Python, ccxt, pandas, pyarrow(parquet), Backtesting.py, pytest, Jupyter.

## Global Constraints

모든 태스크의 요구사항에 아래가 암묵적으로 포함된다 (스펙에서 그대로 옮김):

- 자산 **BTC/USDT**, 시간 단위 **1h + 4h**, 데이터 **약 3년**.
- 저장: **parquet(주) + csv(확인용)**, `data/` 디렉터리 (**git 제외**).
- 거래 비용: `commission=0.001` (**한 방향당 0.1%**, 거래소 수수료). `spread=0.0` (**슬리피지 미반영**, Phase 4 실측까지 보류).
- 룩어헤드 방지: `trade_on_close=False`. `next()`에서는 **현재까지 공개된 완성 캔들만 사용**, 시장가 주문은 **다음 캔들 시가**에 체결.
- 소수점 거래: **`FractionalBacktest` 사용** (`from backtesting.lib import FractionalBacktest`).
- sentiment: 데이터에 **컬럼 자리(`pd.NA`)** + 전략에 **`use_sentiment=False` 스위치 자리**. **구현은 하지 않는다**(Phase 5).
- 리스크 레이어(손절·포지션 사이징·킬스위치)와 가설 문서(`notes/hypothesis_*.md`): **이번엔 제외**(Phase 2부터).
- SMA 파라미터: `fast=20`, `slow=50`.
- 모든 시간 인덱스는 **timezone-aware UTC**.

---

### Task 1: 프로젝트 환경

**Files:**
- Create: `requirements.txt`

**Interfaces:**
- Consumes: (없음)
- Produces: 설치된 가상환경 + import 가능한 라이브러리.

- [ ] **Step 1: `requirements.txt` 작성**

```
ccxt
pandas
pyarrow
backtesting
pytest
jupyter
```

- [ ] **Step 2: 가상환경 생성 + 설치**

Run:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

- [ ] **Step 3: import 확인 (설치 smoke)**

Run:
```bash
python -c "import ccxt, pandas, pyarrow, backtesting, pytest; from backtesting.lib import FractionalBacktest; print('ok')"
```
Expected: `ok` 출력 (에러 없음).

- [ ] **Step 4: Commit**

```bash
git add requirements.txt
git commit -m "chore: add Python dependencies for Phase 0+1"
```

---

### Task 2: 데이터 정리 순수 함수 (`clean_ohlcv`)

ccxt가 준 raw 캔들 행을 정리해 깨끗한 DataFrame으로 만드는 **순수 함수**. 네트워크 없이 단위 테스트한다.

**Files:**
- Create: `fetch.py`
- Test: `tests/test_fetch.py`

**Interfaces:**
- Consumes: (없음)
- Produces: `clean_ohlcv(rows: list[list]) -> pd.DataFrame`
  - 입력: ccxt 행 리스트 `[[ts_ms, open, high, low, close, volume], ...]`
  - 출력: 컬럼 `["open","high","low","close","volume","sentiment"]`, 인덱스 `timestamp`(UTC tz-aware), 중복 제거 + 시간 오름차순, `sentiment`는 전부 `pd.NA`.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_fetch.py`:
```python
import pandas as pd
from fetch import clean_ohlcv


def _rows(ts_list):
    return [[ts, 10, 12, 9, 11, 100] for ts in ts_list]


def test_clean_ohlcv_schema():
    df = clean_ohlcv(_rows([0, 3600_000, 7200_000]))
    assert list(df.columns) == ["open", "high", "low", "close", "volume", "sentiment"]
    assert df.index.name == "timestamp"
    assert str(df.index.tz) == "UTC"


def test_clean_ohlcv_dedups_and_sorts():
    df = clean_ohlcv(_rows([7200_000, 0, 0, 3600_000]))  # 중복(0) + 역순
    ts = [int(t.timestamp() * 1000) for t in df.index]
    assert ts == [0, 3600_000, 7200_000]


def test_clean_ohlcv_sentiment_is_na():
    df = clean_ohlcv(_rows([0, 3600_000]))
    assert df["sentiment"].isna().all()
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/test_fetch.py -v`
Expected: FAIL (`ImportError: cannot import name 'clean_ohlcv'` 또는 모듈 없음).

- [ ] **Step 3: 최소 구현**

`fetch.py`:
```python
import pandas as pd

OHLCV_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]


def clean_ohlcv(rows):
    df = pd.DataFrame(rows, columns=OHLCV_COLUMNS)
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df.drop_duplicates("timestamp").sort_values("timestamp")
    df["sentiment"] = pd.NA
    return df.set_index("timestamp")
```

- [ ] **Step 4: 통과 확인**

Run: `pytest tests/test_fetch.py -v`
Expected: 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add fetch.py tests/test_fetch.py
git commit -m "feat: add clean_ohlcv data normalization"
```

---

### Task 3: 페이지네이션 + 라이브 수집 + 저장

ccxt는 호출당 ~1000개만 주므로 루프로 이어붙인다. 루프 로직은 **가짜 거래소로 단위 테스트**하고, 실제 바이낸스 수집은 **수동 smoke**로 검증한다(네트워크 의존이라 기본 pytest와 분리).

**Files:**
- Modify: `fetch.py`
- Test: `tests/test_fetch.py`

**Interfaces:**
- Consumes: `clean_ohlcv` (Task 2)
- Produces:
  - `fetch_paginated(exchange, symbol, timeframe, since, limit=1000) -> list[list]` — `since` 이후 캔들을 limit개씩 받아 이어붙인 raw 행 리스트.
  - `fetch_ohlcv(symbol="BTC/USDT", timeframe="1h", years=3, exchange=None) -> pd.DataFrame` — 라이브 수집 + 정리 + **미완성 마지막 캔들 제거**.
  - `save(df, symbol, timeframe, data_dir="data") -> str` — parquet + csv 저장, 파일 베이스명 반환.

- [ ] **Step 1: 실패하는 테스트 작성 (페이지네이션, 가짜 거래소)**

`tests/test_fetch.py`에 추가:
```python
from fetch import fetch_paginated


class FakeExchange:
    """since 이후 캔들을 limit개씩 돌려주는 가짜 거래소."""

    def __init__(self, rows):
        self._rows = sorted(rows)  # [[ts, o, h, l, c, v], ...]

    def fetch_ohlcv(self, symbol, timeframe, since, limit):
        return [r for r in self._rows if r[0] >= since][:limit]


def test_fetch_paginated_stitches_all_batches():
    rows = [[i * 3600_000, 1, 1, 1, 1, 1] for i in range(2500)]  # 2500개
    out = fetch_paginated(FakeExchange(rows), "BTC/USDT", "1h", since=0, limit=1000)
    assert len(out) == 2500                       # 누락 없이 전부
    assert [r[0] for r in out] == [r[0] for r in rows]  # 순서 유지
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/test_fetch.py::test_fetch_paginated_stitches_all_batches -v`
Expected: FAIL (`cannot import name 'fetch_paginated'`).

- [ ] **Step 3: 최소 구현 (페이지네이션 + 라이브 + 저장)**

`fetch.py`에 추가 (상단에 `import ccxt` 추가):
```python
import ccxt  # 파일 상단 import 블록에 추가


def fetch_paginated(exchange, symbol, timeframe, since, limit=1000):
    all_rows = []
    while True:
        batch = exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=limit)
        if not batch:
            break
        all_rows += batch
        since = batch[-1][0] + 1          # 다음 페이지: 마지막 캔들 다음부터
        if len(batch) < limit:
            break                          # 더 받을 게 없음
    return all_rows


def fetch_ohlcv(symbol="BTC/USDT", timeframe="1h", years=3, exchange=None):
    exchange = exchange or ccxt.binance()
    since = exchange.milliseconds() - years * 365 * 24 * 60 * 60 * 1000
    rows = fetch_paginated(exchange, symbol, timeframe, since)
    df = clean_ohlcv(rows)
    if len(df) > 0:
        df = df.iloc[:-1]                  # 미완성 마지막 캔들 제거
    return df


def save(df, symbol, timeframe, data_dir="data"):
    import os
    os.makedirs(data_dir, exist_ok=True)
    name = f"{symbol.replace('/', '_')}_{timeframe}"
    df.to_parquet(f"{data_dir}/{name}.parquet")
    df.to_csv(f"{data_dir}/{name}.csv")
    return name


if __name__ == "__main__":
    for tf in ["1h", "4h"]:
        df = fetch_ohlcv("BTC/USDT", tf, years=3)
        save(df, "BTC/USDT", tf)
        print(f"{tf}: {len(df)} candles, {df.index[0]} ~ {df.index[-1]}")
```

- [ ] **Step 4: 단위 테스트 통과 확인**

Run: `pytest tests/test_fetch.py -v`
Expected: 4 tests PASS.

- [ ] **Step 5: 수동 smoke (실제 수집) — 네트워크 필요, 선택 실행**

Run: `python fetch.py`
Expected:
- `1h: <약 26000> candles, <시작일시> ~ <끝일시>` 및 `4h: <약 6500> candles, ...` 출력.
- `data/BTC_USDT_1h.parquet`, `.csv`, `data/BTC_USDT_4h.parquet`, `.csv` 4개 파일 생성.
- 캔들 수가 약 3년치(1h ≈ 26k, 4h ≈ 6.5k)인지 눈으로 확인.

> 이 smoke는 거래소·네트워크 상태에 따라 흔들리므로 CI/기본 pytest에 넣지 않는다. 수동으로만 돌린다.

- [ ] **Step 6: Commit**

```bash
git add fetch.py tests/test_fetch.py
git commit -m "feat: add paginated ccxt fetch and parquet/csv save"
```

---

### Task 4: 하네스 데이터 로딩 (`load_data`)

우리 소문자 컬럼을 Backtesting.py가 요구하는 대문자 `OHLCV`로 변환한다. 변환 로직은 순수 함수로 빼서 단위 테스트한다.

**Files:**
- Create: `backtest.py`
- Test: `tests/test_backtest.py`

**Interfaces:**
- Consumes: (없음 — 파일은 Task 3 산출물 `data/*.parquet`를 읽지만 단위테스트는 합성 df 사용)
- Produces:
  - `_to_backtesting_format(df: pd.DataFrame) -> pd.DataFrame` — `open/high/low/close/volume` → `Open/High/Low/Close/Volume` rename, `sentiment` 및 인덱스 보존.
  - `load_data(symbol="BTC/USDT", timeframe="1h", data_dir="data") -> pd.DataFrame` — parquet 읽어 위 형식으로 반환.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_backtest.py`:
```python
import pandas as pd
from backtest import _to_backtesting_format


def test_to_backtesting_format_renames_and_keeps_sentiment():
    df = pd.DataFrame({
        "open": [1.0], "high": [2.0], "low": [0.5], "close": [1.5],
        "volume": [100.0], "sentiment": [pd.NA],
    })
    out = _to_backtesting_format(df)
    assert {"Open", "High", "Low", "Close", "Volume"} <= set(out.columns)
    assert not ({"open", "high", "low", "close", "volume"} & set(out.columns))
    assert "sentiment" in out.columns
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/test_backtest.py -v`
Expected: FAIL (`cannot import name '_to_backtesting_format'`).

- [ ] **Step 3: 최소 구현**

`backtest.py`:
```python
import pandas as pd


def _to_backtesting_format(df):
    return df.rename(columns={
        "open": "Open", "high": "High", "low": "Low",
        "close": "Close", "volume": "Volume",
    })


def load_data(symbol="BTC/USDT", timeframe="1h", data_dir="data"):
    name = f"{symbol.replace('/', '_')}_{timeframe}"
    df = pd.read_parquet(f"{data_dir}/{name}.parquet")
    return _to_backtesting_format(df)
```

- [ ] **Step 4: 통과 확인**

Run: `pytest tests/test_backtest.py -v`
Expected: 1 test PASS.

- [ ] **Step 5: Commit**

```bash
git add backtest.py tests/test_backtest.py
git commit -m "feat: add harness load_data with OHLCV column mapping"
```

---

### Task 5: SMA 전략 + `run_backtest` (FractionalBacktest)

전략 부품과 하네스 실행 함수를 만들고, 합성 데이터로 **거래가 실제로 발생(`# Trades > 0`)**하고 **stats 키가 존재**하는지 단위 테스트한다.

**Files:**
- Create: `strategies/__init__.py` (빈 파일)
- Create: `strategies/sma_cross.py`
- Modify: `backtest.py`
- Test: `tests/test_backtest.py`

**Interfaces:**
- Consumes: `_to_backtesting_format`은 불필요 (테스트는 이미 대문자 합성 df 사용).
- Produces:
  - `strategies.sma_cross.SmaCross` — Backtesting.py `Strategy` 서브클래스. 속성 `fast=20`, `slow=50`, `use_sentiment=False`.
  - `run_backtest(df, strategy, cash=10_000, commission=0.001, **params) -> (bt, stats)` — `FractionalBacktest`로 실행, `(Backtest 인스턴스, stats Series)` 반환.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_backtest.py`에 추가:
```python
import numpy as np
from backtest import run_backtest
from strategies.sma_cross import SmaCross


def _synthetic(n=300):
    idx = pd.date_range("2020-01-01", periods=n, freq="1h", tz="UTC")
    ramp = np.concatenate([np.linspace(100, 200, n // 2),
                           np.linspace(200, 100, n - n // 2)])  # 상승 후 하락 → 교차 유발
    close = pd.Series(ramp, index=idx)
    return pd.DataFrame({
        "Open": close, "High": close * 1.01, "Low": close * 0.99,
        "Close": close, "Volume": 1000.0,
    }, index=idx)


def test_sma_cross_produces_trades():
    _, stats = run_backtest(_synthetic(), SmaCross)
    assert stats["# Trades"] > 0


def test_run_backtest_exposes_expected_stats():
    _, stats = run_backtest(_synthetic(), SmaCross)
    for key in ["Return [%]", "Sharpe Ratio", "Max. Drawdown [%]", "Win Rate [%]", "# Trades"]:
        assert key in stats.index
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/test_backtest.py -v`
Expected: FAIL (`cannot import name 'SmaCross'` / `cannot import name 'run_backtest'`).

- [ ] **Step 3: 전략 구현**

`strategies/__init__.py`: (빈 파일)

`strategies/sma_cross.py`:
```python
import pandas as pd
from backtesting import Strategy
from backtesting.lib import crossover


def SMA(series, n):
    return pd.Series(series).rolling(n).mean().values


class SmaCross(Strategy):
    fast = 20                # 단기 이평
    slow = 50                # 장기 이평
    use_sentiment = False    # sentiment on/off 스위치 자리 (구현 Phase 5)

    def init(self):
        close = self.data.Close
        self.sma_fast = self.I(SMA, close, self.fast)
        self.sma_slow = self.I(SMA, close, self.slow)
        # sentiment 자리 (Phase 5):
        # if self.use_sentiment:
        #     self.sentiment = self.data.sentiment

    def next(self):
        # 룩어헤드 방지: 현재까지 공개된 완성 캔들만 사용, 주문은 다음 봉 시가 체결.
        if crossover(self.sma_fast, self.sma_slow):     # 골든크로스 → 매수
            self.buy()
        elif crossover(self.sma_slow, self.sma_fast):   # 데드크로스 → 청산
            self.position.close()
        # sentiment 자리 (Phase 5, 비활성):
        # if self.use_sentiment:
        #     score = self.sentiment[-1]
        #     ...
```

- [ ] **Step 4: 하네스 실행 함수 구현**

`backtest.py` 상단 import에 추가하고 함수 추가:
```python
from backtesting.lib import FractionalBacktest  # 파일 상단 import 블록에 추가


def run_backtest(df, strategy, cash=10_000, commission=0.001, **params):
    bt = FractionalBacktest(
        df, strategy,
        cash=cash,
        commission=commission,   # 0.1% per side (거래소 수수료)
        spread=0.0,              # 슬리피지 미반영 (Phase 4 실측까지 보류)
        trade_on_close=False,    # 다음 봉 시가 체결 (룩어헤드 방지)
    )
    stats = bt.run(**params)
    return bt, stats


if __name__ == "__main__":
    from strategies.sma_cross import SmaCross
    df = load_data("BTC/USDT", "1h")
    bt, stats = run_backtest(df, SmaCross)
    print(stats)
```

- [ ] **Step 5: 통과 확인**

Run: `pytest tests/test_backtest.py -v`
Expected: 3 tests PASS (`test_to_backtesting_format...`, `test_sma_cross_produces_trades`, `test_run_backtest_exposes_expected_stats`).

- [ ] **Step 6: 전체 테스트 + 실제 데이터 smoke**

Run: `pytest -v` (전체 단위 테스트 통과)
Run (Task 3 smoke로 `data/`가 채워져 있을 때, 선택): `python backtest.py`
Expected: `print(stats)`에 `Return [%] / Sharpe Ratio / Max. Drawdown [%] / Win Rate [%] / # Trades`가 출력되고 `# Trades > 0`.

- [ ] **Step 7: Commit**

```bash
git add strategies/__init__.py strategies/sma_cross.py backtest.py tests/test_backtest.py
git commit -m "feat: add SMA cross strategy and FractionalBacktest harness"
```

---

### Task 6: 리서치 노트북 (수동 시각화)

파이프라인 결과를 눈으로 확인하는 노트북. 노트북은 TDD 대상이 아니라 **체크리스트로 검증**한다. 커밋은 **출력 비운 상태**로 한다(이번은 hello world smoke이므로 차트를 보존할 필요 없음; 실제 연구 노트북은 Phase 2부터 출력 보존).

**Files:**
- Create: `research/2026-06-25_hello_world.ipynb`

**Interfaces:**
- Consumes: `backtest.load_data`, `backtest.run_backtest`, `strategies.sma_cross.SmaCross`, `data/BTC_USDT_1h.parquet`.
- Produces: (없음 — 수동 확인용)

- [ ] **Step 1: 노트북 생성 (셀 내용)**

`research/2026-06-25_hello_world.ipynb`에 아래 셀들을 만든다:

셀 1:
```python
import sys; sys.path.append("..")  # 노트북에서 레포 루트 모듈 import
from backtest import load_data, run_backtest
from strategies.sma_cross import SmaCross
```
셀 2:
```python
df = load_data("BTC/USDT", "1h")
df.tail()        # 데이터가 어떻게 생겼는지 확인 (sentiment 컬럼이 NA로 존재하는지도)
```
셀 3:
```python
bt, stats = run_backtest(df, SmaCross)
stats            # 수익률·샤프·MDD·승률·거래수 확인
```
셀 4:
```python
bt.plot()        # 수익곡선 + 매매 시점 차트
```

- [ ] **Step 2: 실행 후 체크리스트 확인 (수동)**

노트북을 위에서 아래로 실행하고 다음을 확인:
- [ ] 셀 2: `df`에 `Open/High/Low/Close/Volume` + `sentiment`(NA) 컬럼이 보이고, 인덱스가 UTC 시각이다.
- [ ] 셀 3: `stats`에 `# Trades > 0`, `Return [%] / Sharpe Ratio / Max. Drawdown [%] / Win Rate [%]`가 값으로 나온다.
- [ ] 셀 4: 수익곡선 차트와 매수/매도 마커가 그려진다.

- [ ] **Step 3: 출력 비우고 Commit**

```bash
jupyter nbconvert --clear-output --inplace research/2026-06-25_hello_world.ipynb
git add research/2026-06-25_hello_world.ipynb
git commit -m "docs: add hello-world research notebook"
```

---

## 완료 기준 (이 사이클 전체)

1. `pytest -v` — 전체 단위 테스트 통과 (Task 2,3,4,5).
2. `python fetch.py` — BTC/USDT 1h·4h 약 3년치 캔들 수집 + 파일 4개 생성 (수동 smoke).
3. `python backtest.py` — stats 출력 + `# Trades > 0` (수동 smoke).
4. 노트북 체크리스트 3개 통과 (Task 6).
5. sentiment 컬럼 자리 + `use_sentiment` 스위치 존재(구현 X), `trade_on_close=False` 유지.

## Self-Review 메모

- **스펙 커버리지**: 설계서 §4(fetch)→T2/T3, §5(하네스)→T4/T5, §6(전략+sentiment)→T5, §7(룩어헤드)→T5 next()+`trade_on_close=False`, §8(비용)→T5 `commission/spread`, §10(검증)→완료 기준. 모두 매핑됨.
- **placeholder 없음**: 모든 코드/명령/기대출력 구체화. (수집 캔들 "약 26k/6.5k"는 시장 데이터라 근사 범위로 표기 — 정확값이 아니라 sanity check 용도.)
- **타입 일관성**: `clean_ohlcv`/`fetch_paginated`/`fetch_ohlcv`/`save`/`_to_backtesting_format`/`load_data`/`run_backtest`/`SmaCross` 명칭이 태스크 간 일치.

## Cross-agent 검토 반영 (Codex)

T2 스키마 검증 / T3 smoke 분리 / T5 FractionalBacktest 확정 + 실제 stats 키 / T6 노트북 산출물 기준 / "design 정본 분리" 헤더 — 모두 반영.
