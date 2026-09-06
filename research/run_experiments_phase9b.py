"""
Phase 9B orchestrator. Runs the full opening_range_v2 (1UP/2DOWN) research
matrix -- all 3 entry families (breakout/retest/reversal) x the same
8-symbol synthetic universe used in Phase 8 -- plus every genuinely new
Phase 9B experiment, and writes JSON to research/results_9b/, kept
separate from Phase 7's research/results/ and Phase 8's research/results_8/
so none silently overwrites or is mistaken for another.

Still 100% synthetic data -- see research/config.py DATA DISCLOSURE and
audit/PHASE_9A_REPOSITORY_AND_GOVERNANCE_AUDIT.md.

Run: research/.venv/bin/python -m research.run_experiments_phase9b
"""
from __future__ import annotations

import dataclasses
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from research.backtest.candle_pattern_ablation import run_candle_pattern_ablation
from research.backtest.engine import BacktestConfig, run_backtest
from research.backtest.fibonacci_depth_experiment import run_depth_information_experiment
from research.backtest.metrics import trade_stats
from research.backtest.mutation_testing import run_all_mutation_tests
from research.backtest.no_trade_funnel_v2 import build_detailed_funnel
from research.backtest.out_of_sample_phase9b import run_locked_out_of_sample_test_9b
from research.backtest.portfolio_gating import simulate_portfolio_gating, summarize_gating
from research.backtest.regime_gating import run_regime_gate_comparison
from research.backtest.validation import (
    benjamini_hochberg,
    bootstrap_mean_ci,
    label_verdict,
    permutation_negative_control,
    purged_embargoed_folds,
    walk_forward_folds,
)
from research.core.feature_bar import build_symbol_engine_data
from research.data.synthetic import generate_multi_symbol_dataset
from research.risk.position_sizing import RiskLimits
from research.strategies.opening_range_v2 import OpeningRangeStateMachine

RESULTS_DIR = Path(__file__).parent / "results_9b"
SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD", "XAUUSD"]
N_DAYS = 300
FACTOR_LOADINGS = {
    "EURUSD": 0.75, "GBPUSD": 0.65, "USDJPY": -0.30, "AUDUSD": 0.55,
    "USDCAD": -0.45, "USDCHF": -0.60, "NZDUSD": 0.50, "XAUUSD": 0.20,
}
ENTRY_FAMILIES = ("breakout", "retest", "reversal")
# Narrowed subset for the most expensive per-symbol analyses (bootstrap +
# permutation over the full retracement/candle population per symbol);
# narrowing documented explicitly here rather than silently running all 8,
# same convention as research/run_experiments_phase8.py.
REPRESENTATIVE_SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD"]
HEDGE_PAIRS = [("EURUSD", "GBPUSD"), ("EURUSD", "USDCHF"), ("AUDUSD", "NZDUSD")]


def json_default(o):
    if isinstance(o, pd.Timestamp):
        return o.isoformat()
    if isinstance(o, (np.floating, np.integer)):
        return o.item()
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, float) and (o != o or abs(o) == float("inf")):
        return None
    if dataclasses.is_dataclass(o):
        return dataclasses.asdict(o)
    if isinstance(o, (set,)):
        return list(o)
    return str(o)


def dump(name: str, obj) -> None:
    path = RESULTS_DIR / f"{name}.json"
    with open(path, "w") as f:
        json.dump(obj, f, default=json_default, indent=2)
    print(f"  wrote {path} ({path.stat().st_size / 1024:.1f} KB)")


