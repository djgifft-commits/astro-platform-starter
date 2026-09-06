"""
Phase 9I — Do named candlestick patterns add information beyond the
primitive anatomy measurements they are built from?

Reuses research/core/candle_anatomy.py entirely (compute_anatomy for
primitives, recognize_patterns for the named-pattern layer) -- no new
candle-geometry logic. This module only adds the specific nested
information test Phase 9B asks for: bucket the SAME ATR-normalized
signed-forward-return target (same methodology as research/backtest/
bias_experiment.py and ablation_matrix.py) by (a) primitive anatomy
percentile bins alone, and (b) primitive bins conditional on a named
pattern also firing, and check whether (b) is distinguishable from (a).
"""
from __future__ import annotations

from typing import Dict

import numpy as np
import pandas as pd

from research.backtest.validation import bootstrap_mean_ci, permutation_negative_control


def _signed_forward_return(exec_df: pd.DataFrame, atr: pd.Series, direction: pd.Series, forward_bars: int) -> pd.Series:
    close = exec_df["close"]
    fwd_close = close.shift(-forward_bars)
    fwd_ret_atr = (fwd_close - close) / atr.replace(0, np.nan)
    signed = pd.Series(np.nan, index=exec_df.index)
    bullish = direction == "LONG"
    bearish = direction == "SHORT"
    signed[bullish] = fwd_ret_atr[bullish]
    signed[bearish] = -fwd_ret_atr[bearish]
    return signed


def run_candle_pattern_ablation(ctx, forward_bars: int = 12, n_boot: int = 500, n_perm: int = 500) -> Dict[str, Dict]:
    exec_df = ctx.frames[ctx.execution_tf]
    patterns = ctx.patterns

    # primitive-only "signal": plain candle-close direction (close vs
    # open), with NO body-strength gate -- gating on a strong body would
    # structurally exclude every small-body reversal pattern (doji,
    # hammer, pin_bar, spinning_top) from ever appearing in the tested
    # population, since those patterns are DEFINED by a small body. The
    # baseline must remain neutral to primitive geometry so every named
    # pattern gets a fair chance to show up and be tested against it.
    direction = pd.Series(np.nan, index=exec_df.index, dtype=object)
    direction[exec_df["close"] > exec_df["open"]] = "LONG"
    direction[exec_df["close"] < exec_df["open"]] = "SHORT"

    signed_return = _signed_forward_return(exec_df, ctx.atr_series, direction, forward_bars)
    primitive_mask = direction.notna()

    results: Dict[str, Dict] = {}
    primitive_values = signed_return[primitive_mask].dropna().to_numpy()
    if len(primitive_values) >= 2:
        results["PRIMITIVE_ANATOMY_ONLY"] = {
            "n": len(primitive_values), "mean_signed_return_atr": float(primitive_values.mean()),
            "bootstrap_ci": bootstrap_mean_ci(primitive_values, n_boot=n_boot),
        }

    named_pattern_cols = [c for c in patterns.columns]
    for pattern_name in named_pattern_cols:
        pattern_hit = patterns[pattern_name].reindex(exec_df.index).fillna(False)
        mask = primitive_mask & pattern_hit
        values = signed_return[mask].dropna().to_numpy()
        if len(values) < 30:
            results[pattern_name] = {"n": len(values), "verdict": "INSUFFICIENT_SAMPLE"}
            continue
        ci = bootstrap_mean_ci(values, n_boot=n_boot)
        perm = permutation_negative_control(values, n_perm=n_perm)
        baseline_ci = results.get("PRIMITIVE_ANATOMY_ONLY", {}).get("bootstrap_ci", {})
        distinguishable = bool(baseline_ci) and (
            ci["ci_low"] > baseline_ci["ci_high"] or ci["ci_high"] < baseline_ci["ci_low"]
        )
        verdict = "INFORMATION_PRESENT" if (ci["excludes_zero"] and perm["p_value"] <= 0.05 and distinguishable) else "NO_INFORMATION_DEMONSTRATED"
        results[pattern_name] = {
            "n": int(len(values)), "mean_signed_return_atr": float(values.mean()),
            "bootstrap_ci": ci, "permutation": perm,
            "distinguishable_from_primitive_baseline": distinguishable,
            "verdict": verdict,
        }
    return results


if __name__ == "__main__":
    from research.core.feature_bar import build_symbol_engine_data
    from research.data.synthetic import generate_multi_symbol_dataset

    ds = generate_multi_symbol_dataset(["EURUSD"], n_days=300)
    ctx = build_symbol_engine_data("EURUSD", ds["EURUSD"].bars)
    results = run_candle_pattern_ablation(ctx)
    for name, r in results.items():
        print(name, {k: v for k, v in r.items() if k in ("n", "mean_signed_return_atr", "distinguishable_from_primitive_baseline", "verdict")})
    n_info = sum(1 for r in results.values() if r.get("verdict") == "INFORMATION_PRESENT")
    print(f"\n{n_info} of {len(results)-1} named patterns showed information beyond primitive anatomy")
    print("OK")
