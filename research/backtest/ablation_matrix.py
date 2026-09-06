"""
Phase 8Y — Generalized ablation matrix.

Unlike research/backtest/ablation.py (Phase 7's narrower 2-flag ablation
on top of one strategy's own checklist), this builds a single
deliberately trivial BASELINE signal -- "this bar's close breaks the
prior bar's high/low" -- specifically so it is NOT already conditioned on
any of the features being tested, then measures whether each named
feature, added as an independent post-hoc filter, changes the SAME
ATR-normalized signed-forward-return target used in
research/backtest/bias_experiment.py. This isolates "does this feature
carry information" from "how good is this particular strategy's
combination of features," which is what Phase 8Y actually asks
("determine WHAT ACTUALLY ADDS INFORMATION... do not assume more
features = better strategy").

BASELINE + DXY is not implemented: this project has no DXY data, real or
non-circular synthetic (see audit/PHASE_8B_EXTERNAL_RESEARCH.md) --
reported as DATA_UNAVAILABLE rather than skipped silently.
"""
from __future__ import annotations

from typing import Dict

import numpy as np
import pandas as pd

from research.backtest.validation import bootstrap_mean_ci, permutation_negative_control

BULLISH_PATTERNS = ["bullish_engulfing", "hammer", "pin_bar", "morning_star", "marubozu"]
BEARISH_PATTERNS = ["bearish_engulfing", "shooting_star", "pin_bar", "evening_star", "marubozu"]


def _baseline_direction(exec_df: pd.DataFrame) -> pd.Series:
    prev_high = exec_df["high"].shift(1)
    prev_low = exec_df["low"].shift(1)
    direction = pd.Series(np.nan, index=exec_df.index, dtype=object)
    direction[exec_df["close"] > prev_high] = "LONG"
    direction[exec_df["close"] < prev_low] = "SHORT"
    return direction


def _structure_mask(direction: pd.Series, fb: pd.DataFrame) -> pd.Series:
    return ((direction == "LONG") & (fb["regime_structure_state"] == "LONG")) | \
           ((direction == "SHORT") & (fb["regime_structure_state"] == "SHORT"))


def _regime_mask(direction: pd.Series, fb: pd.DataFrame) -> pd.Series:
    return ((direction == "LONG") & (fb["regime_direction"] == "LONG")) | \
           ((direction == "SHORT") & (fb["regime_direction"] == "SHORT"))


def _candle_mask(direction: pd.Series, patterns: pd.DataFrame) -> pd.Series:
    patterns_aligned = patterns.reindex(direction.index).fillna(False)
    bullish_hit = patterns_aligned[BULLISH_PATTERNS].any(axis=1)
    bearish_hit = patterns_aligned[BEARISH_PATTERNS].any(axis=1)
    return ((direction == "LONG") & bullish_hit) | ((direction == "SHORT") & bearish_hit)


def _fibonacci_mask(direction: pd.Series, retracement_outcomes, exec_index: pd.DatetimeIndex, fib_index: pd.DatetimeIndex, window_bars: int = 20) -> pd.Series:
    mask = pd.Series(False, index=exec_index)
    for o in retracement_outcomes:
        if not o.touched or o.level not in (0.382, 0.5, 0.618) or o.touch_pos is None:
            continue
        imp_direction = "LONG" if o.impulse.direction == "UP" else "SHORT"
        start_ts = fib_index[o.touch_pos]
        end_pos = min(len(fib_index) - 1, o.touch_pos + window_bars)
        end_ts = fib_index[end_pos]
        in_window = (exec_index >= start_ts) & (exec_index <= end_ts) & (direction == imp_direction)
        mask |= pd.Series(in_window, index=exec_index)
    return mask


def _strength_mask(direction: pd.Series, impulses, exec_index: pd.DatetimeIndex, fib_index: pd.DatetimeIndex, fib_df, fib_atr, window_bars: int = 20) -> pd.Series:
    from research.strategies.significant_move import classify_move_strength

    mask = pd.Series(False, index=exec_index)
    for imp in impulses:
        strength, _ = classify_move_strength(imp, fib_df, fib_atr)
        if strength != "STRONG_MOVE":
            continue
        imp_direction = "LONG" if imp.direction == "UP" else "SHORT"
        start_ts = fib_index[imp.end_pos]
        end_pos = min(len(fib_index) - 1, imp.end_pos + window_bars)
        end_ts = fib_index[end_pos]
        in_window = (exec_index >= start_ts) & (exec_index <= end_ts) & (direction == imp_direction)
        mask |= pd.Series(in_window, index=exec_index)
    return mask


def _liquidity_mask(direction: pd.Series, sweeps, exec_index: pd.DatetimeIndex, window_bars_minutes: int = 100) -> pd.Series:
    mask = pd.Series(False, index=exec_index)
    for s in sweeps:
        sweep_direction = "LONG" if s.pool.kind == "SSL" else "SHORT"  # SSL swept -> bullish reversal bias
        start_ts = s.sweep_ts
        end_ts = s.sweep_ts + pd.Timedelta(minutes=window_bars_minutes)
        in_window = (exec_index >= start_ts) & (exec_index <= end_ts) & (direction == sweep_direction)
        mask |= pd.Series(in_window, index=exec_index)
    return mask


