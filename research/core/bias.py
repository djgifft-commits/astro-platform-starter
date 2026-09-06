"""
Phase 4 — Multi-timeframe directional bias engine.

Bias answers "which direction is preferred", NOT "enter now" (that is
Phase 8's job, in strategies/base.py). Combines per-timeframe structure
direction (from research/core/structure.py, causal) across HTF (D1/H4/H1)
down to execution timeframes (M15/M5), weighting higher timeframes more
heavily, and reports which timeframes agree/conflict.
"""
from __future__ import annotations

import dataclasses
from typing import Dict, List, Literal

import pandas as pd

from research.core.structure import find_structure_events

Bias = Literal["STRONG_LONG", "LONG", "NEUTRAL", "SHORT", "STRONG_SHORT"]

TIMEFRAME_WEIGHTS = {"D1": 3.0, "H4": 2.5, "H1": 2.0, "M30": 1.5, "M15": 1.0, "M5": 0.5}


def _tf_direction_asof(df: pd.DataFrame, confirm_bars: int = 3) -> pd.Series:
    """Per-bar prevailing structural direction (LONG/SHORT/NEUTRAL), causal:
    the direction after the most recent structure event confirmed as of
    that bar, using only CLOSED bars."""
    events = find_structure_events(df, confirm_bars=confirm_bars)
    direction = pd.Series("NEUTRAL", index=df.index, dtype=object)
    current = "NEUTRAL"
    event_iter = iter(events)
    next_event = next(event_iter, None)
    for pos, ts in enumerate(df.index):
        while next_event is not None and next_event.index_pos == pos:
            current = "LONG" if next_event.direction == "BULLISH" else "SHORT"
            next_event = next(event_iter, None)
        direction.iloc[pos] = current
    return direction


@dataclasses.dataclass
class BiasSnapshot:
    timestamp: pd.Timestamp
    bias: Bias
    bias_score: float
    bias_confidence: float
    supporting_timeframes: List[str]
    conflicting_timeframes: List[str]


def compute_multi_timeframe_bias(
    frames: Dict[str, pd.DataFrame],
    as_of_ts: pd.Timestamp,
    confirm_bars: int = 3,
) -> BiasSnapshot:
    """frames: {"D1": df, "H4": df, "H1": df, "M15": df, "M5": df} — any
    subset present will be used; timeframes not present are skipped
    (Phase 4: 'do not assume every symbol/timeframe has adequate history')."""
    score = 0.0
    total_weight = 0.0
    supporting: List[str] = []
    conflicting: List[str] = []
    net_direction_sign = 0.0

    per_tf_dir = {}
    for tf, df in frames.items():
        causal = df.loc[df.index <= as_of_ts]
        if len(causal) < 2 * confirm_bars + 5:
            continue
        direction_series = _tf_direction_asof(causal, confirm_bars=confirm_bars)
        d = direction_series.iloc[-1]
        per_tf_dir[tf] = d
        w = TIMEFRAME_WEIGHTS.get(tf, 1.0)
        total_weight += w
        if d == "LONG":
            score += w
        elif d == "SHORT":
            score -= w

    if total_weight == 0:
        return BiasSnapshot(as_of_ts, "NEUTRAL", 0.0, 0.0, [], [])

    norm_score = score / total_weight
    overall = "LONG" if norm_score > 0 else ("SHORT" if norm_score < 0 else "NEUTRAL")
    for tf, d in per_tf_dir.items():
        if d == overall:
            supporting.append(tf)
        elif d != "NEUTRAL":
            conflicting.append(tf)

    if norm_score >= 0.6:
        bias: Bias = "STRONG_LONG"
    elif norm_score >= 0.15:
        bias = "LONG"
    elif norm_score <= -0.6:
        bias = "STRONG_SHORT"
    elif norm_score <= -0.15:
        bias = "SHORT"
    else:
        bias = "NEUTRAL"

    confidence = min(1.0, len(supporting) / max(1, len(supporting) + len(conflicting)))
    return BiasSnapshot(as_of_ts, bias, norm_score, confidence, supporting, conflicting)


