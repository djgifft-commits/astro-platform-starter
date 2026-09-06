"""
Phase 9G — Fibonacci retracement depth: information content AFTER
structure is already known.

Reuses research/core/fibonacci.py's impulse/retracement engine entirely
(no new retracement-measurement logic). This module only adds the
specific depth-bin classification and nested test Phase 9B asks for:
does knowing the EXACT retracement depth (23.6/38.2/50/61.8/78.6% and the
continuous bins between them) add information about continuation
probability, over and above already knowing the impulse's structure was
preserved (Phase 7's `structure_preserved` flag)? If depth adds nothing
once structure is known, "which Fibonacci level" is not doing any real
work distinct from the structural fact already captured elsewhere.
"""
from __future__ import annotations

from typing import Dict

import numpy as np
import pandas as pd

from research.backtest.validation import bootstrap_mean_ci, permutation_negative_control
from research.core.fibonacci import CONTROL_LEVELS, FIB_LEVELS


def depth_bin(level: float) -> str:
    """Six explicit bins Phase 9B names: <23.6%, 23.6-38.2%, 38.2-50%,
    50-61.8%, 61.8-78.6%, >78.6%, folded into the four broader labels
    (SHALLOW/NORMAL/DEEP/NO_RETRACEMENT) also requested."""
    if level < 0.236:
        return "NO_RETRACEMENT"
    if level <= 0.382:
        return "SHALLOW_RETRACEMENT"
    if level <= 0.618:
        return "NORMAL_RETRACEMENT"
    if level <= 0.786:
        return "DEEP_RETRACEMENT"
    return "NO_RETRACEMENT"


def fine_depth_bucket(level: float) -> str:
    if level < 0.236:
        return "<23.6%"
    if level <= 0.382:
        return "23.6-38.2%"
    if level <= 0.5:
        return "38.2-50%"
    if level <= 0.618:
        return "50-61.8%"
    if level <= 0.786:
        return "61.8-78.6%"
    return ">78.6%"


def run_depth_information_experiment(ctx, n_boot: int = 500, n_perm: int = 500) -> Dict[str, Dict]:
    """For every retracement outcome (both Fibonacci and non-Fibonacci
    control levels -- research/core/fibonacci.py already computes both),
    bucket by depth and measure `displacement_after` (ATR-normalized move
    in the impulse direction following the touch -- already computed
    causally by evaluate_retracements). Two nested conditions:

      STRUCTURE_ONLY:        outcome.structure_preserved == True (ignore depth)
      STRUCTURE_PLUS_DEPTH:  same, broken out by fine_depth_bucket

    If STRUCTURE_PLUS_DEPTH's per-bucket means are not distinguishable
    from STRUCTURE_ONLY's pooled mean (via bootstrap CI overlap), depth
    is not adding information beyond the already-known structural fact.
    """
    outcomes = [o for o in ctx.retracement_outcomes if o.touched and o.structure_preserved and o.displacement_after is not None]

    pooled = np.array([o.displacement_after for o in outcomes])
    structure_only = {"n": len(pooled), "mean_displacement_after": float(pooled.mean()) if len(pooled) else None}
    if len(pooled) >= 2:
        structure_only["bootstrap_ci"] = bootstrap_mean_ci(pooled, n_boot=n_boot)

    by_bucket: Dict[str, Dict] = {}
    buckets: Dict[str, list] = {}
    for o in outcomes:
        buckets.setdefault(fine_depth_bucket(o.level), []).append(o.displacement_after)

    order = ["<23.6%", "23.6-38.2%", "38.2-50%", "50-61.8%", "61.8-78.6%", ">78.6%"]
    for bucket in order:
        values = np.array(buckets.get(bucket, []))
        if len(values) < 2:
            by_bucket[bucket] = {"n": len(values), "verdict": "INSUFFICIENT_SAMPLE"}
            continue
        ci = bootstrap_mean_ci(values, n_boot=n_boot)
        perm = permutation_negative_control(values, n_perm=n_perm)
        overlaps_pooled = not (ci["ci_low"] > structure_only["bootstrap_ci"]["ci_high"]
                                or ci["ci_high"] < structure_only["bootstrap_ci"]["ci_low"])
        by_bucket[bucket] = {
            "n": len(values), "mean_displacement_after": float(values.mean()),
            "bootstrap_ci": ci, "permutation": perm,
            "distinguishable_from_structure_only_pool": not overlaps_pooled,
        }

    is_fib_bucket = {"<23.6%": False, "23.6-38.2%": True, "38.2-50%": True, "50-61.8%": True,
                      "61.8-78.6%": True, ">78.6%": False}

    n_distinguishable = sum(1 for b in by_bucket.values() if b.get("distinguishable_from_structure_only_pool"))
    verdict = "INFORMATION_PRESENT" if n_distinguishable >= 2 else "NO_INFORMATION_DEMONSTRATED"

    return {
        "structure_only_baseline": structure_only,
        "depth_buckets": by_bucket,
        "n_buckets_distinguishable_from_baseline": n_distinguishable,
        "verdict": verdict,
    }


if __name__ == "__main__":
    from research.core.feature_bar import build_symbol_engine_data
    from research.data.synthetic import generate_multi_symbol_dataset

    ds = generate_multi_symbol_dataset(["EURUSD"], n_days=300)
    ctx = build_symbol_engine_data("EURUSD", ds["EURUSD"].bars)
    result = run_depth_information_experiment(ctx)
    print("STRUCTURE_ONLY baseline:", result["structure_only_baseline"])
    for bucket, stats in result["depth_buckets"].items():
        print(bucket, {k: v for k, v in stats.items() if k in ("n", "mean_displacement_after", "distinguishable_from_structure_only_pool", "verdict")})
    print("Overall verdict:", result["verdict"])
    print("OK")
