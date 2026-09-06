"""
Phase 8 orchestrator. Runs the FULL Phase 7 matrix again (now under the
corrected cost model -- Phase 8AF fixed a missing exit-side spread
deduction, see audit report -- and the expanded regime taxonomy) plus
every genuinely new Phase 8 experiment, and writes JSON to
research/results_8/, kept separate from Phase 7's research/results/ so
neither silently overwrites or is mistaken for the other.

Still 100% synthetic data -- see research/config.py DATA DISCLOSURE and
audit/PHASE_8A_ARCHITECTURE_AUDIT.md Section 4.

Run: research/.venv/bin/python -m research.run_experiments_phase8
"""
from __future__ import annotations

import dataclasses
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from research.backtest.ablation import run_ablation
from research.backtest.ablation_matrix import run_ablation_matrix
from research.backtest.bias_experiment import run_nested_bias_experiment
from research.backtest.engine import BacktestConfig, run_backtest
from research.backtest.metrics import trade_stats
from research.backtest.mutation_testing import run_all_mutation_tests
from research.backtest.negative_controls import (
    permuted_hedge_pairing_control,
    permuted_strength_control,
    permuted_structure_control,
)
from research.backtest.no_trade_funnel import build_funnel
from research.backtest.out_of_sample import run_locked_out_of_sample_test
from research.backtest.robustness import run_parameter_perturbation, summarize_plateau
from research.backtest.strategy_selector import compare_selectors
from research.backtest.trend_only import run_trend_only_comparison
from research.backtest.validation import (
    benjamini_hochberg,
    bootstrap_mean_ci,
    permutation_negative_control,
    purged_embargoed_folds,
    walk_forward_folds,
    label_verdict,
)
from research.core.feature_bar import build_symbol_engine_data
from research.data.synthetic import generate_multi_symbol_dataset
from research.risk.hedge import build_hedge_correlation_report
from research.risk.sl_models import SL_MODELS
from research.risk.tp_models import TP_MODELS
from research.strategies.opening_range import OpeningRangeBreakout
from research.strategies.significant_move import SignificantMoveContinuation
from research.strategies.structure_continuation import StructureContinuation
from research.strategies.structure_reversal import StructureReversal
from research.strategies.trend_pullback import TrendPullback

RESULTS_DIR = Path(__file__).parent / "results_8"
SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD", "XAUUSD"]
N_DAYS = 300
FACTOR_LOADINGS = {
    "EURUSD": 0.75, "GBPUSD": 0.65, "USDJPY": -0.30, "AUDUSD": 0.55,
    "USDCAD": -0.45, "USDCHF": -0.60, "NZDUSD": 0.50, "XAUUSD": 0.20,
}


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
    return str(o)


def dump(name: str, obj) -> None:
    path = RESULTS_DIR / f"{name}.json"
    with open(path, "w") as f:
        json.dump(obj, f, default=json_default, indent=2)
    print(f"  wrote {path} ({path.stat().st_size / 1024:.1f} KB)")


def strategy_configs():
    return [
        ("opening_range_continuation", OpeningRangeBreakout(variant="continuation")),
        ("opening_range_retest", OpeningRangeBreakout(variant="retest")),
        ("opening_range_failed_breakout", OpeningRangeBreakout(variant="failed_breakout")),
        ("opening_range_sweep_reversal", OpeningRangeBreakout(variant="sweep_reversal")),
        ("trend_pullback", TrendPullback()),
        ("structure_continuation", StructureContinuation()),
        ("structure_reversal", StructureReversal()),
        ("significant_move_strong", SignificantMoveContinuation("STRONG_MOVE")),
        ("significant_move_moderate", SignificantMoveContinuation("MODERATE_MOVE")),
    ]


def regime_breakdown(trades):
    by_regime = {}
    for t in trades:
        regime = t.signal.market_condition or "UNKNOWN"
        by_regime.setdefault(regime, []).append(t)
    return {regime: trade_stats(trs) for regime, trs in by_regime.items()}


