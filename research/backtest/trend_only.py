"""
Phase 8R — Aggressive trend-only mode.

Compares ALL_REGIMES vs TREND_ONLY vs STRONG_TREND_ONLY for a given
strategy/config, using the causal regime classifier's OWN output at each
signal's entry timestamp (never the hidden synthetic ground truth) to
decide whether a signal would have been allowed through. Does not assume
trend-only is better -- reports opportunity cost (the R that was foregone
on filtered-out signals) alongside the surviving trades' stats, exactly as
instructed.
"""
from __future__ import annotations

import dataclasses
from typing import List

from research.backtest.engine import BacktestConfig, run_backtest
from research.backtest.metrics import trade_stats
from research.risk.exit_models import TradeResult
from research.strategies.base import Signal, row_asof

TREND_REGIMES = {"UP_TREND", "STRONG_UPTREND", "WEAK_UPTREND", "DOWN_TREND", "STRONG_DOWNTREND", "WEAK_DOWNTREND"}
STRONG_TREND_REGIMES = {"STRONG_UPTREND", "STRONG_DOWNTREND"}

FILTER_MODES = {
    "ALL_REGIMES": None,
    "TREND_ONLY": TREND_REGIMES,
    "STRONG_TREND_ONLY": STRONG_TREND_REGIMES,
}


def _regime_at_entry(ctx, signal: Signal) -> str:
    row = row_asof(ctx.feature_bars, signal.entry_ts)
    return str(row["regime_regime"]) if row is not None else "UNKNOWN"


def run_trend_only_comparison(ctx, strategy, base_config: BacktestConfig) -> dict:
    full_run = run_backtest(ctx, strategy, base_config)

    results = {}
    for mode_name, allowed_regimes in FILTER_MODES.items():
        if allowed_regimes is None:
            kept: List[TradeResult] = list(full_run.trades)
            skipped: List[TradeResult] = []
        else:
            kept, skipped = [], []
            for trade in full_run.trades:
                regime = _regime_at_entry(ctx, trade.signal)
                (kept if regime in allowed_regimes else skipped).append(trade)

        stats = trade_stats(kept)
        skipped_stats = trade_stats(skipped)
        time_in_market_bars = sum(t.duration_bars for t in kept)

        results[mode_name] = {
            **stats,
            "time_in_market_bars": time_in_market_bars,
            "n_skipped": skipped_stats["n"],
            "opportunity_cost_total_r": (
                skipped_stats["expectancy_r"] * skipped_stats["n"] if skipped_stats["n"] else 0.0
            ),
            "opportunity_cost_mean_r": skipped_stats["expectancy_r"],
        }
    return results


if __name__ == "__main__":
    from research.core.feature_bar import build_symbol_engine_data
    from research.data.synthetic import generate_multi_symbol_dataset
    from research.strategies.trend_pullback import TrendPullback

    ds = generate_multi_symbol_dataset(["EURUSD"], n_days=300)
    data = build_symbol_engine_data("EURUSD", ds["EURUSD"].bars)
    strat = TrendPullback()
    cfg = BacktestConfig()

    results = run_trend_only_comparison(data, strat, cfg)
    for mode, r in results.items():
        print(mode, {k: v for k, v in r.items() if k in
                     ("n", "win_rate", "expectancy_r", "profit_factor", "sharpe", "max_drawdown_r",
                      "n_skipped", "opportunity_cost_total_r")})
    print("OK")
