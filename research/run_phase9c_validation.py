"""
Phase 9C — real-data 1UP/2DOWN strategy validation on ingested XAUUSD M1
history (research/data_manifest/phase9c_manifest.json: READY_FOR_PHASE_9C,
GMT+3 broker offset user-confirmed and independently corroborated against
real market close/reopen structure -- audit/PHASE_9C_DATA_INGESTION.md).

SAMPLE SIZE, STATED UP FRONT: 74 NY sessions (~101 days, one symbol).
Real trade counts per entry family: breakout=29, retest=22, reversal=11.
This is thin. Every statistical test below still runs and is reported
in full, but per this phase's explicit instruction ("If real data is
available but sample size is inadequate, report TRADING_EDGE_UNPROVEN
rather than forcing a conclusion"), do not expect -- and do not
manufacture -- a confident conclusion from numbers this size. The
final report (audit/PHASE_9C_STRATEGY_VALIDATION.md) states explicitly
which questions this sample size cannot actually answer.

REUSE, NOT REBUILD: this orchestrator calls the exact same engine
(research/backtest/engine.py::run_backtest), the exact same strategy
(research/strategies/opening_range_v2.py::OpeningRangeStateMachine,
UNCHANGED from Phase 9B), and the exact same validation/funnel/regime/
Fibonacci/candle/portfolio modules Phase 9B built and tested on synthetic
data. Nothing here is a second execution engine. The only genuinely new
pieces are: real-data loading + spread unit conversion (this file), the
OR-specific A-G ablation (research/backtest/or_ablation_9c.py), and the
chronological LOCK/OOS split (this file).

NOT ASSESSABLE WITH THIS DATA -- reported as such, never faked:
  - Symbol stability: only 1 symbol ingested.
  - Year stability: only ~101 days, no year boundary.
  - Hedge effectiveness: requires >=2 symbols for a correlation pair.
  - Commission / slippage: this project's execution model has no
    commission or slippage capability (research/backtest/engine.py only
    ever modeled spread) -- reported as unavailable, not invented.

Run: research/.venv/bin/python -m research.run_phase9c_validation
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
from research.backtest.or_ablation_9c import run_or_ablation
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
from research.config import PIP_SIZE
from research.core.feature_bar import build_symbol_engine_data
from research.data.real_data import load_real_ohlcv
from research.risk.position_sizing import RiskLimits
from research.strategies.opening_range_v2 import OpeningRangeStateMachine

RESULTS_DIR = Path(__file__).parent / "results_9c_real"
SYMBOL = "XAUUSD"
DATA_PATH = Path(__file__).parent.parent / "data" / "historical" / "XAUUSD_M1.csv"
BROKER_TZ_OFFSET = "+03:00"  # GMT+3, user-confirmed (audit/PHASE_9C_DATA_INGESTION.md Section 11)
ENTRY_FAMILIES = ("breakout", "retest", "reversal")

# The strategy/SL/TP config Phase 8/9B already established as the default
# BEFORE this real data ever existed -- used here UNCHANGED. This project
# never re-tunes a config to real data; the SL/TP/cost/risk sweeps below
# are explicitly descriptive only (Section labeled "not used to select a
# config" in the report), never fed back into this LOCKED_CONFIG.
LOCKED_CONFIG = BacktestConfig(sl_model="FIXED_ATR", sl_atr_mult=1.5, tp_model="FIXED_2R", exit_model="FIXED")


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


def load_real_xauusd():
    """Loads the ingested file and converts its native MT5 <SPREAD> column
    from broker POINTS to PRICE UNITS via this project's existing
    PIP_SIZE["XAUUSD"]=0.01 convention (research/config.py) -- inferred
    from, and consistent with, the file's own uniform 2-decimal price
    quoting (every row, never 3 decimals). research/backtest/engine.py's
    cost model expects `spread` already in price units; without this
    conversion a 23-45 point spread would be applied as $23-45 of cost per
    round trip, which is off by ~100x and would silently wreck every
    result. This conversion is applied ONCE, here, explicitly -- never
    inside the generic loader, which must not carry symbol-specific
    domain assumptions."""
    ds = load_real_ohlcv(str(DATA_PATH), symbol=SYMBOL, assume_naive_tz=BROKER_TZ_OFFSET)
    bars = ds.bars.copy()
    if "spread" in bars.columns:
        bars["spread"] = bars["spread"] * PIP_SIZE[SYMBOL]
    return bars


def chronological_lock_split(trades: list, train_fraction: float = 0.70, embargo: pd.Timedelta = pd.Timedelta(days=1)):
    """A single chronological TRAIN+VALIDATION / TEST split with an
    embargo, in place of a 3-way TRAIN/VALIDATION/TEST split: with the
    trade counts this dataset actually produces (11-29 per family), a
    3-way split leaves single-digit-to-low-double-digit folds, which is
    already at the edge of usefulness for one split -- three-way would
    not add a genuine held-out validation stage, only extra noise. This
    deviation from "prefer TRAIN/VALIDATION/TEST" is deliberate and
    reported, not silent, per that instruction's own "where necessary"
    qualifier on purging/embargo mechanics.

    LOCK discipline: the config passed to whatever produced `trades` is
    LOCKED_CONFIG, frozen before this split is even computed and never
    adjusted afterward based on either half's result."""
    ordered = sorted(trades, key=lambda t: t.entry_ts)
    if not ordered:
        return [], []
    cutoff_idx = int(len(ordered) * train_fraction)
    cutoff_ts = ordered[cutoff_idx].entry_ts if cutoff_idx < len(ordered) else ordered[-1].entry_ts
    train = [t for t in ordered if t.entry_ts < cutoff_ts]
    test = [t for t in ordered if t.entry_ts >= cutoff_ts + embargo]
    return train, test


