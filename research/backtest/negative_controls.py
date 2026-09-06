"""
Phase 8X — Negative controls.

Every major claimed feature gets a control where the feature's real
informational content is destroyed by permutation while its surface
statistics (event count, timing) are preserved. A result that disappears
into its control is NOT evidence of an edge -- exactly the standard
already applied to Fibonacci levels (Phase 7, vs. non-Fibonacci control
depths) and to every strategy's raw R-multiples (the sign-flip permutation
test in research/backtest/validation.py). This module adds three more,
named explicitly in the MASTER COMMAND: structure, move-strength, and
hedge pairing.
"""
from __future__ import annotations

import dataclasses
from typing import Dict

import numpy as np
import pandas as pd

from research.backtest.engine import BacktestConfig, run_backtest
from research.backtest.metrics import trade_stats
from research.core.structure import StructureEvent
from research.risk.hedge import rolling_correlation


def permuted_structure_control(ctx, strategy_cls, config: BacktestConfig, seed: int = 0, **strategy_kwargs) -> Dict:
    """Real structure events vs. the SAME events with `.direction` shuffled
    (timestamps, kind, and broken_swing_price all held fixed -- only which
    events are BULLISH vs BEARISH is randomized). Strategies that key off
    structure direction (structure_continuation, structure_reversal)
    should lose most of their apparent edge once direction is scrambled;
    if they do not, their edge does not actually depend on real structure
    direction."""
    rng = np.random.default_rng(seed)

    real_strategy = strategy_cls(**strategy_kwargs)
    real_run = run_backtest(ctx, real_strategy, config)
    real_stats = trade_stats(real_run.trades)

    shuffled_directions = list(d.direction for d in ctx.structure_events)
    rng.shuffle(shuffled_directions)
    shuffled_events = [
        StructureEvent(e.index_pos, e.timestamp, e.kind, new_dir, e.broken_swing_price)
        for e, new_dir in zip(ctx.structure_events, shuffled_directions)
    ]
    shuffled_ctx = dataclasses.replace(ctx, structure_events=shuffled_events)

    control_strategy = strategy_cls(**strategy_kwargs)
    control_run = run_backtest(shuffled_ctx, control_strategy, config)
    control_stats = trade_stats(control_run.trades)

    return {
        "real": real_stats,
        "permuted_structure_direction": control_stats,
        "edge_survives_control": bool(
            real_stats["n"] > 0 and control_stats["n"] > 0
            and real_stats["expectancy_r"] > control_stats["expectancy_r"]
            and real_stats["expectancy_r"] > 0
        ),
    }


def permuted_strength_control(ctx, required_strength: str, config: BacktestConfig, seed: int = 0) -> Dict:
    """Real STRONG/MODERATE/WEAK move-strength labels vs. the SAME labels
    shuffled across the SAME set of impulses (so entry timing/count is
    identical; only which impulse is called "strong" is randomized)."""
    from research.strategies.significant_move import SignificantMoveContinuation, classify_move_strength

    rng = np.random.default_rng(seed)
    fib_df = ctx.frames.get("M15", ctx.frames[ctx.execution_tf])
    fib_atr = ctx.atr_series.reindex(fib_df.index).ffill()

    real_labels = {}
    for imp in ctx.impulses:
        strength, _ = classify_move_strength(imp, fib_df, fib_atr)
        real_labels[id(imp)] = strength

    shuffled_values = list(real_labels.values())
    rng.shuffle(shuffled_values)
    shuffled_labels = dict(zip(real_labels.keys(), shuffled_values))

    real_strategy = SignificantMoveContinuation(required_strength, strength_override=real_labels)
    real_run = run_backtest(ctx, real_strategy, config)

    control_strategy = SignificantMoveContinuation(required_strength, strength_override=shuffled_labels)
    control_run = run_backtest(ctx, control_strategy, config)

    real_stats = trade_stats(real_run.trades)
    control_stats = trade_stats(control_run.trades)
    return {
        "real": real_stats,
        "permuted_strength_label": control_stats,
        "edge_survives_control": bool(
            real_stats["n"] > 0 and control_stats["n"] > 0
            and real_stats["expectancy_r"] > control_stats["expectancy_r"]
            and real_stats["expectancy_r"] > 0
        ),
    }


def permuted_hedge_pairing_control(ret_a: pd.Series, ret_b: pd.Series, window: int = 100, seed: int = 0) -> Dict:
    """Real (time-aligned) rolling correlation between two symbols' return
    streams vs. the same two series with `b`'s VALUES shuffled (breaking
    the time relationship but preserving its marginal distribution). A
    real hedge relationship should show much larger |correlation| than
    this shuffled control."""
    rng = np.random.default_rng(seed)

    real_corr = rolling_correlation(ret_a, ret_b, window=window)

    b_values = ret_b.to_numpy().copy()
    rng.shuffle(b_values)
    shuffled_b = pd.Series(b_values, index=ret_b.index)
    control_corr = rolling_correlation(ret_a, shuffled_b, window=window)

    real_mean_abs = float(real_corr.dropna().abs().mean())
    control_mean_abs = float(control_corr.dropna().abs().mean())
    return {
        "real_mean_abs_correlation": real_mean_abs,
        "permuted_pairing_mean_abs_correlation": control_mean_abs,
        "edge_survives_control": bool(real_mean_abs > control_mean_abs * 1.5),
    }


if __name__ == "__main__":
    from research.core.feature_bar import build_symbol_engine_data
    from research.data.synthetic import generate_multi_symbol_dataset
    from research.strategies.structure_continuation import StructureContinuation
    from research.strategies.structure_reversal import StructureReversal

    ds = generate_multi_symbol_dataset(
        ["EURUSD", "GBPUSD"], n_days=180, factor_loadings={"EURUSD": 0.75, "GBPUSD": 0.65}
    )
    data = {sym: build_symbol_engine_data(sym, d.bars) for sym, d in ds.items()}
    cfg = BacktestConfig()

    print("=== Structure direction control (StructureContinuation) ===")
    print(permuted_structure_control(data["EURUSD"], StructureContinuation, cfg))

    print("=== Structure direction control (StructureReversal) ===")
    print(permuted_structure_control(data["EURUSD"], StructureReversal, cfg))

    print("=== Move-strength label control ===")
    print(permuted_strength_control(data["EURUSD"], "STRONG_MOVE", cfg))

    print("=== Hedge pairing control ===")
    ret_a = data["EURUSD"].frames["M5"]["close"].pct_change()
    ret_b = data["GBPUSD"].frames["M5"]["close"].pct_change()
    print(permuted_hedge_pairing_control(ret_a, ret_b))
    print("OK")
