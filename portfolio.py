import pandas as pd
from backtest import run_backtest


def equity_curve(df, strategy, **params):
    _, stats = run_backtest(df, strategy, **params)
    return stats["_equity_curve"]["Equity"]


def per_coin_equity(data_by_symbol, strategy, **params):
    cols = {sym: equity_curve(df, strategy, **params) for sym, df in data_by_symbol.items()}
    return pd.DataFrame(cols)


def combine_equal_weight(equities, cash=10_000):
    n = equities.shape[1]
    alloc = cash / n
    contribs = {}
    for col in equities.columns:
        e = equities[col]
        first = e.dropna().iloc[0]
        # 상장 후: alloc*(e/first). 상장 전(선행 NaN): 현금 alloc 보유. 내부 결측: ffill.
        contribs[col] = (alloc * e / first).ffill().fillna(alloc)
    return pd.DataFrame(contribs).sum(axis=1)


def combine_sleeves(equities, weights=None, freq="1D", cash=10_000):
    names = list(equities.keys())
    if weights is None:
        weights = {n: 1 / len(names) for n in names}
    # 1) 각 sleeve 일간 리샘플 → 2) 한 DataFrame → 3) 공통창 dropna
    df = pd.DataFrame({n: equities[n].resample(freq).last() for n in names}).dropna()
    # 4) 공통창 첫 row로 정규화 → 5) cash*weight 가중 합산
    parts = {n: cash * weights[n] * df[n] / df[n].iloc[0] for n in names}
    return pd.DataFrame(parts).sum(axis=1)


def portfolio_metrics(equity, periods_per_year=6 * 365):
    ret = (equity.iloc[-1] / equity.iloc[0] - 1) * 100
    mdd = (equity / equity.cummax() - 1).min() * 100
    r = equity.pct_change(fill_method=None).dropna()
    sharpe = (r.mean() / r.std()) * (periods_per_year ** 0.5) if r.std() > 0 else 0.0
    return {"Return [%]": ret, "Max. Drawdown [%]": mdd, "Sharpe Ratio": sharpe}


def return_correlation(equities):
    return equities.pct_change(fill_method=None).corr()
