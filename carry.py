import pandas as pd


def carry_pnl(funding, notional=1.0, spot_fee=0.001, perp_fee=0.0005):
    leg_fee = notional * (spot_fee + perp_fee)          # 한 쪽(진입 or 청산) = 2 legs
    equity = notional * (1 + funding.cumsum()) - leg_fee   # 진입 수수료(2 legs) 전체 반영
    equity.iloc[-1] -= leg_fee                            # 청산 수수료(2 legs) 마지막에
    return equity


def carry_metrics(equity, periods_per_year=1095):
    ret = (equity.iloc[-1] / equity.iloc[0] - 1) * 100
    n = len(equity)
    ann = ((equity.iloc[-1] / equity.iloc[0]) ** (periods_per_year / n) - 1) * 100 if n > 0 else 0.0
    mdd = (equity / equity.cummax() - 1).min() * 100
    r = equity.pct_change(fill_method=None).dropna()
    sharpe = (r.mean() / r.std()) * (periods_per_year ** 0.5) if r.std() > 0 else 0.0
    return {"Return [%]": ret, "Ann Return [%]": ann, "Sharpe": sharpe, "MDD [%]": mdd}


def funding_stats(funding):
    return {
        "mean": funding.mean(),
        "median": funding.median(),
        "p5": funding.quantile(0.05),
        "p95": funding.quantile(0.95),
        "neg_ratio": (funding < 0).mean(),
    }


def net_carry_pnl(funding, notional=1.0, spot_fee=0.001, perp_fee=0.0005,
                  annual_haircut=0.02, periods_per_year=1095):
    """v1 gross 캐리에 연 haircut을 매 기간 균등 차감한 net 손익곡선. carry_pnl 재사용(DRY)."""
    drag = annual_haircut / periods_per_year          # 매 8h basis/슬리피지 haircut
    return carry_pnl(funding - drag, notional=notional, spot_fee=spot_fee, perp_fee=perp_fee)


def rolling_worst_return(equity, window=270):
    """최악 window-기간 수익률(기본 270 = 90일*3, 8h봉). equity[t]/equity[t-window]-1 의 최소."""
    return (equity / equity.shift(window) - 1).min()


def negative_funding_stats(funding):
    """음수 펀딩 레짐 지표: 최장 연속 음수 개수 / 음수 구간 합 / 음수 비율."""
    neg = funding < 0
    longest = streak = 0
    for v in neg:
        streak = streak + 1 if v else 0
        longest = max(longest, streak)
    return {
        "longest_neg_streak": longest,
        "neg_total": funding[neg].sum(),
        "neg_ratio": neg.mean(),
    }
