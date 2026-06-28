import numpy as np
import pandas as pd
from portfolio import equity_curve, per_coin_equity
from portfolio import combine_equal_weight, portfolio_metrics, return_correlation
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
