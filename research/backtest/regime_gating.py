"""
Phase 9E/9V — Explicit regime-gating with named blocking codes.

Generalizes research/backtest/trend_only.py's binary ALL/TREND/STRONG_TREND
filter (Phase 8) into the exact outcome vocabulary Phase 9 asks for:
TRADE_ALLOWED / TRADE_BLOCKED_REGIME / TRADE_BLOCKED_DIRECTION /
TRADE_BLOCKED_STRUCTURE / TRADE_BLOCKED_VOLATILITY. Ranging markets are
NEVER silently discarded -- every candidate's gate decision and its
regime are both recorded, so "does avoiding ranges actually help" can be
answered from the data rather than assumed.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from research.backtest.metrics import trade_stats
from research.strategies.base import row_asof

STRONG_TREND_REGIMES = {"STRONG_UPTREND", "STRONG_DOWNTREND"}
ANY_TREND_REGIMES = {"STRONG_UPTREND", "UP_TREND", "WEAK_UPTREND", "STRONG_DOWNTREND", "DOWN_TREND", "WEAK_DOWNTREND"}
LOW_INFO_VOLATILITY_STATES = {"HIGH_VOLATILITY"}  # gated out under the "aggressive trend" preference below


def gate_trade(
    market_regime: Optional[str],
    trend_direction: Optional[str],
    candidate_direction: str,
    volatility_state: Optional[str],
    structure_direction: Optional[str],
    require_strong_trend: bool = False,
    require_direction_agreement: bool = True,
    block_high_volatility: bool = False,
) -> str:
    """Returns one of TRADE_ALLOWED / TRADE_BLOCKED_REGIME /
    TRADE_BLOCKED_DIRECTION / TRADE_BLOCKED_STRUCTURE /
    TRADE_BLOCKED_VOLATILITY. Checked in this order (first match wins) so
    every candidate gets exactly one reason, per Phase 9S's "must NOT
    automatically become a trade" requirement."""
    if require_strong_trend and market_regime not in STRONG_TREND_REGIMES:
        return "TRADE_BLOCKED_REGIME"
    if block_high_volatility and volatility_state in LOW_INFO_VOLATILITY_STATES:
        return "TRADE_BLOCKED_VOLATILITY"
    if require_direction_agreement and trend_direction is not None:
        candidate_trend = "LONG" if candidate_direction == "LONG" else "SHORT"
        if trend_direction not in ("NEUTRAL", None) and trend_direction != candidate_trend:
            return "TRADE_BLOCKED_DIRECTION"
    if structure_direction is not None:
        candidate_trend = "LONG" if candidate_direction == "LONG" else "SHORT"
        if structure_direction not in ("NEUTRAL", None) and structure_direction != candidate_trend:
            return "TRADE_BLOCKED_STRUCTURE"
    return "TRADE_ALLOWED"


def run_regime_gate_comparison(ctx, trades: list) -> Dict[str, Dict]:
    """For a list of already-generated TradeResults, classify each under
    three gate configurations (ungated / trend-required / strong-trend-
    required) and report stats for EVERY regime bucket under the
    ungated case (so ranging-market performance is visible, never
    discarded), plus the gated-vs-ungated comparison."""
    fb = ctx.feature_bars

    per_trade_regime = []
    for t in trades:
        row = row_asof(fb, t.entry_ts)
        regime = str(row["regime_regime"]) if row is not None else "UNKNOWN"
        trend_dir = str(row["regime_direction"]) if row is not None else "NEUTRAL"
        vol_state = str(row["regime_volatility_state"]) if row is not None else "NORMAL"
        struct_dir = str(row["regime_structure_state"]) if row is not None else "NEUTRAL"
        per_trade_regime.append((t, regime, trend_dir, vol_state, struct_dir))

    by_regime: Dict[str, list] = {}
    for t, regime, *_ in per_trade_regime:
        by_regime.setdefault(regime, []).append(t)
    regime_breakdown = {regime: trade_stats(trs) for regime, trs in by_regime.items()}

    configs = {
        "UNGATED": dict(require_strong_trend=False, require_direction_agreement=False, block_high_volatility=False),
        "DIRECTION_AGREEMENT_REQUIRED": dict(require_strong_trend=False, require_direction_agreement=True, block_high_volatility=False),
        "STRONG_TREND_REQUIRED": dict(require_strong_trend=True, require_direction_agreement=True, block_high_volatility=False),
    }

    gated_results = {}
    for config_name, kwargs in configs.items():
        allowed_trades = []
        blocked_counts: Dict[str, int] = {}
        for t, regime, trend_dir, vol_state, struct_dir in per_trade_regime:
            gate = gate_trade(regime, trend_dir, t.signal.direction, vol_state, struct_dir, **kwargs)
            blocked_counts[gate] = blocked_counts.get(gate, 0) + 1
            if gate == "TRADE_ALLOWED":
                allowed_trades.append(t)
        gated_results[config_name] = {"gate_counts": blocked_counts, **trade_stats(allowed_trades)}

    return {"regime_breakdown_ungated": regime_breakdown, "gate_configs": gated_results}


if __name__ == "__main__":
    from research.backtest.engine import BacktestConfig, run_backtest
    from research.core.feature_bar import build_symbol_engine_data
    from research.data.synthetic import generate_multi_symbol_dataset
    from research.strategies.trend_pullback import TrendPullback

    ds = generate_multi_symbol_dataset(["EURUSD"], n_days=300)
    ctx = build_symbol_engine_data("EURUSD", ds["EURUSD"].bars)
    run = run_backtest(ctx, TrendPullback(), BacktestConfig())

    result = run_regime_gate_comparison(ctx, run.trades)
    print("=== Regime breakdown (ungated, nothing discarded) ===")
    for regime, stats in result["regime_breakdown_ungated"].items():
        print(f"  {regime}: n={stats['n']} expectancy={stats['expectancy_r']:.3f}")
    print("=== Gate config comparison ===")
    for config, stats in result["gate_configs"].items():
        print(f"  {config}: gates={stats['gate_counts']} n={stats['n']} expectancy={stats.get('expectancy_r')}")
    print("OK")
