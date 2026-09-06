"""
Phase 8AE — No-trade analysis (mandatory, not optional).

Builds the funnel:

    CANDIDATES -> FILTERED -> CONFIRMED -> EXECUTED -> WIN / LOSS

from the SAME Signal/RejectedCandidate/TradeResult records every strategy
already produces (research/strategies/base.py, research/backtest/
engine.py) -- no new tracking mechanism, just a structured rollup of data
that already exists, plus a breakdown of the exact rejection reason at
every stage so bottlenecks are visible rather than guessed at.

Stage semantics for this project's strategies:
  CANDIDATES  = every RejectedCandidate + every Signal (every setup the
                 strategy ever looked at, whether or not it went anywhere)
  FILTERED    = candidates rejected at "SETUP_FORMING" (failed a context/
                 regime/bias/liquidity precondition before any entry
                 trigger was even evaluated)
  CONFIRMED   = candidates that passed context/setup but were rejected at
                 "CONFIRMATION_PENDING" (an entry trigger was searched for
                 but never found/confirmed within the monitoring window)
  EXECUTED    = actual Signals that became trades
  WIN / LOSS  = executed trades split by r_multiple sign
"""
from __future__ import annotations

from collections import Counter
from typing import Dict, List

from research.risk.exit_models import TradeResult
from research.strategies.base import RejectedCandidate, Signal


def build_funnel(signals: List[Signal], rejected: List[RejectedCandidate], trades: List[TradeResult]) -> Dict:
    filtered = [r for r in rejected if r.entry_state_reached in ("SETUP_FORMING", "SETUP_READY")]
    confirmation_pending = [r for r in rejected if r.entry_state_reached == "CONFIRMATION_PENDING"]

    wins = [t for t in trades if t.r_multiple > 0]
    losses = [t for t in trades if t.r_multiple <= 0]

    n_candidates = len(signals) + len(rejected)

    return {
        "n_candidates": n_candidates,
        "n_filtered": len(filtered),
        "filtered_reasons": dict(Counter(r.first_failing_rule for r in filtered).most_common(10)),
        "n_confirmed_but_not_triggered": len(confirmation_pending),
        "confirmation_pending_reasons": dict(Counter(r.first_failing_rule for r in confirmation_pending).most_common(10)),
        "n_executed": len(signals),
        "n_win": len(wins),
        "n_loss": len(losses),
        "win_rate_of_executed": len(wins) / len(trades) if trades else None,
        "filtered_rate": len(filtered) / n_candidates if n_candidates else None,
        "confirmation_failure_rate": len(confirmation_pending) / n_candidates if n_candidates else None,
        "execution_rate": len(signals) / n_candidates if n_candidates else None,
    }


def build_funnel_report(matrix_run_results: List[dict]) -> List[dict]:
    """matrix_run_results: list of dicts each with keys 'symbol',
    'strategy', 'signals', 'rejected', 'trades' (the raw objects, not
    just their JSON-serialized stats) -- produces one funnel row per
    (symbol, strategy) cell, exactly mirroring the Pair x Strategy x
    Regime matrix's granularity."""
    rows = []
    for r in matrix_run_results:
        funnel = build_funnel(r["signals"], r["rejected"], r["trades"])
        rows.append({"symbol": r["symbol"], "strategy": r["strategy"], **funnel})
    return rows


if __name__ == "__main__":
    from research.backtest.engine import BacktestConfig, run_backtest
    from research.core.feature_bar import build_symbol_engine_data
    from research.data.synthetic import generate_multi_symbol_dataset
    from research.strategies.structure_continuation import StructureContinuation

    ds = generate_multi_symbol_dataset(["EURUSD"], n_days=300)
    ctx = build_symbol_engine_data("EURUSD", ds["EURUSD"].bars)
    run = run_backtest(ctx, StructureContinuation(), BacktestConfig())

    funnel = build_funnel(run.signals, run.rejected, run.trades)
    for k, v in funnel.items():
        print(k, ":", v)
    assert funnel["n_executed"] == len(run.trades) or funnel["n_executed"] >= len(run.trades)
    print("OK")
