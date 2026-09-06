"""
Phase 9C — OR-specific feature ablation: A (OR ONLY) through G (FULL MODEL).

Phase 9B's generalized ablation_matrix.py used a deliberately trivial,
non-OR baseline ("close breaks the prior bar's high/low") so it could
isolate whether each feature carries information at all, independent of
any one strategy. Phase 9C asks a narrower, OR-specific question instead:
given that a candidate ALREADY comes from a real OR breakout, does adding
market structure, then each of significant-move/liquidity/Fibonacci/candle
anatomy on top of structure, change the same ATR-normalized signed-forward
-return target? This determines the minimum feature set that survives,
for the OR strategy specifically -- not a generic feature-value study.

REUSE: the five per-feature masks (_structure_mask, _strength_mask,
_liquidity_mask, _fibonacci_mask, _candle_mask) are imported directly from
research/backtest/ablation_matrix.py, not reimplemented -- only the
baseline direction signal (A: an actual OR breakout, not "close breaks
prior bar's high/low") and the nesting (B=A+structure; C-F=B+exactly one
more feature; G=the real OpeningRangeStateMachine's own executed trades)
are new here.
"""
from __future__ import annotations

from typing import Dict

import numpy as np
import pandas as pd

from research.backtest.ablation_matrix import (
    _candle_mask,
    _fibonacci_mask,
    _liquidity_mask,
    _strength_mask,
    _structure_mask,
)
from research.backtest.validation import bootstrap_mean_ci, permutation_negative_control


def _or_breakout_direction(ctx, monitor_bars: int = 48) -> pd.Series:
    """A: OR ONLY. The raw M5-close-beyond-OR-boundary condition, with NO
    bias-hierarchy check, no M1 entry trigger, no SL/TP -- exactly the
    'first thing the strategy notices' signal, so every later comparison
    (B-G) is measured against what OR alone would have said."""
    exec_df = ctx.frames[ctx.execution_tf]
    direction = pd.Series(np.nan, index=exec_df.index, dtype=object)
    for orr in ctx.opening_ranges:
        if not orr.sufficient_data or orr.or_range_size <= 0:
            continue
        window = exec_df.loc[(exec_df.index > orr.or_close_utc)].iloc[:monitor_bars]
        for ts, row in window.iterrows():
            if row["close"] > orr.or_high:
                direction.loc[ts] = "LONG"
                break
            if row["close"] < orr.or_low:
                direction.loc[ts] = "SHORT"
                break
    return direction


