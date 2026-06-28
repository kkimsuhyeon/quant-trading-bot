import pandas as pd


def load_signals(csv_path):
    df = pd.read_csv(csv_path)
    df = df.sort_values("signal_bar_time")
    df = df.drop_duplicates(["strategy", "symbol", "timeframe", "signal_bar_time"], keep="last")
    return df.reset_index(drop=True)


def proxy_equity(sig, strategy, cash=10_000, commission=0.001):
    s = sig[sig["strategy"] == strategy].sort_values("signal_bar_time").reset_index(drop=True)
    equity = cash
    units = 0.0
    prev_pos = 0
    out = []
    for _, r in s.iterrows():
        price = float(r["signal_bar_close"])
        pos = int(r["desired_position"])
        if prev_pos == 0 and pos == 1:                 # 진입(종가 proxy 체결)
            spend = equity * (1 - commission)
            units = spend / price
            equity = 0.0
        elif prev_pos == 1 and pos == 0:               # 청산
            equity = units * price * (1 - commission)
            units = 0.0
        mark = equity + units * price                  # mark-to-market
        out.append({"signal_bar_time": r["signal_bar_time"], "position": pos, "equity": mark})
        prev_pos = pos
    return pd.DataFrame(out)
