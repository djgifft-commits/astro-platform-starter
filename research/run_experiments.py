"""
Orchestrator: runs the full research program described in the audit report
and dumps JSON results to research/results/ for both the web terminal
(Phases 23-27) and the written report (Phase 29).

This script performs NO live trading, connects to no broker, and reads no
real market data -- see research/config.py DATA DISCLOSURE. Every number
this script produces is an engine-validation result on labeled synthetic
data.

Run: research/.venv/bin/python -m research.run_experiments
"""
from __future__ import annotations

import dataclasses
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from research.backtest.ablation import run_ablation
from research.backtest.engine import BacktestConfig, run_backtest
from research.backtest.metrics import trade_stats
from research.backtest.validation import (
    benjamini_hochberg,
    bootstrap_mean_ci,
    permutation_negative_control,
    walk_forward_folds,
    label_verdict,
)
from research.core.feature_bar import build_symbol_engine_data
from research.core.fibonacci import FIB_LEVELS, CONTROL_LEVELS
from research.data.quality import audit_bars
from research.data.synthetic import generate_multi_symbol_dataset
from research.risk import position_sizing
from research.risk.exit_models import EXIT_MODELS
from research.risk.portfolio import run_hedge_cases
from research.risk.sl_models import SL_MODELS
from research.risk.tp_models import TP_MODELS
from research.strategies.fib_pullback import FibonacciPullback
from research.strategies.opening_range import OpeningRangeBreakout
from research.strategies.significant_move import SignificantMoveContinuation
from research.strategies.structure_continuation import StructureContinuation
from research.strategies.structure_reversal import StructureReversal
from research.strategies.trend_pullback import TrendPullback

RESULTS_DIR = Path(__file__).parent / "results"
SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD", "XAUUSD"]
N_DAYS = 300
FACTOR_LOADINGS = {  # designed correlation structure for Phase 13/19 hedge-mechanics testing only
    "EURUSD": 0.75, "GBPUSD": 0.65, "USDJPY": -0.30, "AUDUSD": 0.55,
    "USDCAD": -0.45, "USDCHF": -0.60, "NZDUSD": 0.50, "XAUUSD": 0.20,
}