def run_or_ablation(ctx, or_v2_full_model_trades: list, forward_bars: int = 12,
                     n_boot: int = 500, n_perm: int = 500) -> Dict[str, Dict]:
    exec_df = ctx.frames[ctx.execution_tf]
    fb = ctx.feature_bars
    fib_df = ctx.frames.get("M15", exec_df)
    fib_atr = ctx.atr_series.reindex(fib_df.index).ffill()

    direction = _or_breakout_direction(ctx)
    has_direction = direction.notna()

    close = exec_df["close"]
    fwd_close = close.shift(-forward_bars)
    fwd_ret_atr = (fwd_close - close) / ctx.atr_series.replace(0, np.nan)
    signed_return = pd.Series(np.nan, index=exec_df.index)
    signed_return[direction == "LONG"] = fwd_ret_atr[direction == "LONG"]
    signed_return[direction == "SHORT"] = -fwd_ret_atr[direction == "SHORT"]

    structure = _structure_mask(direction, fb)
    strength = _strength_mask(direction, ctx.impulses, exec_df.index, fib_df.index, fib_df, fib_atr)
    liquidity = _liquidity_mask(direction, ctx.liquidity_sweeps, exec_df.index)
    fibonacci = _fibonacci_mask(direction, ctx.retracement_outcomes, exec_df.index, fib_df.index)
    candle = _candle_mask(direction, ctx.patterns)

    stages = {
        "A_OR_ONLY": has_direction,
        "B_OR_PLUS_STRUCTURE": has_direction & structure,
        "C_OR_STRUCTURE_PLUS_SIGNIFICANT_MOVE": has_direction & structure & strength,
        "D_OR_STRUCTURE_PLUS_LIQUIDITY": has_direction & structure & liquidity,
        "E_OR_STRUCTURE_PLUS_FIBONACCI": has_direction & structure & fibonacci,
        "F_OR_STRUCTURE_PLUS_CANDLE_ANATOMY": has_direction & structure & candle,
    }

    results: Dict[str, Dict] = {}
    for name, mask in stages.items():
        values = signed_return[mask].dropna().to_numpy()
        if len(values) < 2:
            results[name] = {"n": len(values), "verdict": "INSUFFICIENT_SAMPLE"}
            continue
        ci = bootstrap_mean_ci(values, n_boot=n_boot)
        perm = permutation_negative_control(values, n_perm=n_perm)
        distinguishable = ci["excludes_zero"] and perm["p_value"] <= 0.05
        mean_val = float(values.mean())
        verdict = ("NO_INFORMATION_DEMONSTRATED" if not distinguishable else
                   ("INFORMATION_PRESENT_BENEFICIAL" if mean_val > 0 else "INFORMATION_PRESENT_HARMFUL"))
        results[name] = {"n": int(len(values)), "mean_signed_return_atr": mean_val,
                          "bootstrap_ci": ci, "permutation": perm, "verdict": verdict}

    # G: FULL MODEL -- the actual OpeningRangeStateMachine's own executed
    # trades (real entry price, real SL/TP, real cost), not a proxy signal
    # -- so this cell is measured in R-multiples, not ATR-normalized
    # forward return, and is not directly comparable cell-for-cell to A-F
    # (different units); it answers "does the fully-built strategy do
    # better than the raw OR signal alone," not "is G's raw signal
    # stronger."
    rs = np.array([t.r_multiple for t in or_v2_full_model_trades])
    if len(rs) < 2:
        results["G_FULL_MODEL"] = {"n": len(rs), "verdict": "INSUFFICIENT_SAMPLE",
                                    "note": "units are R-multiple (real trades), not ATR-normalized return -- not directly comparable to A-F"}
    else:
        ci = bootstrap_mean_ci(rs, n_boot=n_boot)
        perm = permutation_negative_control(rs, n_perm=n_perm)
        distinguishable = ci["excludes_zero"] and perm["p_value"] <= 0.05
        mean_val = float(rs.mean())
        verdict = ("NO_INFORMATION_DEMONSTRATED" if not distinguishable else
                   ("INFORMATION_PRESENT_BENEFICIAL" if mean_val > 0 else "INFORMATION_PRESENT_HARMFUL"))
        results["G_FULL_MODEL"] = {"n": int(len(rs)), "mean_r_multiple": mean_val,
                                    "bootstrap_ci": ci, "permutation": perm, "verdict": verdict,
                                    "note": "units are R-multiple (real trades), not ATR-normalized return -- not directly comparable to A-F"}

    n_a = results["A_OR_ONLY"].get("n", 0)
    minimal_survivors = [name for name, r in results.items()
                          if name != "A_OR_ONLY" and r.get("verdict", "").startswith("INFORMATION_PRESENT")]
    results["_summary"] = {
        "n_candidates_A_OR_ONLY": n_a,
        "stages_beyond_A_showing_information": minimal_survivors,
        "note": "G is not assumed superior -- compare verdicts, not just presence of a cell",
    }
    return results


if __name__ == "__main__":
    from research.backtest.engine import BacktestConfig, run_backtest
    from research.core.feature_bar import build_symbol_engine_data
    from research.data.synthetic import generate_multi_symbol_dataset
    from research.strategies.opening_range_v2 import OpeningRangeStateMachine

    ds = generate_multi_symbol_dataset(["EURUSD"], n_days=300)
    ctx = build_symbol_engine_data("EURUSD", ds["EURUSD"].bars)
    run = run_backtest(ctx, OpeningRangeStateMachine(entry_family="breakout"), BacktestConfig())

    results = run_or_ablation(ctx, run.trades)
    for stage, r in results.items():
        if stage == "_summary":
            continue
        print(stage, {k: v for k, v in r.items() if k in ("n", "mean_signed_return_atr", "mean_r_multiple", "verdict")})
    print("summary:", results["_summary"])
    print("OK")