def _orb_mask(direction: pd.Series, opening_ranges, exec_index: pd.DatetimeIndex, window_hours: int = 4) -> pd.Series:
    mask = pd.Series(False, index=exec_index)
    for orr in opening_ranges:
        start_ts = orr.or_close_utc
        end_ts = orr.or_close_utc + pd.Timedelta(hours=window_hours)
        in_window = (exec_index >= start_ts) & (exec_index <= end_ts)
        mask |= pd.Series(in_window, index=exec_index)
    return mask


def run_ablation_matrix(ctx, forward_bars: int = 12, n_boot: int = 500, n_perm: int = 500) -> Dict[str, Dict]:
    exec_df = ctx.frames[ctx.execution_tf]
    fb = ctx.feature_bars
    fib_df = ctx.frames.get("M15", exec_df)
    fib_atr = ctx.atr_series.reindex(fib_df.index).ffill()

    direction = _baseline_direction(exec_df)
    has_direction = direction.notna()

    close = exec_df["close"]
    fwd_close = close.shift(-forward_bars)
    fwd_ret_atr = (fwd_close - close) / ctx.atr_series.replace(0, np.nan)
    signed_return = pd.Series(np.nan, index=exec_df.index)
    signed_return[direction == "LONG"] = fwd_ret_atr[direction == "LONG"]
    signed_return[direction == "SHORT"] = -fwd_ret_atr[direction == "SHORT"]

    masks = {
        "structure": _structure_mask(direction, fb),
        "regime": _regime_mask(direction, fb),
        "candle": _candle_mask(direction, ctx.patterns),
        "fibonacci": _fibonacci_mask(direction, ctx.retracement_outcomes, exec_df.index, fib_df.index),
        "strength": _strength_mask(direction, ctx.impulses, exec_df.index, fib_df.index, fib_df, fib_atr),
        "liquidity": _liquidity_mask(direction, ctx.liquidity_sweeps, exec_df.index),
        "orb": _orb_mask(direction, ctx.opening_ranges, exec_df.index),
    }

    stages = {
        "BASELINE": has_direction,
        "BASELINE_PLUS_STRUCTURE": has_direction & masks["structure"],
        "BASELINE_PLUS_REGIME": has_direction & masks["regime"],
        "BASELINE_PLUS_STRUCTURE_PLUS_REGIME": has_direction & masks["structure"] & masks["regime"],
        "BASELINE_PLUS_FIBONACCI": has_direction & masks["fibonacci"],
        "BASELINE_PLUS_CANDLE": has_direction & masks["candle"],
        "BASELINE_PLUS_STRENGTH": has_direction & masks["strength"],
        "BASELINE_PLUS_LIQUIDITY": has_direction & masks["liquidity"],
        "BASELINE_PLUS_ORB": has_direction & masks["orb"],
        "BASELINE_PLUS_DXY": None,  # DATA_UNAVAILABLE, see module docstring
        "FULL_CONTEXT": has_direction & masks["structure"] & masks["regime"] & masks["candle"]
        & masks["strength"] & masks["liquidity"] & masks["orb"],
    }

    results = {}
    for name, mask in stages.items():
        if mask is None:
            results[name] = {"verdict": "DATA_UNAVAILABLE", "note": "no DXY data, real or non-circular synthetic"}
            continue
        values = signed_return[mask].dropna().to_numpy()
        if len(values) < 2:
            results[name] = {"n": len(values), "verdict": "INSUFFICIENT_SAMPLE"}
            continue
        ci = bootstrap_mean_ci(values, n_boot=n_boot)
        perm = permutation_negative_control(values, n_perm=n_perm)
        statistically_distinguishable = ci["excludes_zero"] and perm["p_value"] <= 0.05
        mean_val = float(values.mean())
        if not statistically_distinguishable:
            verdict = "NO_INFORMATION_DEMONSTRATED"
        elif mean_val > 0:
            verdict = "INFORMATION_PRESENT_BENEFICIAL"
        else:
            verdict = "INFORMATION_PRESENT_HARMFUL"
        results[name] = {
            "n": int(len(values)), "mean_signed_return_atr": mean_val,
            "bootstrap_ci": ci, "permutation": perm, "verdict": verdict,
        }
    return results


if __name__ == "__main__":
    from research.core.feature_bar import build_symbol_engine_data
    from research.data.synthetic import generate_multi_symbol_dataset

    ds = generate_multi_symbol_dataset(["EURUSD"], n_days=180)
    data = build_symbol_engine_data("EURUSD", ds["EURUSD"].bars)
    results = run_ablation_matrix(data)
    for stage, r in results.items():
        summary = {k: v for k, v in r.items() if k in ("n", "mean_signed_return_atr", "verdict")}
        print(stage, summary)
    print("OK")