def main():
    t_start = time.time()
    RESULTS_DIR.mkdir(exist_ok=True)

    print(f"[1/10] Generating synthetic dataset: {len(SYMBOLS)} symbols x {N_DAYS} days...")
    dataset = generate_multi_symbol_dataset(SYMBOLS, n_days=N_DAYS, factor_loadings=FACTOR_LOADINGS)

    print("[2/10] Building causal engine data per symbol...")
    engine_data = {}
    for sym, d in dataset.items():
        t0 = time.time()
        engine_data[sym] = build_symbol_engine_data(sym, d.bars)
        print(f"  {sym}: {time.time() - t0:.1f}s")

    base_config = BacktestConfig(sl_model="FIXED_ATR", sl_atr_mult=1.5, tp_model="FIXED_2R", exit_model="FIXED")

    print("[3/10] OR v2 matrix: 3 entry families x 8 symbols, full statistical validation...")
    matrix_rows = []
    trades_by_symbol_family = {sym: {} for sym in SYMBOLS}
    signals_rejected_by_symbol_family = {sym: {} for sym in SYMBOLS}
    all_pvalues = []

    for sym in SYMBOLS:
        ctx = engine_data[sym]
        for family in ENTRY_FAMILIES:
            strat = OpeningRangeStateMachine(entry_family=family)
            run = run_backtest(ctx, strat, base_config)
            trades_by_symbol_family[sym][family] = run.trades
            signals_rejected_by_symbol_family[sym][family] = (run.signals, run.rejected)
            stats = trade_stats(run.trades)
            rs = np.array([t.r_multiple for t in run.trades])
            ci = bootstrap_mean_ci(rs, n_boot=500) if len(rs) >= 2 else {"excludes_zero": False}
            perm = permutation_negative_control(rs, n_perm=500) if len(rs) >= 2 else {"p_value": 1.0}
            matrix_rows.append({"symbol": sym, "entry_family": family, **stats,
                                 "n_rejected_candidates": len(run.rejected),
                                 "bootstrap_ci": ci, "permutation": perm})
            all_pvalues.append(perm.get("p_value", 1.0))

    bh_survives = benjamini_hochberg(all_pvalues, alpha=0.05)
    for row, survives in zip(matrix_rows, bh_survives):
        row["bh_fdr_survives"] = bool(survives)
        sym, family = row["symbol"], row["entry_family"]
        trades = trades_by_symbol_family[sym][family]
        folds = walk_forward_folds(trades, n_folds=5)
        fold_stats = [trade_stats(test) for _, test in folds]
        verdict = label_verdict(row["n"], row["bootstrap_ci"], row["permutation"], fold_stats, row["bh_fdr_survives"])
        row["walk_forward_folds"] = fold_stats
        row["verdict"] = verdict.verdict
        row["verdict_reasons"] = verdict.reasons

        purged_folds = purged_embargoed_folds(trades, n_folds=5)
        row["purged_embargoed_summary"] = [
            {"fold": f.fold_index, "n_test": len(f.test), "n_purged": f.n_purged, "n_embargoed": f.n_embargoed}
            for f in purged_folds
        ]
    dump("or_v2_matrix", matrix_rows)

    print("[4/10] Detailed 13-stage no-trade funnel (3 families x 8 symbols)...")
    funnel_rows = []
    for sym in SYMBOLS:
        for family in ENTRY_FAMILIES:
            signals, rejected = signals_rejected_by_symbol_family[sym][family]
            funnel_rows.append({"symbol": sym, "entry_family": family,
                                 **build_detailed_funnel(signals, rejected)})
    dump("no_trade_funnel_v2", funnel_rows)

    print("[5/10] Regime gating comparison (breakout family, 8 symbols)...")
    regime_rows = []
    for sym in SYMBOLS:
        result = run_regime_gate_comparison(engine_data[sym], trades_by_symbol_family[sym]["breakout"])
        regime_rows.append({"symbol": sym, **result})
    dump("regime_gating", regime_rows)

    print(f"[6/10] Fibonacci depth information + candle pattern ablation ({REPRESENTATIVE_SYMBOLS})...")
    fib_rows, candle_rows = [], []
    for sym in REPRESENTATIVE_SYMBOLS:
        fib_rows.append({"symbol": sym, **run_depth_information_experiment(engine_data[sym])})
        candle_rows.append({"symbol": sym, "results": run_candle_pattern_ablation(engine_data[sym])})
    dump("fibonacci_depth_experiment", fib_rows)
    dump("candle_pattern_ablation", candle_rows)

    print("[7/10] New SL/TP models comparison (breakout family, 8 symbols)...")
    sl_tp_rows = []
    for sym in SYMBOLS:
        ctx = engine_data[sym]
        strat = OpeningRangeStateMachine(entry_family="breakout")
        for sl_model in ("FIXED_ATR", "BREAKOUT_CANDLE"):
            cfg = BacktestConfig(sl_model=sl_model, tp_model="FIXED_2R", exit_model="FIXED")
            run = run_backtest(ctx, strat, cfg)
            sl_tp_rows.append({"symbol": sym, "model_type": "SL", "model": sl_model, **trade_stats(run.trades)})
        for tp_model in ("FIXED_2R", "OR_OPPOSITE_BOUNDARY_TARGET", "LIQUIDITY_TARGET"):
            cfg = BacktestConfig(sl_model="FIXED_ATR", tp_model=tp_model, exit_model="FIXED")
            run = run_backtest(ctx, strat, cfg)
            sl_tp_rows.append({"symbol": sym, "model_type": "TP", "model": tp_model, **trade_stats(run.trades)})
    dump("sl_tp_v2_comparison", sl_tp_rows)

    print("[8/10] Cost sensitivity sweep (breakout family, 8 symbols)...")
    cost_rows = []
    for sym in SYMBOLS:
        ctx = engine_data[sym]
        strat = OpeningRangeStateMachine(entry_family="breakout")
        for name, mult in [("COST_NEUTRAL", 0.0), ("BASE_COST", 1.0), ("ADVERSE_COST", 2.0), ("STRESS_COST", 5.0)]:
            cfg = BacktestConfig(spread_multiplier=mult)
            run = run_backtest(ctx, strat, cfg)
            cost_rows.append({"symbol": sym, "cost_scenario": name, "multiplier": mult, **trade_stats(run.trades)})
    dump("cost_sensitivity", cost_rows)

    print(f"[9/10] Portfolio gating across correlated/uncorrelated pairs ({HEDGE_PAIRS})...")
    portfolio_rows = []
    limits = RiskLimits(max_open_positions=3, max_daily_loss_pct=0.03, max_consecutive_losses=5)
    for a, b in HEDGE_PAIRS:
        outcomes = simulate_portfolio_gating(
            {a: trades_by_symbol_family[a]["breakout"], b: trades_by_symbol_family[b]["breakout"]},
            limits=limits, correlated_symbol_pairs=[(a, b)],
        )
        portfolio_rows.append({"pair": f"{a}/{b}", **summarize_gating(outcomes)})
    dump("portfolio_gating", portfolio_rows)

    print("[10/10] Parameter robustness grid (EURUSD, breakout), out-of-sample lock, mutation tests...")
    robustness_rows = []
    for require_bias in (True, False):
        for sl_model in ("FIXED_ATR", "BREAKOUT_CANDLE"):
            for tp_model in ("FIXED_1R", "FIXED_2R", "FIXED_3R"):
                strat = OpeningRangeStateMachine(entry_family="breakout", require_bias_agreement=require_bias)
                cfg = BacktestConfig(sl_model=sl_model, tp_model=tp_model, exit_model="FIXED")
                run = run_backtest(engine_data["EURUSD"], strat, cfg)
                stats = trade_stats(run.trades)
                robustness_rows.append({"require_bias_agreement": require_bias, "sl_model": sl_model,
                                         "tp_model": tp_model, **stats})
    valid = [r for r in robustness_rows if r["n"] >= 30]
    positive = [r for r in valid if r["expectancy_r"] > 0]
    robustness_summary = {
        "n_configs_tested": len(robustness_rows),
        "n_configs_with_enough_trades": len(valid),
        "fraction_positive_expectancy": (len(positive) / len(valid)) if valid else None,
        "verdict": ("STABLE_PLATEAU" if valid and len(positive) / len(valid) >= 0.7 else
                    "ISOLATED_SPIKE" if valid and len(positive) / len(valid) <= 0.3 else
                    "MIXED_NOT_ROBUST" if valid else "INSUFFICIENT_SAMPLE"),
    }
    dump("robustness_perturbation", {"rows": robustness_rows, "summary": robustness_summary})

    oos_result = run_locked_out_of_sample_test_9b()
    dump("out_of_sample_locked", oos_result)

    mutation_results = run_all_mutation_tests()
    dump("mutation_tests", [{"name": n, "detected": d, "detail": det} for n, d, det in mutation_results])

    print(f"\nAll Phase 9B experiments complete in {time.time() - t_start:.1f}s. Results in {RESULTS_DIR}")


if __name__ == "__main__":
    main()
