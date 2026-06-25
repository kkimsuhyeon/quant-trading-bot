# Phase 0 + 1 상세 설계 — 실험실 구축 (Hello World)

> 상태: **설계 완료, 구현 전**
> 관련: 로드맵은 [`PLAN.md`](../../PLAN.md), 가드레일은 [`CLAUDE.md`](../../CLAUDE.md).
> 이 설계는 cross-agent 검토(Codex)를 거쳐 확정됨. (검토 기록은 문서 끝 참조)

## 1. 개요 & 범위 (Scope)

이번 사이클의 목적은 **"전략을 싸게 검증하는 실험실"의 뼈대를 끝까지 한 번 관통**시키는 것이다.
즉 `데이터 수집 → 백테스트 하네스 → 전략 → 결과 출력`이 막힘없이 흐르는 파이프라인을 만든다.

- **Phase 0**: ccxt로 BTC/USDT 캔들을 수집·정리해 파일로 저장 (+ sentiment 컬럼 자리).
- **Phase 1**: Backtesting.py 얇은 래퍼(하네스) + 가장 단순한 전략(SMA 교차)으로 파이프라인 관통
  (+ sentiment on/off 스위치 자리).

> ⚠️ **중요 — SMA 교차는 "수익 전략 검증"이 아니라 "파이프라인 hello world"다.**
> 이 단계의 SMA 전략이 돈을 버는지는 관심사가 아니다. 오직 "파이프라인이 끝까지 도는가"만 본다.
> 따라서 **가설 문서(`notes/hypothesis_*.md`)와 리스크 레이어(손절·포지션 사이징·킬스위치)는
> 이 hello world에서는 생략하고, 진짜 전략을 검증하는 Phase 2부터 필수로 적용**한다.

## 2. 이번에 만드는 파일 (산출물)

```
quant-trading-bot/
├─ data/                          ← 수집 데이터 (git 미포함, 재현 가능)
│   ├─ BTC_USDT_1h.parquet / .csv
│   └─ BTC_USDT_4h.parquet / .csv
├─ fetch.py                       ← [Phase 0] 데이터 수집
├─ backtest.py                    ← [Phase 1] 하네스 (만들고 고정)
├─ strategies/
│   └─ sma_cross.py               ← [Phase 1] hello world 전략 (부품)
├─ research/
│   └─ 2026-06-25_hello_world.ipynb   ← 돌려보고 차트 확인
└─ requirements.txt
```

데이터는 **한 방향으로만** 흐른다:

```
[바이낸스] ──ccxt──▶ fetch.py ──저장──▶ data/*.parquet
                                            │ 읽기
                                            ▼
                                       backtest.py (하네스)
                                            │  ← strategies/sma_cross.py 꽂음
                                            │  ← 수수료 0.1%, 룩어헤드 방지
                                            ▼
                                       결과(수익률·MDD·샤프) ──▶ research/*.ipynb 차트
```

**두 가지 분리 원칙이 이 흐름에 박혀 있다:**
1. **수집 ↔ 백테스트 분리.** `fetch.py`는 한 번 받아 파일로 저장만, `backtest.py`는 읽기만.
   (백테스트마다 거래소를 두드리지 않는다.)
2. **하네스 ↔ 전략 분리.** `backtest.py`는 고정, `strategies/`의 부품만 갈아끼운다.
   (CLAUDE.md 가드라인 3.)

## 3. 핵심 결정 요약

| 항목 | 결정 | 비고 |
|---|---|---|
| 자산 | BTC/USDT | ETH는 Phase 2에서 호출 한 줄 추가 |
| 시간 단위 | 1h + 4h | |
| 데이터 기간 | 약 3년 | OOS 검증(Phase 3) 가능한 최소 |
| 저장 포맷 | parquet(주) + csv(확인용) | |
| 작업 방식 | `.py` + Jupyter 노트북 혼합 | 로직은 .py, 탐색·시각화는 노트북 |
| 백테스트 엔진 | Backtesting.py (얇은 래퍼) | 밑바닥부터 안 짠다 |
| 거래 비용 | 한 방향당 0.1% (수수료) | 슬리피지는 Phase 4 실측까지 보류 (§9) |
| 룩어헤드 방지 | `trade_on_close=False` (기본) | 다음 봉 시가 체결 (§8) |

