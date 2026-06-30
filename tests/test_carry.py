import pandas as pd
from carry import carry_pnl, carry_metrics, funding_stats


def _funding(values, start="2021-06-01"):
    idx = pd.date_range(start, periods=len(values), freq="8h", tz="UTC")
    return pd.Series(values, index=idx, dtype=float)


def test_carry_pnl_accrues_funding_minus_fees():
    f = _funding([0.0005] * 100)                       # 매기 +0.0005, 100기
    eq = carry_pnl(f)                                  # notional=1, fee 0.001+0.0005
    # 누적펀딩 0.05, 4-leg 수수료 = 2*(0.001+0.0005)=0.003 → 최종 ≈ 1+0.05-0.003 = 1.047
    assert abs(eq.iloc[-1] - 1.047) < 1e-6
    # 첫 기: 1+0.0005 - 진입수수료 0.0015 = 0.999
    assert abs(eq.iloc[0] - 0.999) < 1e-6


def test_carry_pnl_fees_can_exceed_small_funding():
    f = _funding([0.0001, -0.0001, 0.0001])            # 누적 0.0001, 수수료 0.003
    eq = carry_pnl(f)
    assert eq.iloc[-1] < 1.0                            # 수수료가 펀딩보다 커서 순손실


def test_carry_metrics_keys_and_mdd():
    f = _funding([0.001, -0.002, 0.001, 0.001])
    eq = carry_pnl(f)
    m = carry_metrics(eq)
    assert {"Return [%]", "Ann Return [%]", "Sharpe", "MDD [%]"} <= set(m)
    assert m["MDD [%]"] <= 0                            # 낙폭은 음수(또는 0)


def test_carry_metrics_net_loss_has_negative_return_and_mdd():
    # 펀딩(누적 0.0001)은 소폭 +지만 수수료 0.003로 순손실.
    # gross 공식이었으면 Sharpe 부호가 +로 어긋났을 케이스.
    f = _funding([0.0001, -0.0001, 0.0001])
    eq = carry_pnl(f)
    m = carry_metrics(eq)
    assert m["Return [%]"] < 0
    assert m["MDD [%]"] < 0


def test_carry_metrics_uptrend_has_positive_sharpe_and_return():
    # 매기 +0.001 꾸준히 → 수수료 후에도 명백히 우상향.
    f = _funding([0.001] * 200)
    eq = carry_pnl(f)
    m = carry_metrics(eq)
    assert m["Return [%]"] > 0
    assert m["Sharpe"] > 0


def test_funding_stats_neg_ratio():
    f = _funding([0.001, -0.001, -0.001, 0.001])        # 음수 2/4 = 0.5
    s = funding_stats(f)
    assert round(s["neg_ratio"], 2) == 0.5
    assert {"mean", "median", "p5", "p95", "neg_ratio"} <= set(s)


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
    assert abs(s["neg_ratio"] - 0.6) < 1e-9                        # 3/5
