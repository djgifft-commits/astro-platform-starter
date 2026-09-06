"""
Phase 3 — Market condition classifier.

Causal by construction: every feature at bar i uses only data with index
<= i. The classifier never sees the synthetic ground-truth regime label
(research/data/synthetic.py); that label is used only after the fact, by
research/backtest/validation.py, to report an ENGINE VALIDATION diagnostic
("did the causal classifier's regime broadly track the generating regime
more than a random labeling would?") — never as a strategy input.
"""
from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd

from research.core.atr import atr, normalized_atr
from research.core.structure import find_structure_events

Regime = Literal[
    "STRONG_UPTREND", "UP_TREND", "WEAK_UPTREND", "RANGE",
    "WEAK_DOWNTREND", "DOWN_TREND", "STRONG_DOWNTREND",
    "HIGH_VOLATILITY", "LOW_VOLATILITY", "TRANSITION", "UNKNOWN",
]


def _slope_zscore(close: pd.Series, lookback: int) -> pd.Series:
    """Linear-regression slope of log-price over `lookback` bars, expressed
    as a standardized trend-significance score: the per-bar OLS slope
    (~ average per-bar log-return over the window) divided by the per-bar
    return std, then scaled by sqrt(lookback) so the result approximates a
    t-statistic for "is the drift over this window distinguishable from
    noise" rather than a raw per-bar Sharpe ratio (which is always tiny for
    FX-like per-minute/hourly drift-to-vol ratios and would never clear a
    meaningful threshold regardless of trend persistence)."""
    log_close = np.log(close)
    x = np.arange(lookback)
    x_mean = x.mean()
    x_var = ((x - x_mean) ** 2).sum()

    def _slope(window: np.ndarray) -> float:
        y = window
        return float(((x - x_mean) * (y - y.mean())).sum() / x_var)

    slope = log_close.rolling(lookback).apply(_slope, raw=True)
    ret_std = log_close.diff().rolling(lookback).std()
    return ((slope / ret_std.replace(0, np.nan)) * np.sqrt(lookback)).rename("slope_z")


def compute_regime_features(
    df: pd.DataFrame,
    slope_lookback: int = 50,
    vol_lookback: int = 100,
    structure_confirm_bars: int = 3,
) -> pd.DataFrame:
    natr = normalized_atr(df, period=14)
    natr_pctile = natr.rolling(vol_lookback, min_periods=vol_lookback // 2).rank(pct=True)
    slope_z = _slope_zscore(df["close"], slope_lookback)

    events = find_structure_events(df, confirm_bars=structure_confirm_bars)
    event_series = pd.Series("NONE", index=df.index)
    for e in events:
        event_series.iloc[e.index_pos] = f"{e.kind}_{e.direction}"

    # trend persistence: fraction of last `slope_lookback` closes that are directionally consistent with slope sign
    direction = np.sign(df["close"].diff())
    persistence = direction.rolling(slope_lookback).apply(
        lambda w: float((np.sign(w.sum()) == w).mean()) if w.sum() != 0 else 0.5, raw=True
    )

    out = pd.DataFrame(
        {
            "natr": natr,
            "natr_pctile": natr_pctile,
            "slope_z": slope_z,
            "structure_event": event_series,
            "trend_persistence": persistence,
        },
        index=df.index,
    )
    return out


def classify_regime(features: pd.DataFrame) -> pd.DataFrame:
    """Map causal features -> MARKET_STATE. Thresholds are explicit and
    documented; they are a starting hypothesis, sensitivity-tested in the
    ablation/validation phase, not asserted as universally correct."""
    slope_z = features["slope_z"]
    natr_pctile = features["natr_pctile"]
    persistence = features["trend_persistence"]

    regime = pd.Series("UNKNOWN", index=features.index, dtype=object)
    strength = pd.Series(0.0, index=features.index)
    direction = pd.Series("NEUTRAL", index=features.index, dtype=object)
    confidence = pd.Series(0.0, index=features.index)

    has_data = slope_z.notna() & natr_pctile.notna() & persistence.notna()

    high_vol = has_data & (natr_pctile >= 0.85)
    low_vol = has_data & (natr_pctile <= 0.15)

    strong_up = has_data & (slope_z >= 1.5) & (persistence >= 0.65)
    up = has_data & (slope_z >= 0.75) & (slope_z < 1.5) & (persistence >= 0.55)
    weak_up = has_data & (slope_z >= 0.25) & (slope_z < 0.75)
    strong_dn = has_data & (slope_z <= -1.5) & (persistence >= 0.65)
    dn = has_data & (slope_z <= -0.75) & (slope_z > -1.5) & (persistence >= 0.55)
    weak_dn = has_data & (slope_z <= -0.25) & (slope_z > -0.75)
    rng = has_data & (slope_z > -0.25) & (slope_z < 0.25)
    transition = has_data & ~(strong_up | up | weak_up | strong_dn | dn | weak_dn | rng)

    regime[rng] = "RANGE"
    regime[weak_up] = "WEAK_UPTREND"
    regime[up] = "UP_TREND"
    regime[strong_up] = "STRONG_UPTREND"
    regime[weak_dn] = "WEAK_DOWNTREND"
    regime[dn] = "DOWN_TREND"
    regime[strong_dn] = "STRONG_DOWNTREND"
    regime[transition] = "TRANSITION"
    # volatility state is reported alongside trend regime, not overriding it,
    # except when it is extreme enough with no clear trend to dominate:
    regime[has_data & high_vol & rng] = "HIGH_VOLATILITY"
    regime[~has_data] = "UNKNOWN"

    direction[strong_up | up | weak_up] = "LONG"
    direction[strong_dn | dn | weak_dn] = "SHORT"
    direction[rng | transition] = "NEUTRAL"

    strength = slope_z.abs().clip(0, 3) / 3.0
    confidence = (persistence.clip(0.5, 1.0) - 0.5) * 2.0

    vol_state = pd.Series("NORMAL", index=features.index, dtype=object)
    vol_state[high_vol] = "HIGH_VOLATILITY"
    vol_state[low_vol] = "LOW_VOLATILITY"

    return pd.DataFrame(
        {
            "regime": regime,
            "strength": strength,
            "direction": direction,
            "confidence": confidence,
            "volatility_state": vol_state,
            "trend_persistence": persistence,
        },
        index=features.index,
    )


if __name__ == "__main__":
    from research.data.synthetic import generate_multi_symbol_dataset

    ds = generate_multi_symbol_dataset(["EURUSD"], n_days=60)
    h1 = ds["EURUSD"].bars.resample("1h").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}
    ).dropna()

    feats = compute_regime_features(h1)
    state = classify_regime(feats)
    print(state["regime"].value_counts())
    print(state.dropna().head())

    # causality: feature at position i must not depend on rows after i
    feats_partial = compute_regime_features(h1.iloc[:200])
    state_partial = classify_regime(feats_partial)
    common = state.index.intersection(state_partial.index)
    common = common[common <= h1.index[199 - 60]]  # stay well clear of rolling-window edge effects
    mismatches = (state.loc[common, "regime"] != state_partial.loc[common, "regime"]).sum()
    print("mismatches on truncated-vs-full recompute (should be 0):", mismatches)
    assert mismatches == 0
    print("OK")
