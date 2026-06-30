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
