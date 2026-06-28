import pandas as pd
from paper_report import load_signals, proxy_equity


def _signals_csv(tmp_path):
    # 한 전략(regime)에 대해 4개 봉: 0,1,1,0 (한 번 진입했다가 청산)
    times = pd.date_range("2026-01-01", periods=4, freq="4h", tz="UTC")
    rows = []
    for t, close, pos in zip(times, [100, 110, 120, 90], [0, 1, 1, 0]):
        rows.append({"run_at": t.isoformat(), "symbol": "BTC/USDT", "timeframe": "4h",
                     "strategy": "regime", "signal_bar_time": t.isoformat(),
                     "signal_bar_close": close, "desired_position": pos,
                     "source_rows": 1000, "lookback_bars": 1000, "strategy_params": "sma_n=200"})
    p = str(tmp_path / "signals.csv")
    pd.DataFrame(rows).to_csv(p, index=False)
    return p


def test_load_signals_dedups_last(tmp_path):
    p = _signals_csv(tmp_path)
    # 마지막 봉 중복 추가(다른 run_at)
    extra = pd.read_csv(p).tail(1)
    extra.to_csv(p, mode="a", header=False, index=False)
    sig = load_signals(p)
    assert len(sig[sig["strategy"] == "regime"]) == 4        # 중복 제거


def test_proxy_equity_realizes_pnl(tmp_path):
    sig = load_signals(_signals_csv(tmp_path))
    eq = proxy_equity(sig, "regime")
    # 110에 진입 → 90에 청산: 손실. 최종 자본 < 시작.
    assert eq["equity"].iloc[-1] < 10_000
    assert "equity" in eq.columns
