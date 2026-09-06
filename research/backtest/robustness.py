"""
Phase 8AG — Robustness (parameter perturbation).

A strategy is not robust because one backtest is profitable. This module
perturbs the ONE cell that reached `EDGE_ESTABLISHED` in Phase 7
(trend_pullback on synthetic XAUUSD -- see audit/
PHASE_7_MULTI_STRATEGY_HEDGE_BACKTEST.md Section 8) across nearby,
reasonable parameter values -- never brute-force-optimized, just a small
grid around the values already used -- to check whether the positive
result is a stable plateau or an isolated spike (Bailey & Lopez de Prado's
"backtest overfitting" concern, RESEARCH_CARDS.md card T, applies just as
much to a single lucky parameterization as to a single lucky strategy).
"""
from __future__ import annotations

from typing import Dict, List

from research.backtest.engine import BacktestConfig, run_backtest
from research.backtest.metrics import trade_stats
from research.strategies.trend_pullback import TrendPullback


def run_parameter_perturbation(ctx) -> List[Dict]:
    rows = []
    depth_grid = [(0.25, 0.60), (0.30, 0.65), (0.35, 0.70)]  # (min_depth, max_depth)
    persistence_grid = [0.50, 0.55, 0.60]
    sl_mult_grid = [1.25, 1.5, 1.75]

    for min_depth, max_depth in depth_grid:
        for min_persistence in persistence_grid:
            for sl_mult in sl_mult_grid:
                strat = TrendPullback(min_depth=min_depth, max_depth=max_depth, min_persistence=min_persistence)
                cfg = BacktestConfig(sl_atr_mult=sl_mult)
                run = run_backtest(ctx, strat, cfg)
                stats = trade_stats(run.trades)
                rows.append({
                    "min_depth": min_depth, "max_depth": max_depth,
                    "min_persistence": min_persistence, "sl_atr_mult": sl_mult,
                    **stats,
                })
    return rows


def summarize_plateau(rows: List[Dict]) -> Dict:
    valid = [r for r in rows if r["n"] >= 30]
    if not valid:
        return {"verdict": "INSUFFICIENT_SAMPLE", "n_configs_tested": len(rows), "n_configs_with_enough_trades": 0}
    positive = [r for r in valid if r["expectancy_r"] > 0]
    fraction_positive = len(positive) / len(valid)
    return {
        "n_configs_tested": len(rows),
        "n_configs_with_enough_trades": len(valid),
        "fraction_positive_expectancy": fraction_positive,
        "min_expectancy_r": min(r["expectancy_r"] for r in valid),
        "max_expectancy_r": max(r["expectancy_r"] for r in valid),
        "mean_expectancy_r": sum(r["expectancy_r"] for r in valid) / len(valid),
        "verdict": "STABLE_PLATEAU" if fraction_positive >= 0.7 else (
            "ISOLATED_SPIKE" if fraction_positive <= 0.3 else "MIXED_NOT_ROBUST"
        ),
    }


if __name__ == "__main__":
    from research.core.feature_bar import build_symbol_engine_data
    from research.data.synthetic import generate_multi_symbol_dataset

    ds = generate_multi_symbol_dataset(["XAUUSD"], n_days=300)
    ctx = build_symbol_engine_data("XAUUSD", ds["XAUUSD"].bars)

    rows = run_parameter_perturbation(ctx)
    for r in rows:
        print({k: v for k, v in r.items() if k in ("min_depth", "max_depth", "min_persistence", "sl_atr_mult", "n", "expectancy_r")})

    summary = summarize_plateau(rows)
    print("SUMMARY:", summary)
    print("OK")