## 4. Phase 0 — 데이터층 (`fetch.py`)

바이낸스에서 캔들을 받아 정리해 저장한다. 초보가 놓치기 쉬운 **함정 3개**를 설계에 박는다.

- **함정 1 — 한 번에 다 못 받음.** ccxt는 호출당 최대 ~1000개만 준다. 3년치 1h ≈ 26,000개이므로
  **시작 시점부터 현재까지 루프 돌며 1000개씩 받아 이어붙인다**(페이지네이션).
- **함정 2 — 미완성 캔들.** 진행 중인 마지막 캔들은 룩어헤드의 씨앗 → **잘라낸다**.
- **함정 3 — 중복·정렬.** 이어붙이다 경계에서 겹치거나 꼬일 수 있다 → **시간 기준 중복 제거 + 정렬**.

그리고 PLAN대로 **sentiment 컬럼 자리**를 비워 둔다(`pd.NA`). 구현은 Phase 5.

```python
# fetch.py
import ccxt
import pandas as pd

def fetch_ohlcv(symbol="BTC/USDT", timeframe="1h", years=3):
    exchange = ccxt.binance()
    since = exchange.parse8601(<지금부터 years년 전>)
    all_rows = []
    while True:
        batch = exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=1000)
        if not batch:
            break
        all_rows += batch
        since = batch[-1][0] + 1          # 다음 페이지: 마지막 캔들 다음부터
        if len(batch) < 1000:
            break

    df = pd.DataFrame(all_rows, columns=["timestamp","open","high","low","close","volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    df = df.drop_duplicates("timestamp").sort_values("timestamp")   # 함정 3
    df = df.iloc[:-1]                      # 함정 2: 마지막 미완성 캔들 제거
    df["sentiment"] = pd.NA               # sentiment 자리 (Phase 5에서 채움)
    return df.set_index("timestamp")

def save(df, symbol, timeframe):
    name = f"{symbol.replace('/','_')}_{timeframe}"   # BTC_USDT_1h
    df.to_parquet(f"data/{name}.parquet")
    df.to_csv(f"data/{name}.csv")

if __name__ == "__main__":
    for tf in ["1h", "4h"]:
        df = fetch_ohlcv("BTC/USDT", tf, years=3)
        save(df, "BTC/USDT", tf)
        print(f"{tf}: {len(df)} candles, {df.index[0]} ~ {df.index[-1]}")
```

## 5. Phase 1 — 하네스 (`backtest.py`)

하네스는 `데이터 + 전략 → 결과`를 돌려주는 **고정된 틀**이다. 우리 원칙(수수료, 룩어헤드 방지,
소수점 거래)을 여기에 박는다. Backtesting.py를 쓰기 위한 **번역 2개**가 필요하다.

- **번역 1 — 컬럼 이름.** Backtesting.py는 `Open/High/Low/Close/Volume`(대문자)를 요구한다.
  우리 데이터는 소문자 → 읽으면서 rename. (`sentiment` 컬럼은 그대로 두면 전략에서 `self.data.sentiment`로 접근 가능 → §7 스위치 통로.)
- **번역 2 — 소수점(fractional) 거래.** ⚠️ Backtesting.py 기본 `Backtest`는 **정수 단위**로 거래한다.
  초기자본 $10,000인데 BTC 1개가 $30,000이면 **1개도 못 사서 거래가 0번** 일어나는 "조용한 버그"가 난다.
  → **`FractionalBacktest`를 사용**(또는 초기자본을 충분히 크게)하고, **smoke test에서 "거래 횟수 > 0"을
  반드시 단언**한다. (정확한 API는 구현 시 Backtesting.py 공식 문서로 확인.)

