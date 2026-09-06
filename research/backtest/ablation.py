"""
Phase 20 — Feature ablation.

Scope narrowing (documented in the audit report): a fully generic ablation
harness over every named feature (regime, bias, structure, liquidity,
Fibonacci, displacement, candlestick, opening range, retest, DXY,
StopTracker, exit model, volatility, session) would require every
strategy to expose each of those as an independently toggleable filter.
Only two are wired as togglable flags today (research/strategies/
opening_range.py's `require_bias_alignment` / `require_structure_confirm`,
i.e. the A6/A7 variants) — this module ablates those two, incrementally,
on top of the baseline continuation breakout. Fibonacci-level value and
candlestick-pattern value are separately, explicitly measured by running
research/strategies/fib_pullback.py across FIB_LEVELS+CONTROL_LEVELS and
comparing pattern-conditioned vs pattern-only performance (see
run_experiments.py) rather than through this incremental-ΔX harness —
that is a more direct test for those two features than forcing them into
this harness would have been.
"""
from __future__ import annotations

from typing import Dict, List

from research.backtest.engine import BacktestConfig, run_backtest
from research.backtest.metrics import trade_stats
from research.strategies.opening_range import OpeningRangeBreakout


def run_ablation(ctx, base_config: BacktestConfig) -> List[Dict]:
    stages = [
        ("baseline_no_filters", dict(require_bias_alignment=False, require_structure_confirm=False)),
        ("plus_htf_bias_alignment", dict(require_bias_alignment=True, require_structure_confirm=False)),
        ("plus_structure_confirmation", dict(require_bias_alignment=True, require_structure_confirm=True)),
    ]

    rows = []
    prev_stats = None
    for stage_name, kwargs in stages:
        strat = OpeningRangeBreakout(variant="continuation", **kwargs)
        run = run_backtest(ctx, strat, base_config)
        stats = trade_stats(run.trades)
        row = {"stage": stage_name, **stats}
        if prev_stats is not None:
            row["delta_expectancy_r"] = stats["expectancy_r"] - prev_stats["expectancy_r"] if stats["n"] and prev_stats["n"] else float("nan")
            row["delta_profit_factor"] = (
                stats["profit_factor"] - prev_stats["profit_factor"]
                if np_isfinite(stats["profit_factor"]) and np_isfinite(prev_stats["profit_factor"]) else float("nan")
            )
            row["delta_sharpe"] = stats["sharpe"] - prev_stats["sharpe"] if stats["n"] and prev_stats["n"] else float("nan")
            row["delta_max_drawdown_r"] = stats["max_drawdown_r"] - prev_stats["max_drawdown_r"] if stats["n"] and prev_stats["n"] else float("nan")
            row["delta_trade_count"] = stats["n"] - prev_stats["n"]
        rows.append(row)
        prev_stats = stats
    return rows


def np_isfinite(x: float) -> bool:
    try:
        return x == x and abs(x) != float("inf")
    except TypeError:
        return False


if __name__ == "__main__":
    from research.core.feature_bar import build_symbol_engine_data
    from research.data.synthetic import generate_multi_symbol_dataset

    ds = generate_multi_symbol_dataset(["EURUSD"], n_days=180)
    data = build_symbol_engine_data("EURUSD", ds["EURUSD"].bars)
    rows = run_ablation(data, BacktestConfig())
    for r in rows:
        print(r)
    print("OK")