def compute_bias_series(frames: Dict[str, pd.DataFrame], confirm_bars: int = 3) -> pd.DataFrame:
    """Vectorized, causal per-bar bias series on the union of all provided
    timeframe indices' timestamps restricted to the FINEST timeframe's
    index (the one strategies actually iterate on). Computes each
    timeframe's direction series ONCE (not once per bar) and combines via
    as-of merge, which is what makes this tractable at scale."""
    finest_tf = min(frames, key=lambda tf: frames[tf].index.to_series().diff().median())
    base_index = frames[finest_tf].index

    per_tf_direction = {}
    for tf, df in frames.items():
        if len(df) < 2 * confirm_bars + 5:
            continue
        per_tf_direction[tf] = _tf_direction_asof(df, confirm_bars=confirm_bars)

    merged = pd.DataFrame(index=base_index)
    for tf, series in per_tf_direction.items():
        s = series.reindex(series.index.union(base_index)).ffill().reindex(base_index)
        merged[tf] = s

    score = pd.Series(0.0, index=base_index)
    weight_total = pd.Series(0.0, index=base_index)
    for tf in merged.columns:
        w = TIMEFRAME_WEIGHTS.get(tf, 1.0)
        present = merged[tf].notna()
        weight_total += present * w
        score += present * w * merged[tf].map({"LONG": 1.0, "SHORT": -1.0, "NEUTRAL": 0.0}).fillna(0.0)

    norm_score = (score / weight_total.replace(0, pd.NA)).astype(float)

    bias = pd.Series("NEUTRAL", index=base_index, dtype=object)
    bias[norm_score >= 0.6] = "STRONG_LONG"
    bias[(norm_score >= 0.15) & (norm_score < 0.6)] = "LONG"
    bias[(norm_score <= -0.15) & (norm_score > -0.6)] = "SHORT"
    bias[norm_score <= -0.6] = "STRONG_SHORT"

    supporting_count = pd.Series(0, index=base_index)
    conflicting_count = pd.Series(0, index=base_index)
    overall_dir = pd.Series("NEUTRAL", index=base_index, dtype=object)
    overall_dir[norm_score > 0] = "LONG"
    overall_dir[norm_score < 0] = "SHORT"
    for tf in merged.columns:
        supporting_count += (merged[tf] == overall_dir).astype(int)
        conflicting_count += ((merged[tf] != overall_dir) & merged[tf].notna() & (merged[tf] != "NEUTRAL")).astype(int)

    confidence = (supporting_count / (supporting_count + conflicting_count).replace(0, pd.NA)).astype(float).fillna(0.0)

    # Phase 8F: a separate 4-state vocabulary (BULLISH/BEARISH/NEUTRAL/
    # CONFLICTED), distinct from the 5-state STRONG_LONG..STRONG_SHORT
    # scale above. CONFLICTED is not just "weak" -- it specifically means
    # multiple timeframes actively disagree (both supporting_count and
    # conflicting_count are non-trivial), which NEUTRAL (no strong signal
    # either way, low conflict) does not capture.
    bias_4state = pd.Series("NEUTRAL", index=base_index, dtype=object)
    bias_4state[norm_score > 0.15] = "BULLISH"
    bias_4state[norm_score < -0.15] = "BEARISH"
    has_real_conflict = (conflicting_count >= 1) & (supporting_count >= 1) & (conflicting_count >= supporting_count * 0.75)
    bias_4state[has_real_conflict] = "CONFLICTED"

    return pd.DataFrame(
        {
            "bias": bias,
            "bias_score": norm_score.fillna(0.0),
            "bias_confidence": confidence,
            "bias_supporting_count": supporting_count,
            "bias_conflicting_count": conflicting_count,
            "bias_4state": bias_4state,
        },
        index=base_index,
    )


if __name__ == "__main__":
    from research.data.loaders import resample_all
    from research.data.synthetic import generate_multi_symbol_dataset

    ds = generate_multi_symbol_dataset(["EURUSD"], n_days=120)
    m1 = ds["EURUSD"].bars
    frames = resample_all(m1, ("M5", "M15", "H1", "H4", "D1"))

    snap = compute_multi_timeframe_bias(frames, as_of_ts=m1.index[-1])
    print(snap)

    # causality: bias computed with only data up to an earlier timestamp must
    # not change if we append future bars after that timestamp
    cutoff = m1.index[len(m1) // 2]
    frames_full = frames
    frames_truncated = {tf: df.loc[df.index <= cutoff] for tf, df in frames.items()}
    snap_full = compute_multi_timeframe_bias(frames_full, as_of_ts=cutoff)
    snap_trunc = compute_multi_timeframe_bias(frames_truncated, as_of_ts=cutoff)
    assert snap_full.bias == snap_trunc.bias, (snap_full, snap_trunc)
    assert abs(snap_full.bias_score - snap_trunc.bias_score) < 1e-9
    print("Causality check OK")

    series = compute_bias_series(frames)
    print(series.tail())
    print(series["bias"].value_counts())
    # spot check series matches snapshot at same timestamp
    snap_at_last = compute_multi_timeframe_bias(frames, as_of_ts=series.index[-1])
    assert abs(series["bias_score"].iloc[-1] - snap_at_last.bias_score) < 1e-6
    print("Series/snapshot agreement OK")
