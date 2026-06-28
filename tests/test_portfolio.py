import numpy as np
import pandas as pd
from portfolio import equity_curve, per_coin_equity
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