def main():
    t_start = time.time()
    RESULTS_DIR.mkdir(exist_ok=True)

    print(f"[1/12] Generating synthetic dataset (corrected engine): {len(SYMBOLS)} symbols x {N_DAYS} days...")
    dataset = generate_multi_symbol_dataset(SYMBOLS, n_days=N_DAYS, factor_loadings=FACTOR_LOADINGS)

    print("[2/12] Building causal engine data per symbol (expanded regime taxonomy)...")
    engine_data = {}
    for sym, d in dataset.items():
        t0 = time.time()
        engine_data[sym] = build_symbol_engine_data(sym, d.bars)
        print(f"  {sym}: {time.time() - t0:.1f}s")

    print("[3/12] Re-running PAIR x STRATEGY x REGIME matrix under corrected cost model...")
    base_config = BacktestConfig(sl_model="FIXED_ATR", sl_atr_mult=1.5, tp_model="FIXED_2R", exit_model="FIXED")
    matrix_rows = []
    trades_by_symbol_strategy = {sym: {} for sym in SYMBOLS}
    signals_rejected_by_symbol_strategy = {sym: {} for sym in SYMBOLS}
    all_pvalues = []
    funnel_rows = []

    for sym in SYMBOLS:
        ctx = engine_data[sym]
        for strat_name, strat in strategy_configs():
            run = run_backtest(ctx, strat, base_config)
            trades_by_symbol_strategy[sym][strat_name] = run.trades
            signals_rejected_by_symbol_strategy[sym][strat_name] = (run.signals, run.rejected)
            stats = trade_stats(run.trades)
            rs = np.array([t.r_multiple for t in run.trades])
            ci = bootstrap_mean_ci(rs, n_boot=500) if len(rs) >= 2 else {"excludes_zero": False}
            perm = permutation_negative_control(rs, n_perm=500) if len(rs) >= 2 else {"p_value": 1.0}
            row = {"symbol": sym, "strategy": strat_name, **stats,
                   "regime_breakdown": regime_breakdown(run.trades),
                   "n_rejected_candidates": len(run.rejected),
                   "bootstrap_ci": ci, "permutation": perm}
            matrix_rows.append(row)
            all_pvalues.append(perm.get("p_value", 1.0))
            funnel_rows.append({"symbol": sym, "strategy": strat_name,
                                 **build_funnel(run.signals, run.rejected, run.trades)})

    bh_survives = benjamini_hochberg(all_pvalues, alpha=0.05)
    for row, survives in zip(matrix_rows, bh_survives):
        row["bh_fdr_survives"] = bool(survives)
        sym, strat_name = row["symbol"], row["strategy"]
        trades = trades_by_symbol_strategy[sym][strat_name]
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

    dump("matrix_corrected", matrix_rows)
    dump("no_trade_funnel", funnel_rows)

    print("[4/12] New SL/TP models comparison (opening_range_continuation, all symbols)...")
    sl_rows, tp_rows = [], []
    for sym in SYMBOLS:
        ctx = engine_data[sym]
        strat = OpeningRangeBreakout(variant="continuation")
        for sl_model in SL_MODELS:
            cfg = BacktestConfig(sl_model=sl_model, tp_model="FIXED_2R", exit_model="FIXED")
            run = run_backtest(ctx, strat, cfg)
            sl_rows.append({"symbol": sym, "sl_model": sl_model, **trade_stats(run.trades)})
        for tp_model in TP_MODELS:
            cfg = BacktestConfig(sl_model="FIXED_ATR", tp_model=tp_model, exit_model="FIXED")
            run = run_backtest(ctx, strat, cfg)
            tp_rows.append({"symbol": sym, "tp_model": tp_model, **trade_stats(run.trades)})
    dump("sl_comparison_v2", sl_rows)
    dump("tp_comparison_v2", tp_rows)

    print("[5/12] Cost sensitivity sweep (opening_range_continuation, all symbols)...")
    cost_rows = []
    for sym in SYMBOLS:
        ctx = engine_data[sym]
        strat = OpeningRangeBreakout(variant="continuation")
        for name, mult in [("COST_NEUTRAL", 0.0), ("BASE_COST", 1.0), ("ADVERSE_COST", 2.0), ("STRESS_COST", 5.0)]:
            cfg = BacktestConfig(spread_multiplier=mult)
            run = run_backtest(ctx, strat, cfg)
            cost_rows.append({"symbol": sym, "cost_scenario": name, "multiplier": mult, **trade_stats(run.trades)})
    dump("cost_sensitivity", cost_rows)

    # Representative subset for the two most expensive per-symbol analyses
    # (each does bootstrap+permutation over ~11-20k rows per symbol);
    # narrowing documented explicitly in the audit report rather than
    # silently running all 8.
    REPRESENTATIVE_SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD"]

    print(f"[6/12] Nested bias experiment ({REPRESENTATIVE_SYMBOLS})...")
    bias_rows = []
    for sym in REPRESENTATIVE_SYMBOLS:
        result = run_nested_bias_experiment(engine_data[sym])
        bias_rows.append({"symbol": sym, **result})
    dump("nested_bias_experiment", bias_rows)

    print(f"[7/12] Generalized ablation matrix ({REPRESENTATIVE_SYMBOLS})...")
    ablation_matrix_rows = []
    for sym in REPRESENTATIVE_SYMBOLS:
        result = run_ablation_matrix(engine_data[sym])
        ablation_matrix_rows.append({"symbol": sym, **result})
    dump("ablation_matrix", ablation_matrix_rows)
    dump("ablation_v1_extended", [
        {"symbol": sym, **row}
        for sym in ("EURUSD", "GBPUSD")
        for row in run_ablation(engine_data[sym], base_config)
    ])

    print("[8/12] Rolling hedge correlation report (correlated + uncorrelated pairs)...")
    hedge_pairs = [("EURUSD", "GBPUSD"), ("EURUSD", "USDJPY"), ("EURUSD", "USDCHF"), ("AUDUSD", "NZDUSD")]
    hedge_rows = [build_hedge_correlation_report(engine_data[a], engine_data[b]) for a, b in hedge_pairs]
    dump("rolling_hedge_correlation", hedge_rows)

    print("[9/12] Negative controls...")
    nc_results = {
        "structure_continuation": permuted_structure_control(engine_data["EURUSD"], StructureContinuation, base_config),
        "structure_reversal": permuted_structure_control(engine_data["EURUSD"], StructureReversal, base_config),
        "significant_move_strong": permuted_strength_control(engine_data["EURUSD"], "STRONG_MOVE", base_config),
    }
    ret_a = engine_data["EURUSD"].frames["M5"]["close"].pct_change()
    ret_b = engine_data["GBPUSD"].frames["M5"]["close"].pct_change()
    nc_results["hedge_pairing"] = permuted_hedge_pairing_control(ret_a, ret_b)
    dump("negative_controls", nc_results)

    print("[10/12] Trend-only mode comparison (trend_pullback, all symbols)...")
    trend_only_rows = []
    for sym in SYMBOLS:
        result = run_trend_only_comparison(engine_data[sym], TrendPullback(), base_config)
        trend_only_rows.append({"symbol": sym, **result})
    dump("trend_only_comparison", trend_only_rows)

    print("[11/12] Strategy selector comparison (all symbols)...")
    selector_rows = []
    for sym in SYMBOLS:
        comparison = compare_selectors(trades_by_symbol_strategy[sym], {sym: engine_data[sym]})
        selector_rows.append({"symbol": sym, **comparison})
    dump("strategy_selector_comparison", selector_rows)

    print("[12/12] Robustness (parameter perturbation), out-of-sample lock, mutation tests...")
    robustness_rows = run_parameter_perturbation(engine_data["XAUUSD"])
    robustness_summary = summarize_plateau(robustness_rows)
    dump("robustness_perturbation", {"rows": robustness_rows, "summary": robustness_summary})

    oos_result = run_locked_out_of_sample_test()
    dump("out_of_sample_locked", oos_result)

    mutation_results = run_all_mutation_tests()
    dump("mutation_tests", [{"name": n, "detected": d, "detail": det} for n, d, det in mutation_results])

    print(f"\nAll Phase 8 experiments complete in {time.time() - t_start:.1f}s. Results in {RESULTS_DIR}")


if __name__ == "__main__":
    main()
