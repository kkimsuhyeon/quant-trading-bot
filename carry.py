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
