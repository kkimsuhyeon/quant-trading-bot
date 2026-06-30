import pandas as pd


def sentiment_risk_off(use_sentiment, sentiment_value, threshold=75):
    """극탐욕(F&G ≥ threshold)이면 True(=현금/리스크오프). 스위치 off나 결측이면 False."""
    if not use_sentiment:
        return False
    if sentiment_value is None or pd.isna(sentiment_value):
        return False                      # 결측 = 필터 off (baseline처럼)
    return bool(sentiment_value >= threshold)
