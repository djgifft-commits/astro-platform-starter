"""ATR / volatility normalization (Wilder, 1978). See RESEARCH_CARDS.md card K."""
from __future__ import annotations

import numpy as np
import pandas as pd


def true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    tr.iloc[0] = df["high"].iloc[0] - df["low"].iloc[0]
    return tr.rename("true_range")


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Wilder's smoothed ATR. Causal: atr[t] uses only bars <= t."""
    tr = true_range(df)
    return tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean().rename(f"atr_{period}")


def normalized_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """ATR as a fraction of price, for cross-instrument comparability."""
    a = atr(df, period)
    return (a / df["close"]).rename(f"natr_{period}")


if __name__ == "__main__":
    from research.data.synthetic import generate_multi_symbol_dataset

    ds = generate_multi_symbol_dataset(["EURUSD"], n_days=5)
    m1 = ds["EURUSD"].bars
    a = atr(m1, 14)
    print(a.dropna().head())
    assert (a.dropna() > 0).all()
    print("OK")
