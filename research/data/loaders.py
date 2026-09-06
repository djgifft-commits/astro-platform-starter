"""
Causal timeframe aggregation.

Resampling M1 -> M5/M15/H1/H4/D1 using only CLOSED bars. The last bucket of
a resample is dropped whenever it is not yet complete relative to the
available M1 history, so no "forming" higher-timeframe bar is ever exposed
to a consumer (Phase 2 requirement: forming-bar exclusion).
"""
from __future__ import annotations

import pandas as pd

from research.config import TIMEFRAMES_MINUTES

_PANDAS_FREQ = {
    "M1": "1min",
    "M5": "5min",
    "M15": "15min",
    "H1": "1h",
    "H4": "4h",
    "D1": "1D",
}


def resample_ohlc(m1: pd.DataFrame, timeframe: str, spread_col: str = "spread") -> pd.DataFrame:
    """Aggregate M1 OHLC(+spread) bars to a higher timeframe, dropping any
    final bucket whose right edge extends past the last available M1
    timestamp (i.e. it would be a still-forming bar)."""
    if timeframe == "M1":
        return m1.copy()
    if timeframe not in _PANDAS_FREQ:
        raise ValueError(f"unknown timeframe {timeframe}")

    freq = _PANDAS_FREQ[timeframe]
    agg = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
    }
    if spread_col in m1.columns:
        agg[spread_col] = "mean"

    out = m1.resample(freq, label="left", closed="left").agg(agg).dropna(subset=["open"])

    bar_minutes = TIMEFRAMES_MINUTES[timeframe]
    last_m1_ts = m1.index[-1]
    # a bucket is "closed" only if its right edge <= last available M1 timestamp + 1 minute
    bucket_end = out.index + pd.Timedelta(minutes=bar_minutes)
    closed_mask = bucket_end <= (last_m1_ts + pd.Timedelta(minutes=1))
    out = out.loc[closed_mask]
    out.index.name = "timestamp"
    return out


def resample_all(m1: pd.DataFrame, timeframes=("M5", "M15", "H1", "H4", "D1")) -> dict[str, pd.DataFrame]:
    return {tf: resample_ohlc(m1, tf) for tf in timeframes}


def as_of(df: pd.DataFrame, timestamp: pd.Timestamp) -> pd.DataFrame:
    """Causal slice: every row with index <= timestamp (inclusive of a bar
    that just closed exactly at `timestamp`, exclusive of anything after)."""
    return df.loc[df.index <= timestamp]


if __name__ == "__main__":
    from research.data.synthetic import generate_multi_symbol_dataset

    ds = generate_multi_symbol_dataset(["EURUSD"], n_days=5)
    m1 = ds["EURUSD"].bars
    for tf in ("M5", "M15", "H1", "H4", "D1"):
        out = resample_ohlc(m1, tf)
        bar_minutes = TIMEFRAMES_MINUTES[tf]
        expected_last_start = m1.index[-1].floor(f"{bar_minutes}min")
        print(tf, out.shape, "last bar start:", out.index[-1], "vs floor-of-last-m1:", expected_last_start)
        assert out.index[-1] <= expected_last_start
    print("OK")