def json_default(o):
    if isinstance(o, (pd.Timestamp,)):
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
    configs = [
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
    for level in (0.382, 0.5, 0.618):  # representative Fibonacci subset for the main matrix;
        configs.append((f"fib_pullback_{level}", FibonacciPullback(level)))
    return configs


def regime_breakdown(trades):
    by_regime = {}
    for t in trades:
        regime = t.signal.market_condition or "UNKNOWN"
        by_regime.setdefault(regime, []).append(t)
    return {regime: trade_stats(trs) for regime, trs in by_regime.items()}


def main():
    t_start = time.time()
    RESULTS_DIR.mkdir(exist_ok=True)

    print(f"[1/9] Generating synthetic dataset: {len(SYMBOLS)} symbols x {N_DAYS} days...")
    dataset = generate_multi_symbol_dataset(SYMBOLS, n_days=N_DAYS, factor_loadings=FACTOR_LOADINGS)

    print("[2/9] Data quality audit...")
    quality_reports = []
    for sym, d in dataset.items():
        report = audit_bars(d.bars, sym, "M1", 1)
        quality_reports.append(report.to_dict())
    dump("data_quality", quality_reports)

    print("[3/9] Building causal engine data per symbol...")
    engine_data = {}
    for sym, d in dataset.items():
        t0 = time.time()
        engine_data[sym] = build_symbol_engine_data(sym, d.bars)
        print(f"  {sym}: {time.time() - t0:.1f}s, {len(engine_data[sym].frames[engine_data[sym].execution_tf])} M5 bars")

    # Regime-classifier engine-validation diagnostic (never fed back causally)
    print("[3b/9] Regime classifier vs. SYNTHETIC ground truth (engine validation only)...")
    regime_validation = {}
    for sym, d in dataset.items():
        h1 = engine_data[sym].frames["H1"]
        gt_h1 = d.ground_truth_regime.resample("1h").first().reindex(h1.index).ffill()
        classified = engine_data[sym].feature_bars["regime_regime"].reindex(
            engine_data[sym].feature_bars.index
        )
        classified_h1 = classified.resample("1h").first().reindex(h1.index).ffill()
        valid = gt_h1.notna() & classified_h1.notna()
        agree_directional = 0
        total = 0
        for gt, cl in zip(gt_h1[valid], classified_h1[valid]):
            gt_dir = "UP" if "UP" in str(gt) else ("DOWN" if "DOWN" in str(gt) else "FLAT")
            cl_dir = "UP" if "UP" in str(cl) else ("DOWN" if "DOWN" in str(cl) else "FLAT")
            total += 1
            if gt_dir == cl_dir:
                agree_directional += 1
        regime_validation[sym] = {
            "directional_agreement_rate": agree_directional / total if total else None,
            "n": total,
            "note": "Diagnostic only: agreement between the CAUSAL classifier and the hidden SYNTHETIC "
                    "generating regime's broad direction (UP/DOWN/FLAT). Not used by any strategy.",
        }
    dump("regime_validation", regime_validation)

    print("[4/9] PAIR x STRATEGY x REGIME matrix...")
    base_config = BacktestConfig(sl_model="FIXED_ATR", sl_atr_mult=1.5, tp_model="FIXED_2R", exit_model="FIXED")
    matrix_rows = []
    trades_by_symbol_strategy = {sym: {} for sym in SYMBOLS}
    all_pvalues_index = []
    all_pvalues = []
    sample_trades = []
    sample_rejected = []

    for sym in SYMBOLS:
        ctx = engine_data[sym]
        for strat_name, strat in strategy_configs():
            run = run_backtest(ctx, strat, base_config)
            trades_by_symbol_strategy[sym][strat_name] = run.trades
            stats = trade_stats(run.trades)
            rs = np.array([t.r_multiple for t in run.trades])
            ci = bootstrap_mean_ci(rs, n_boot=600) if len(rs) >= 2 else {"excludes_zero": False}
            perm = permutation_negative_control(rs, n_perm=600) if len(rs) >= 2 else {"p_value": 1.0}
            row = {
                "symbol": sym, "strategy": strat_name, **stats,
                "regime_breakdown": regime_breakdown(run.trades),
                "n_rejected_candidates": len(run.rejected),
                "bootstrap_ci": ci, "permutation": perm,
            }
            matrix_rows.append(row)
            all_pvalues_index.append((sym, strat_name))
            all_pvalues.append(perm.get("p_value", 1.0))

            if len(sample_trades) < 40 and run.trades:
                for t in run.trades[:5]:
                    sample_trades.append({
                        "symbol": sym, "strategy": strat_name, "variant": t.signal.variant,
                        "direction": t.signal.direction, "entry_ts": t.entry_ts, "entry_price": t.entry_price,
                        "sl_model": t.sl_model, "tp_model": t.tp_model, "exit_model": t.exit_model,
                        "initial_sl": t.initial_sl, "exit_ts": t.exit_ts, "exit_price": t.exit_price,
                        "exit_reason": t.exit_reason, "r_multiple": t.r_multiple, "mfe_r": t.mfe_r, "mae_r": t.mae_r,
                        "duration_bars": t.duration_bars, "setup_reason": t.signal.setup_reason,
                        "rules_passed": t.signal.rules_passed, "rules_failed": t.signal.rules_failed,
                        "market_condition": t.signal.market_condition, "directional_bias": t.signal.directional_bias,
                        "candle_pattern": t.signal.candle_pattern,
                    })
            if len(sample_rejected) < 40 and run.rejected:
                for rc in run.rejected[:5]:
                    sample_rejected.append({
                        "symbol": sym, "strategy": strat_name, "variant": rc.variant, "ts": rc.ts,
                        "entry_state_reached": rc.entry_state_reached, "first_failing_rule": rc.first_failing_rule,
                        "rules_checked": [{"name": c.name, "passed": c.passed, "detail": c.detail} for c in rc.rules_checked],
                    })

    bh_survives = benjamini_hochberg(all_pvalues, alpha=0.05)
    for row, survives in zip(matrix_rows, bh_survives):
        row["bh_fdr_survives"] = bool(survives)

    print("[4b/9] Walk-forward + verdict labeling per (symbol, strategy) cell...")
    for row in matrix_rows:
        sym, strat_name = row["symbol"], row["strategy"]
        trades = trades_by_symbol_strategy[sym][strat_name]
        folds = walk_forward_folds(trades, n_folds=5)
        fold_stats = [trade_stats(test) for _, test in folds]
        verdict = label_verdict(row["n"] if row["n"] == row["n"] else 0, row["bootstrap_ci"], row["permutation"],
                                 fold_stats, row["bh_fdr_survives"])
        row["walk_forward_folds"] = fold_stats
        row["verdict"] = verdict.verdict
        row["verdict_reasons"] = verdict.reasons

    dump("matrix", matrix_rows)
    dump("sample_trades", sample_trades)
    dump("sample_rejected_candidates", sample_rejected)

    print("[5/9] SL / TP / Exit model comparisons (representative strategy: opening_range_continuation)...")
    sl_rows, tp_rows, exit_rows = [], [], []
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
        for exit_model in EXIT_MODELS:
            cfg = BacktestConfig(sl_model="FIXED_ATR", tp_model="FIXED_2R", exit_model=exit_model)
            run = run_backtest(ctx, strat, cfg)
            exit_rows.append({"symbol": sym, "exit_model": exit_model, **trade_stats(run.trades)})
    dump("sl_comparison", sl_rows)
    dump("tp_comparison", tp_rows)
    dump("exit_comparison", exit_rows)

    print("  Which exit wins for which strategy? (extending exit comparison to all main strategies, EURUSD)")
    exit_by_strategy = []
    ctx = engine_data["EURUSD"]
    for strat_name, strat in strategy_configs():
        for exit_model in EXIT_MODELS:
            cfg = BacktestConfig(sl_model="FIXED_ATR", tp_model="FIXED_2R", exit_model=exit_model)
            run = run_backtest(ctx, strat, cfg)
            exit_by_strategy.append({"strategy": strat_name, "exit_model": exit_model, **trade_stats(run.trades)})
    dump("exit_by_strategy", exit_by_strategy)

    print("[6/9] Fibonacci level comparison (all levels, EURUSD + GBPUSD)...")
    fib_rows = []
    for sym in ("EURUSD", "GBPUSD"):
        ctx = engine_data[sym]
        for level in FIB_LEVELS + CONTROL_LEVELS:
            strat = FibonacciPullback(level)
            run = run_backtest(ctx, strat, base_config)
            fib_rows.append({
                "symbol": sym, "level": level, "is_fibonacci_level": level in FIB_LEVELS,
                **trade_stats(run.trades),
            })
    dump("fibonacci_level_comparison", fib_rows)

    print("[7/9] Risk-level sweep + lot-size demonstration (opening_range_continuation, EURUSD)...")
    trades_repr = trades_by_symbol_strategy["EURUSD"]["opening_range_continuation"]
    ordered = sorted([t for t in trades_repr if t.exit_ts is not None], key=lambda t: t.entry_ts)
    risk_levels = [0.0025, 0.005, 0.0075, 0.01, 0.0125, 0.015, 0.02]
    risk_rows = []
    for risk_pct in risk_levels:
        equity = 1.0
        peak = 1.0
        max_dd = 0.0
        for t in ordered:
            equity *= (1 + risk_pct * t.r_multiple)
            peak = max(peak, equity)
            max_dd = min(max_dd, (equity - peak) / peak)
        risk_rows.append({
            "risk_percent": risk_pct, "n_trades": len(ordered),
            "final_equity_multiple": equity, "max_drawdown_pct": max_dd,
            "total_return_pct": equity - 1.0,
        })
    dump("risk_level_sweep", risk_rows)

    lot_rows = []
    equity_acct = 10_000.0
    for lots in (0.01, 0.02, 0.03, 0.05, 0.10, 0.20):
        total_pnl_usd = 0.0
        for t in ordered:
            pip = 0.0001
            pnl_pips = (t.r_multiple * t.initial_risk) / pip
            pnl_usd = pnl_pips * pip * lots * 100_000
            total_pnl_usd += pnl_usd
        lot_rows.append({"lots": lots, "n_trades": len(ordered), "total_pnl_usd": total_pnl_usd,
                          "return_on_10k_pct": total_pnl_usd / equity_acct * 100})
    dump("lot_size_experiment", lot_rows)

    print("[8/9] Hedge / portfolio cases (A-G)...")
    hedge_cases = run_hedge_cases(trades_by_symbol_strategy)
    hedge_summary = {
        name: {
            "description": case.description, "n_trades": len(case.trades),
            "gross_exposure_lots": case.gross_exposure_lots, "net_exposure_lots": case.net_exposure_lots,
            "realized_correlation": case.realized_correlation, "max_drawdown": case.max_drawdown,
            "sharpe": case.sharpe, "sortino": case.sortino, "profit_factor": case.profit_factor,
            "total_return_r": case.total_return_r,
        }
        for name, case in hedge_cases.items()
    }
    dump("hedge_cases", hedge_summary)

    print("[9/9] Feature ablation (opening_range_continuation, EURUSD + GBPUSD)...")
    ablation_rows = []
    for sym in ("EURUSD", "GBPUSD"):
        rows = run_ablation(engine_data[sym], base_config)
        for r in rows:
            r["symbol"] = sym
        ablation_rows.extend(rows)
    dump("ablation", ablation_rows)

    print("Sample candle data + overlays for the web replay terminal (EURUSD, 30-day window)...")
    exec_df = engine_data["EURUSD"].frames["M5"]
    window = exec_df.iloc[: 30 * 288]
    candle_rows = [
        {"ts": ts, "open": r["open"], "high": r["high"], "low": r["low"], "close": r["close"]}
        for ts, r in window.iterrows()
    ]
    overlays = {
        "opening_ranges": [
            {"date": orr.date, "session_open_utc": orr.session_open_utc, "or_close_utc": orr.or_close_utc,
             "or_high": orr.or_high, "or_low": orr.or_low}
            for orr in engine_data["EURUSD"].opening_ranges if orr.session_open_utc <= window.index[-1]
        ],
        "structure_events": [
            {"ts": e.timestamp, "kind": e.kind, "direction": e.direction, "price": e.broken_swing_price}
            for e in engine_data["EURUSD"].structure_events if e.timestamp <= window.index[-1]
        ],
        "liquidity_sweeps": [
            {"ts": s.sweep_ts, "kind": s.pool.kind, "price": s.pool.price}
            for s in engine_data["EURUSD"].liquidity_sweeps if s.sweep_ts <= window.index[-1]
        ],
        "trades": sample_trades,
    }
    dump("candles_eurusd_sample", candle_rows)
    dump("overlays_eurusd_sample", overlays)

    print(f"\nAll experiments complete in {time.time() - t_start:.1f}s. Results in {RESULTS_DIR}")


if __name__ == "__main__":
    main()
