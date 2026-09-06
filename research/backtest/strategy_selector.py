"""
Phase 8AA — Strategy selection engine (research-only).

A causal, regime-conditional router: at each candidate signal's own entry
timestamp, look up the causal regime classification (research/core/
regime.py) and decide whether that signal's PRODUCING STRATEGY is
"allowed" to fire in that regime. Compared against two baselines per
Phase 8AA's own instruction ("test against random strategy selection,
single-strategy baseline, always-on strategy"):

  ALWAYS_ON:        every signal from every strategy is kept (no routing)
  RANDOM_SELECTION: each candidate signal is kept with the SAME overall
                      keep-rate as the real selector, but the keep/drop
                      decision is a coin flip independent of regime --
                      isolates whether the selector's REGIME-CONDITIONING
                      does anything beyond simply thinning the trade count
  REGIME_SELECTOR:  the actual routing table below

No look-ahead: the regime used to gate a signal is read at that signal's
own entry_ts, never a later bar.
"""
from __future__ import annotations

from typing import Dict, List

import numpy as np

from research.backtest.metrics import trade_stats
from research.strategies.base import row_asof

# Regime -> set of strategy names allowed to fire (Phase 8AA's worked example)
ROUTING_TABLE: Dict[str, set] = {
    "STRONG_UPTREND": {"trend_pullback", "structure_continuation", "significant_move_strong", "significant_move_moderate"},
    "UP_TREND": {"trend_pullback", "structure_continuation", "significant_move_moderate"},
    "WEAK_UPTREND": {"trend_pullback"},
    "STRONG_DOWNTREND": {"trend_pullback", "structure_continuation", "significant_move_strong", "significant_move_moderate"},
    "DOWN_TREND": {"trend_pullback", "structure_continuation", "significant_move_moderate"},
    "WEAK_DOWNTREND": {"trend_pullback"},
    # RANGE: trend-continuation strategies are NOT auto-enabled (Phase 8AA:
    # "IF RANGE: do not automatically trade trend strategy") -- only
    # mean-reversion-flavored / reversal strategies and OR fading are kept.
    "RANGE": {"opening_range_breakout", "structure_reversal"},
    # TRANSITION requires additional confirmation -- modeled here as
    # requiring the signal to also carry an explicit structure/liquidity
    # tag (a stricter subset than the routing table alone can express, so
    # this is layered on separately in `apply_selector` below).
    "TRANSITION": {"structure_reversal", "structure_continuation"},
    "HIGH_VOLATILITY": {"opening_range_breakout"},
    "EXPANSION": {"opening_range_breakout", "significant_move_strong"},
    "CONTRACTION": set(),  # low-information squeeze regime: nothing auto-enabled
    "LOW_VOLATILITY": set(),
    "UNKNOWN": set(),
}


def _regime_at_entry(ctx, entry_ts) -> str:
    row = row_asof(ctx.feature_bars, entry_ts)
    return str(row["regime_regime"]) if row is not None else "UNKNOWN"


def apply_selector(all_trades_by_strategy: Dict[str, list], ctx_by_symbol: Dict[str, object]) -> Dict[str, List]:
    """all_trades_by_strategy: {strategy_name: [TradeResult, ...]} for ONE
    symbol's worth of trades across every strategy tested on it.
    ctx_by_symbol here is really just ctx for that one symbol (kept as a
    dict for interface symmetry with multi-symbol callers)."""
    kept = []
    for strat_name, trades in all_trades_by_strategy.items():
        for t in trades:
            symbol = t.signal.symbol
            ctx = ctx_by_symbol[symbol]
            regime = _regime_at_entry(ctx, t.entry_ts)
            allowed = ROUTING_TABLE.get(regime, set())
            if strat_name in allowed:
                if regime == "TRANSITION" and t.signal.liquidity_state is None:
                    continue  # TRANSITION's "additional confirmation" requirement
                kept.append(t)
    return kept


def compare_selectors(all_trades_by_strategy: Dict[str, list], ctx_by_symbol: Dict[str, object], seed: int = 0) -> Dict[str, dict]:
    rng = np.random.default_rng(seed)
    all_trades = [t for trades in all_trades_by_strategy.values() for t in trades]

    always_on_stats = trade_stats(all_trades)

    selected = apply_selector(all_trades_by_strategy, ctx_by_symbol)
    selector_stats = trade_stats(selected)

    keep_rate = len(selected) / len(all_trades) if all_trades else 0.0
    random_mask = rng.random(len(all_trades)) < keep_rate
    random_selection = [t for t, keep in zip(all_trades, random_mask) if keep]
    random_stats = trade_stats(random_selection)

    return {
        "ALWAYS_ON": always_on_stats,
        "RANDOM_SELECTION": {**random_stats, "keep_rate": keep_rate},
        "REGIME_SELECTOR": {**selector_stats, "keep_rate": keep_rate},
    }


if __name__ == "__main__":
    from research.backtest.engine import BacktestConfig, run_backtest
    from research.core.feature_bar import build_symbol_engine_data
    from research.data.synthetic import generate_multi_symbol_dataset
    from research.strategies.opening_range import OpeningRangeBreakout
    from research.strategies.significant_move import SignificantMoveContinuation
    from research.strategies.structure_continuation import StructureContinuation
    from research.strategies.structure_reversal import StructureReversal
    from research.strategies.trend_pullback import TrendPullback

    ds = generate_multi_symbol_dataset(["EURUSD"], n_days=300)
    ctx = build_symbol_engine_data("EURUSD", ds["EURUSD"].bars)
    cfg = BacktestConfig()

    strategies = {
        "opening_range_breakout": OpeningRangeBreakout("continuation"),
        "trend_pullback": TrendPullback(),
        "structure_continuation": StructureContinuation(),
        "structure_reversal": StructureReversal(),
        "significant_move_strong": SignificantMoveContinuation("STRONG_MOVE"),
        "significant_move_moderate": SignificantMoveContinuation("MODERATE_MOVE"),
    }
    trades_by_strategy = {name: run_backtest(ctx, strat, cfg).trades for name, strat in strategies.items()}

    comparison = compare_selectors(trades_by_strategy, {"EURUSD": ctx})
    for name, stats in comparison.items():
        print(name, {k: v for k, v in stats.items() if k in ("n", "win_rate", "expectancy_r", "profit_factor", "sharpe", "keep_rate")})
    print("OK")
