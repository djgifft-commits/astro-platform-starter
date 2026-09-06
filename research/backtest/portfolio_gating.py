"""
Phase 9S — Position-overlap / portfolio engine.

A candidate signal must NOT automatically become a trade. This module
processes already-generated TradeResults (from possibly multiple symbols/
strategies) in strict chronological order and applies research/risk/
position_sizing.py's existing RiskLimits/RiskGuardState/check_risk_limits
(reused, not reimplemented) plus a correlation check, causally: a
candidate at time T is only ever compared against positions already open
and risk state already accumulated from trades that entered strictly
before T.

Outcome codes: EXECUTED, BLOCKED_POSITION_OVERLAP, BLOCKED_RISK,
BLOCKED_CORRELATION.
"""
from __future__ import annotations

import dataclasses
from typing import Dict, List, Optional, Tuple

from research.risk.exit_models import TradeResult
from research.risk.position_sizing import RiskGuardState, RiskLimits, check_risk_limits

RISK_LIMIT_TO_CODE = {
    "MAX_OPEN_POSITIONS": "BLOCKED_POSITION_OVERLAP",
    "MAX_GROSS_EXPOSURE": "BLOCKED_POSITION_OVERLAP",
    "MAX_DAILY_LOSS": "BLOCKED_RISK",
    "MAX_DRAWDOWN": "BLOCKED_RISK",
    "MAX_CONSECUTIVE_LOSSES": "BLOCKED_RISK",
}


@dataclasses.dataclass
class GatedTradeOutcome:
    trade: TradeResult
    outcome: str  # "EXECUTED" / "BLOCKED_POSITION_OVERLAP" / "BLOCKED_RISK" / "BLOCKED_CORRELATION"
    reasons: List[str]
    equity_after: float


def simulate_portfolio_gating(
    trades_by_symbol: Dict[str, List[TradeResult]],
    limits: RiskLimits = RiskLimits(),
    starting_equity: float = 10_000.0,
    risk_pct: float = 0.01,
    correlated_symbol_pairs: Optional[List[Tuple[str, str]]] = None,
) -> List[GatedTradeOutcome]:
    """correlated_symbol_pairs: symbol pairs to treat as correlated for the
    BLOCKED_CORRELATION check (pass real measured pairs from research/risk/
    hedge.py's rolling correlation report -- this function does not compute
    correlation itself, per the reuse-not-duplicate rule)."""
    correlated = set()
    for a, b in (correlated_symbol_pairs or []):
        correlated.add((a, b))
        correlated.add((b, a))

    all_trades = sorted(
        (t for trades in trades_by_symbol.values() for t in trades if t.exit_ts is not None),
        key=lambda t: t.entry_ts,
    )

    open_positions: List[TradeResult] = []
    state = RiskGuardState(peak_equity=starting_equity)
    equity = starting_equity
    daily_pnl_date = None
    outcomes: List[GatedTradeOutcome] = []

    for trade in all_trades:
        open_positions = [p for p in open_positions if p.exit_ts > trade.entry_ts]

        if daily_pnl_date != trade.entry_ts.normalize():
            daily_pnl_date = trade.entry_ts.normalize()
            state.daily_pnl = 0.0
            # MAX_CONSECUTIVE_LOSSES is a same-day circuit breaker, not a
            # permanent kill switch: without a day-boundary reset here, a
            # blocked candidate is never scored as a win/loss, so the
            # counter could never move again once tripped and trading
            # would be disabled for the rest of the backtest.
            state.consecutive_losses = 0

        state.open_positions = len(open_positions)
        state.symbol_exposure = {}
        for p in open_positions:
            state.symbol_exposure[p.signal.symbol] = state.symbol_exposure.get(p.signal.symbol, 0.0) + 1.0

        violations = check_risk_limits(state, limits, equity)
        if violations:
            code = RISK_LIMIT_TO_CODE.get(violations[0], "BLOCKED_RISK")
            outcomes.append(GatedTradeOutcome(trade, code, violations, equity))
            continue

        correlated_open = [p for p in open_positions if (p.signal.symbol, trade.signal.symbol) in correlated]
        if correlated_open:
            outcomes.append(GatedTradeOutcome(
                trade, "BLOCKED_CORRELATION",
                [f"correlated_with_open_position_in_{p.signal.symbol}" for p in correlated_open], equity,
            ))
            continue

        pnl = risk_pct * trade.r_multiple * equity
        equity += pnl
        state.peak_equity = max(state.peak_equity, equity)
        state.current_drawdown = (state.peak_equity - equity) / state.peak_equity if state.peak_equity > 0 else 0.0
        state.daily_pnl += pnl
        state.consecutive_losses = (state.consecutive_losses + 1) if trade.r_multiple <= 0 else 0

        open_positions.append(trade)
        outcomes.append(GatedTradeOutcome(trade, "EXECUTED", [], equity))

    return outcomes


def summarize_gating(outcomes: List[GatedTradeOutcome]) -> Dict:
    from collections import Counter
    counts = Counter(o.outcome for o in outcomes)
    executed = [o for o in outcomes if o.outcome == "EXECUTED"]
    return {
        "n_candidates": len(outcomes),
        "outcome_counts": dict(counts),
        "n_executed": len(executed),
        "final_equity": outcomes[-1].equity_after if outcomes else None,
        "execution_rate": len(executed) / len(outcomes) if outcomes else None,
    }


if __name__ == "__main__":
    from research.backtest.engine import BacktestConfig, run_backtest
    from research.core.feature_bar import build_symbol_engine_data
    from research.data.synthetic import generate_multi_symbol_dataset
    from research.strategies.opening_range_v2 import OpeningRangeStateMachine

    ds = generate_multi_symbol_dataset(
        ["EURUSD", "GBPUSD"], n_days=300, factor_loadings={"EURUSD": 0.75, "GBPUSD": 0.65}
    )
    ctxs = {sym: build_symbol_engine_data(sym, d.bars) for sym, d in ds.items()}
    cfg = BacktestConfig()

    trades_by_symbol = {}
    for sym, ctx in ctxs.items():
        strat = OpeningRangeStateMachine(entry_family="breakout")
        run = run_backtest(ctx, strat, cfg)
        trades_by_symbol[sym] = run.trades

    # tight limits deliberately, to exercise every blocking code
    limits = RiskLimits(max_open_positions=2, max_daily_loss_pct=0.02, max_consecutive_losses=3)
    outcomes = simulate_portfolio_gating(trades_by_symbol, limits=limits, correlated_symbol_pairs=[("EURUSD", "GBPUSD")])
    summary = summarize_gating(outcomes)
    print(summary)
    assert summary["n_candidates"] == sum(len(t) for t in trades_by_symbol.values() if t)
    print("OK")