```python
# backtest.py
import pandas as pd
from backtesting import Backtest          # 구현 시 FractionalBacktest 사용 여부 확정

def load_data(symbol="BTC/USDT", timeframe="1h"):
    name = f"{symbol.replace('/','_')}_{timeframe}"
    df = pd.read_parquet(f"data/{name}.parquet")
    df = df.rename(columns={                # 번역 1
        "open":"Open", "high":"High", "low":"Low",
        "close":"Close", "volume":"Volume",
    })
    return df

def run_backtest(df, strategy, cash=10_000, commission=0.001, **params):
    bt = Backtest(
        df, strategy,
        cash=cash,
        commission=commission,   # 0.001 = 한 방향당 0.1% (거래소 수수료)
        trade_on_close=False,    # 룩어헤드 방지: 다음 봉 시가 체결 (§8)
    )
    stats = bt.run(**params)     # 전략 파라미터 전달 (use_sentiment 등)
    return bt, stats

if __name__ == "__main__":
    from strategies.sma_cross import SmaCross
    df = load_data("BTC/USDT", "1h")
    bt, stats = run_backtest(df, SmaCross)
    print(stats)                 # 수익률·샤프·MDD·승률·거래수 자동 출력
```

`print(stats)`가 `Return [%]`, `Sharpe Ratio`, `Max. Drawdown [%]`, `Win Rate [%]`, `# Trades` 등을
**자동 계산**해 출력한다(우리가 안 짠다). 하네스가 "얇은" 이유다.

**고정 원칙:** 전략을 N개 만들어도 `run_backtest(df, 새전략)`처럼 전략만 바꿔 호출한다.
`backtest.py`는 수정하지 않는다.

## 6. Phase 1 — 전략 (`strategies/sma_cross.py`) + sentiment 스위치

전략은 Backtesting.py `Strategy` 상속 클래스다. `init()`(지표 1회 계산), `next()`(캔들마다 결정) 두 개.

```python
# strategies/sma_cross.py
import pandas as pd
from backtesting import Strategy
from backtesting.lib import crossover

def SMA(series, n):
    return pd.Series(series).rolling(n).mean()

class SmaCross(Strategy):
    fast = 20                # 단기 이평 (파라미터)
    slow = 50                # 장기 이평 (파라미터)
    use_sentiment = False    # ★ sentiment on/off 스위치 자리 (구현 Phase 5)

    def init(self):
        close = self.data.Close
        self.sma_fast = self.I(SMA, close, self.fast)
        self.sma_slow = self.I(SMA, close, self.slow)
        # ★ sentiment 자리 (Phase 5):
        # if self.use_sentiment:
        #     self.sentiment = self.data.sentiment

    def next(self):
        # 룩어헤드 방지(§8): 현재까지 공개된 완성 캔들만 사용.
        if crossover(self.sma_fast, self.sma_slow):     # 골든크로스 → 매수
            self.buy()
        elif crossover(self.sma_slow, self.sma_fast):   # 데드크로스 → 청산
            self.position.close()

        # ★ sentiment 자리 (Phase 5에서 구현, 지금은 비활성):
        # if self.use_sentiment:
        #     score = self.sentiment[-1]
        #     # 점수로 진입 거르기 / 포지션 크기 보정 등
```

**sentiment 스위치 연결 경로** (PLAN "자리만 뚫기"):

```
run_backtest(df, SmaCross, use_sentiment=True)   ← 나중에 이렇게 켬
   └─ Backtesting.py가 값을 전략에 주입 → SmaCross.use_sentiment = True
        └─ init()/next()의 sentiment 블록이 살아남 (Phase 5에서 구현)
```

지금은 `use_sentiment=False` → 데이터엔 컬럼 자리(`pd.NA`), 전략엔 스위치 자리. **둘 다 뚫려 있고 구현은 0.**

## 7. 룩어헤드 방지 (가드라인 4)

