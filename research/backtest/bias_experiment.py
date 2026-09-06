"""
Phase 8F — Nested bias experiment.

Tests whether directional bias contains predictive information on its
own, and whether adding structure/regime confirmation improves that
information, via three nested conditions on the SAME forward-return
target (never a full trade simulation -- this isolates the bias signal
itself from any strategy's entry/exit mechanics):

  BIAS ONLY:            bias_4state in {BULLISH, BEARISH}
  BIAS + STRUCTURE:     ... AND regime_structure_state agrees with bias
  BIAS + STRUCTURE + REGIME:  ... AND regime_direction also agrees

For each condition, the target is the ATR-normalized forward return over
`forward_bars`, SIGNED so that "correct" bias always contributes
positively (BULLISH forward return as-is, BEARISH forward return
negated) -- so a strategy with zero information gives a signed-return
mean of ~0, and genuine information gives a positive mean. This is
assessed with the same bootstrap CI + permutation negative control
machinery as every other claim in this project (research/backtest/
validation.py), never eyeballed.
"""
from __future__ import annotations

from typing import Dict

import numpy as np
import pandas as pd

from research.backtest.validation import bootstrap_mean_ci, permutation_negative_control


def _signed_forward_return(fb: pd.DataFrame, exec_df: pd.DataFrame, atr: pd.Series, forward_bars: int) -> pd.Series:
    close = exec_df["close"]
    fwd_close = close.shift(-forward_bars)
    fwd_ret_atr = (fwd_close - close) / atr.replace(0, np.nan)

    bullish = fb["bias_bias_4state"] == "BULLISH"
    bearish = fb["bias_bias_4state"] == "BEARISH"
    signed = pd.Series(np.nan, index=fb.index)
    signed[bullish] = fwd_ret_atr[bullish]
    signed[bearish] = -fwd_ret_atr[bearish]
    return signed


def run_nested_bias_experiment(ctx, forward_bars: int = 12, n_boot: int = 600, n_perm: int = 600) -> Dict[str, Dict]:
    fb = ctx.feature_bars
    exec_df = ctx.frames[ctx.execution_tf]
    atr = ctx.atr_series

    signed_return = _signed_forward_return(fb, exec_df, atr, forward_bars)

    bullish = fb["bias_bias_4state"] == "BULLISH"
    bearish = fb["bias_bias_4state"] == "BEARISH"
    bias_only_mask = bullish | bearish

    struct_agrees = (
        (bullish & (fb["regime_structure_state"] == "LONG"))
        | (bearish & (fb["regime_structure_state"] == "SHORT"))
    )
    bias_structure_mask = bias_only_mask & struct_agrees

    regime_agrees = (
        (bullish & (fb["regime_direction"] == "LONG"))
        | (bearish & (fb["regime_direction"] == "SHORT"))
    )
    bias_structure_regime_mask = bias_structure_mask & regime_agrees

    conditions = {
        "BIAS_ONLY": bias_only_mask,
        "BIAS_PLUS_STRUCTURE": bias_structure_mask,
        "BIAS_PLUS_STRUCTURE_PLUS_REGIME": bias_structure_regime_mask,
    }

    results = {}
    for name, mask in conditions.items():
        values = signed_return[mask].dropna().to_numpy()
        if len(values) < 2:
            results[name] = {"n": len(values), "verdict": "INSUFFICIENT_SAMPLE"}
            continue
        ci = bootstrap_mean_ci(values, n_boot=n_boot)
        perm = permutation_negative_control(values, n_perm=n_perm)
        verdict = (
            "INFORMATION_PRESENT" if ci["excludes_zero"] and perm["p_value"] <= 0.05
            else "NO_INFORMATION_DEMONSTRATED"
        )
        results[name] = {
            "n": int(len(values)),
            "mean_signed_return_atr": float(values.mean()),
            "bootstrap_ci": ci,
            "permutation": perm,
            "verdict": verdict,
        }
    return results


if __name__ == "__main__":
    from research.core.feature_bar import build_symbol_engine_data
    from research.data.synthetic import generate_multi_symbol_dataset

    ds = generate_multi_symbol_dataset(["EURUSD"], n_days=180)
    data = build_symbol_engine_data("EURUSD", ds["EURUSD"].bars)
    results = run_nested_bias_experiment(data)
    for name, r in results.items():
        print(name, r)
    print("OK")
