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
