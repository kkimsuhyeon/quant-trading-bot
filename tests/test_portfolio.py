import numpy as np
import pandas as pd
from portfolio import (equity_curve, per_coin_equity, combine_equal_weight,
                       combine_sleeves, portfolio_metrics, return_correlation)
from strategies.sma_cross import SmaCross


def _osc(n=400, start="2021-01-01"):
    idx = pd.date_range(start, periods=n, freq="4h", tz="UTC")
    close = pd.Series(120 + 40 * np.sin(np.linspace(0, 8 * np.pi, n)), index=idx)
    return pd.DataFrame({"Open": close, "High": close * 1.01, "Low": close * 0.99,
                         "Close": close, "Volume": 1000.0}, index=idx)


def _days(start, n):
    return pd.date_range(start, periods=n, freq="1D", tz="UTC")


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