def stats_block(trades: list, n_boot: int = 1000, n_perm: int = 1000) -> dict:
    stats = trade_stats(trades)
    rs = np.array([t.r_multiple for t in trades])
    ci = bootstrap_mean_ci(rs, n_boot=n_boot) if len(rs) >= 2 else {"excludes_zero": False}
    perm = permutation_negative_control(rs, n_perm=n_perm) if len(rs) >= 2 else {"p_value": 1.0}
    return {**stats, "bootstrap_ci": ci, "permutation": perm}


def main():
    t_start = time.time()
    RESULTS_DIR.mkdir(exist_ok=True)

    print("[1/11] Loading real XAUUSD M1 data (GMT+3-corrected, spread converted to price units)...")
    bars = load_real_xauusd()
    print(f"  {len(bars)} M1 bars, {bars.index[0]} .. {bars.index[-1]}")
    print(f"  spread (price units) sample: {bars['spread'].iloc[:5].tolist()}")

    print("[2/11] Building causal engine data...")
    ctx = build_symbol_engine_data(SYMBOL, bars)
    print(f"  {len(ctx.opening_ranges)} NY opening ranges")

    print("[3/11] OR v2 matrix: 3 entry families, full statistical validation...")
    matrix_rows = []
    trades_by_family = {}
    signals_rejected_by_family = {}
    day_summaries_by_family = {}  # every real NY session -> Decision Inspector
    all_pvalues = []
    for family in ENTRY_FAMILIES:
        strat = OpeningRangeStateMachine(entry_family=family)
        run = run_backtest(ctx, strat, LOCKED_CONFIG)
        trades_by_family[family] = run.trades
        signals_rejected_by_family[family] = (run.signals, run.rejected)
        day_summaries_by_family[family] = strat.day_summaries
        row = {"entry_family": family, **stats_block(run.trades), "n_rejected_candidates": len(run.rejected)}
        matrix_rows.append(row)
        all_pvalues.append(row["permutation"].get("p_value", 1.0))

    bh_survives = benjamini_hochberg(all_pvalues, alpha=0.05)
    for row, survives in zip(matrix_rows, bh_survives):
        row["bh_fdr_survives"] = bool(survives)
        trades = trades_by_family[row["entry_family"]]
        n_folds = 3 if row["n"] >= 15 else 0  # <15 trades: fold dispersion would be meaningless noise
        fold_stats = [trade_stats(test) for _, test in walk_forward_folds(trades, n_folds=n_folds)] if n_folds else []
        verdict = label_verdict(row["n"], row["bootstrap_ci"], row["permutation"], fold_stats, row["bh_fdr_survives"])
        row["walk_forward_folds"] = fold_stats
        row["verdict"] = verdict.verdict
        row["verdict_reasons"] = verdict.reasons
        purged = purged_embargoed_folds(trades, n_folds=n_folds, embargo=pd.Timedelta(hours=24)) if n_folds else []
        row["purged_embargoed_summary"] = [
            {"fold": f.fold_index, "n_test": len(f.test), "n_purged": f.n_purged, "n_embargoed": f.n_embargoed}
            for f in purged
        ]
    dump("or_v2_matrix_real", matrix_rows)

    print("[3b/11] Decision Inspector data -- every real NY session, all 3 families "
          "(WHY ENTERED / WHY REJECTED / what each timeframe knew, from MARKET_CONTEXT)...")
    decision_inspector_real = {
        family: [dataclasses.asdict(d) for d in day_summaries_by_family[family]]
        for family in ENTRY_FAMILIES
    }
    dump("decision_inspector_real", decision_inspector_real)

    print("[4/11] 13-stage no-trade funnel...")
    funnel_rows = []
    for family in ENTRY_FAMILIES:
        signals, rejected = signals_rejected_by_family[family]
        funnel_rows.append({"entry_family": family, **build_detailed_funnel(signals, rejected)})
    dump("no_trade_funnel_v2_real", funnel_rows)

    print("[5/11] Regime gating comparison (breakout family)...")
    regime_result = run_regime_gate_comparison(ctx, trades_by_family["breakout"])
    dump("regime_gating_real", regime_result)

    print("[6/11] Fibonacci depth information + candle pattern ablation...")
    fib_result = run_depth_information_experiment(ctx)
    candle_result = run_candle_pattern_ablation(ctx)
    dump("fibonacci_depth_real", fib_result)
    dump("candle_pattern_ablation_real", candle_result)

    print("[7/11] OR-specific A-G ablation (breakout family as G)...")
    or_ablation_result = run_or_ablation(ctx, trades_by_family["breakout"])
    dump("or_ablation_9c_real", or_ablation_result)

    print("[8/11] SL/TP descriptive comparison (breakout family) -- NOT used to select a config...")
    sl_tp_rows = []
    for sl_model in ("FIXED_ATR", "BREAKOUT_CANDLE"):
        cfg = BacktestConfig(sl_model=sl_model, tp_model="FIXED_2R", exit_model="FIXED")
        run = run_backtest(ctx, OpeningRangeStateMachine(entry_family="breakout"), cfg)
        sl_tp_rows.append({"model_type": "SL", "model": sl_model, **trade_stats(run.trades)})
    for tp_model in ("FIXED_0.5R", "FIXED_1R", "FIXED_2R", "FIXED_3R", "FIXED_4R", "OR_OPPOSITE_BOUNDARY_TARGET", "LIQUIDITY_TARGET"):
        cfg = BacktestConfig(sl_model="FIXED_ATR", tp_model=tp_model, exit_model="FIXED")
        run = run_backtest(ctx, OpeningRangeStateMachine(entry_family="breakout"), cfg)
        sl_tp_rows.append({"model_type": "TP", "model": tp_model, **trade_stats(run.trades)})
    dump("sl_tp_descriptive_real", sl_tp_rows)

    print("[9/11] Real-spread cost sensitivity (BASE/ADVERSE/STRESS)...")
    cost_rows = []
    for name, mult in [("COST_NEUTRAL", 0.0), ("BASE_COST", 1.0), ("ADVERSE_COST", 2.0), ("STRESS_COST", 5.0)]:
        cfg = BacktestConfig(spread_multiplier=mult)
        run = run_backtest(ctx, OpeningRangeStateMachine(entry_family="breakout"), cfg)
        cost_rows.append({"cost_scenario": name, "multiplier": mult, **trade_stats(run.trades)})
    dump("cost_sensitivity_real", cost_rows)
    print("  NOTE: commission and slippage are NOT modeled -- this project's execution engine has no such "
          "capability (spread only); reported as unavailable, not simulated.")

    print("[10/11] Risk-level sweep (0.25/0.50/0.75/1.00%) + cross-family position-overlap simulation...")
    risk_rows = []
    limits = RiskLimits(max_open_positions=3, max_daily_loss_pct=0.05, max_consecutive_losses=6)
    for risk_pct in (0.0025, 0.0050, 0.0075, 0.0100):
        outcomes = simulate_portfolio_gating({SYMBOL: trades_by_family["breakout"]}, limits=limits, risk_pct=risk_pct)
        risk_rows.append({"risk_pct": risk_pct, **summarize_gating(outcomes)})
    dump("risk_level_sweep_real", risk_rows)

    # Cross-family overlap: if this bot ran breakout+retest+reversal on
    # XAUUSD SIMULTANEOUSLY, how often would they compete for the same
    # risk/position budget? This is a same-symbol overlap question, not a
    # cross-symbol correlation one -- correlated_symbol_pairs is
    # deliberately not used here.
    overlap_outcomes = simulate_portfolio_gating(
        {f"XAUUSD_{fam}": trades_by_family[fam] for fam in ENTRY_FAMILIES}, limits=limits,
    )
    dump("cross_family_overlap_real", {"summary": summarize_gating(overlap_outcomes),
                                        "note": "same-symbol, cross-entry-family overlap -- not a cross-symbol correlation analysis (only one symbol is available)"})

    print("[11/11] Locked chronological OOS split (breakout, 70/30, LOCKED_CONFIG never re-tuned) + mutation tests...")
    train, test = chronological_lock_split(trades_by_family["breakout"])
    oos_result = {
        "locked_config": "opening_range_v2 breakout (default params) / FIXED_ATR@1.5 / FIXED_2R / FIXED -- frozen since Phase 8/9B, never adjusted based on this real data",
        "split_method": "single chronological 70/30 split with a 1-day embargo (a 3-way TRAIN/VALIDATION/TEST split was not used -- see chronological_lock_split's docstring for why, given n=29 total breakout trades)",
        "exploration_segment": stats_block(train),
        "locked_test_segment": stats_block(test),
    }
    dump("locked_oos_real", oos_result)

    mutation_results = run_all_mutation_tests()
    dump("mutation_tests_real", [{"name": n, "detected": d, "detail": det} for n, d, det in mutation_results])

    print("\nNOT ASSESSABLE WITH THIS DATA (reported, not faked):")
    print("  - Symbol stability: only 1 symbol (XAUUSD) ingested.")
    print("  - Year stability: only ~101 days span, no year boundary.")
    print("  - Hedge effectiveness: requires >=2 symbols for a correlation pair.")
    print("  - Commission/slippage: not modeled by this project's execution engine.")

    print(f"\nAll Phase 9C real-data experiments complete in {time.time() - t_start:.1f}s. Results in {RESULTS_DIR}")


if __name__ == "__main__":
    main()