> **`Strategy.next()`에서는 현재까지 공개된 완성 캔들만 사용한다.
> `trade_on_close=False`를 유지하므로, 해당 캔들 종가 기준으로 생성한 시장가 주문은
> 다음 캔들 시가에 체결된다.**

즉 끝난 캔들의 확정된 정보로만 판단하고, 실제 매매는 다음 봉에서 일어난다. 미래를 보지 않는다.
이 동작은 Backtesting.py 기본값이므로 **우리는 `trade_on_close=False`를 건드리지 않기만** 하면 된다.

## 8. 거래 비용 — 수수료 vs 슬리피지 (가드라인 1)

- **수수료(commission)**: `commission=0.001` = 한 방향당 **0.1%** (바이낸스 현물 기본). 진입·청산 양쪽 적용.
- **슬리피지(slippage)**: 이번 단계에서는 **모델링하지 않는다(spread=0)**. 백테스트의 슬리피지 추정은
  부정확하므로, **실제 체결 차이는 Phase 4(테스트넷 페이퍼 트레이딩)에서 실측**한다.
- 따라서 현재 비용 가정은 "수수료만 반영, 슬리피지는 Phase 4까지 보류"임을 **명시적으로** 기록한다.

## 9. 리스크 관리 & 가설 문서 — Phase 2부터 (hello world 예외)

CLAUDE.md 가드라인 5(리스크 관리)와 작업 규율 6(가설 문서)은 **진짜 전략을 검증하는 Phase 2부터** 적용한다.
이번 hello world의 SMA는 "파이프라인 관통 확인용"이므로:

- 포지션 = 가용 자본 전부(소수점 매수), 청산 = 반대 크로스 (= 최소 진입/청산만).
- **손절·포지션 사이징·킬스위치, 그리고 `notes/hypothesis_*.md`는 작성하지 않는다.**
- Phase 2에서 첫 "검증 대상 전략"을 만들 때 이 둘을 **필수**로 도입한다.

## 10. 검증 계획 (smoke tests)

이 사이클의 "완료" 기준:

1. **데이터**: `fetch.py` 실행 → BTC/USDT 1h·4h 각각 캔들 개수와 기간(시작~끝)이 출력되고 약 3년 분량인가.
2. **거래 발생**: 백테스트의 `# Trades > 0` (= fractional 거래가 실제로 일어났는가 — §5 함정).
3. **지표 출력**: `print(stats)`에 `Return [%] / Sharpe / Max. Drawdown [%] / Win Rate [%]`가 나오는가.
4. **룩어헤드**: `trade_on_close=False`가 유지되는가 (§7).
5. **노트북**: `research/` 노트북에서 수익곡선 차트가 그려지는가.

## 11. 범위 밖 / 나중 (deferred)

- **sentiment 구현** → Phase 5 (지금은 컬럼·스위치 자리만).
- **슬리피지 실측** → Phase 4.
- **리스크 레이어 / 가설 문서** → Phase 2.
- **ETH, 추가 전략** → Phase 2.
- **포트폴리오 결합 / 선물** → Phase 7.

## 12. Cross-agent 검토 기록 (Codex)

이 설계는 `trader-codex`(Codex, gpt-5.5) 검토를 거쳤다. 반영한 피드백:

- **(1) fractional 거래**: `FractionalBacktest` 사용 + smoke test에서 `# Trades > 0` 단언. (§5, §10)
- **(2) 수수료/슬리피지 용어 분리**: commission=수수료, 슬리피지는 Phase 4까지 보류 명시. (§8)
- **(3) 룩어헤드 문구 정밀화**: "현재까지 공개된 완성 캔들 사용 → 다음 봉 시가 체결". (§7)
- **(4) hello world 분류**: 가설 문서·리스크 레이어는 Phase 2부터. (§1, §9)
- **(5) 문서 구조**: PLAN.md(로드맵) / docs/design(설계 상세) 역할 분리. (README)
