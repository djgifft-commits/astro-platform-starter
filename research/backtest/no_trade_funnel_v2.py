"""
Phase 9T — No-trade funnel with the exact stage sequence Phase 9B names:

    candidate
    -> session valid?
    -> market regime valid?
    -> directional bias valid?
    -> structure valid?
    -> liquidity event?
    -> range breakout?
    -> M5 confirmation?
    -> M1 trigger?
    -> SL valid?
    -> RR valid?
    -> risk valid?
    -> position overlap?
    -> EXECUTE

Reuses research/backtest/no_trade_funnel.py's simpler 3-stage funnel
(FILTERED/CONFIRMATION_PENDING/EXECUTED) as its foundation and the
`first_failing_rule` text already recorded on every RejectedCandidate
(research/strategies/base.py) -- this module only adds the finer-grained
stage classification by pattern-matching that text, plus the trailing
risk/position-overlap stages which the strategy layer itself does not
know about (those come from research/backtest/portfolio_gating.py,
composed here rather than duplicated).
"""
from __future__ import annotations

from collections import Counter
from typing import Dict, List, Optional

FUNNEL_STAGES = [
    "session_valid", "regime_valid", "bias_valid", "structure_valid",
    "liquidity_event", "range_breakout", "m5_confirmation", "m1_trigger",
    "sl_valid", "rr_valid", "risk_valid", "position_overlap", "executed",
]

_STAGE_KEYWORDS = [
    ("session", "session_valid"),
    ("regime", "regime_valid"),
    ("bias", "bias_valid"),
    ("structure", "structure_valid"),
    ("liquidity", "liquidity_event"),
    ("breakout", "range_breakout"),
    ("m5", "m5_confirmation"),
    ("confirmed_m5", "m5_confirmation"),
    ("confirmation_pending", "m1_trigger"),
    ("m1", "m1_trigger"),
    ("retest", "range_breakout"),
    ("sweep", "range_breakout"),
    ("reversal", "range_breakout"),
    ("sl", "sl_valid"),
    ("rr", "rr_valid"),
    ("risk", "risk_valid"),
    ("overlap", "position_overlap"),
]


def _classify_stage(first_failing_rule: str, entry_state_reached: str) -> str:
    text = (first_failing_rule or "").lower()
    for keyword, stage in _STAGE_KEYWORDS:
        if keyword in text:
            return stage
    if entry_state_reached == "SETUP_FORMING":
        return "structure_valid"
    if entry_state_reached == "CONFIRMATION_PENDING":
        return "m1_trigger"
    return "m1_trigger"


def build_detailed_funnel(
    signals: list,
    rejected: list,
    position_overlap_blocked: Optional[List] = None,
    risk_blocked: Optional[List] = None,
) -> Dict:
    """signals/rejected: raw Signal/RejectedCandidate lists from a single
    strategy.scan() call. position_overlap_blocked/risk_blocked: optional
    lists of decisions blocked downstream by research/backtest/
    portfolio_gating.py (composed, not duplicated -- that module owns the
    actual overlap/risk logic)."""
    stage_rejections = Counter()
    for r in rejected:
        stage = _classify_stage(r.first_failing_rule, str(r.entry_state_reached))
        stage_rejections[stage] += 1

    n_candidates = len(signals) + len(rejected)
    n_risk_blocked = len(risk_blocked) if risk_blocked else 0
    n_overlap_blocked = len(position_overlap_blocked) if position_overlap_blocked else 0
    n_executed = max(0, len(signals) - n_risk_blocked - n_overlap_blocked)

    funnel_counts = {stage: stage_rejections.get(stage, 0) for stage in FUNNEL_STAGES if stage not in ("risk_valid", "position_overlap", "executed")}
    funnel_counts["risk_valid"] = n_risk_blocked
    funnel_counts["position_overlap"] = n_overlap_blocked
    funnel_counts["executed"] = n_executed

    funnel_pct = {stage: (count / n_candidates if n_candidates else None) for stage, count in funnel_counts.items()}

    return {
        "n_candidates": n_candidates,
        "rejections_by_stage": funnel_counts,
        "rejection_pct_by_stage": funnel_pct,
        "n_executed": n_executed,
        "execution_rate": n_executed / n_candidates if n_candidates else None,
    }


if __name__ == "__main__":
    from research.core.feature_bar import build_symbol_engine_data
    from research.data.synthetic import generate_multi_symbol_dataset
    from research.strategies.opening_range_v2 import OpeningRangeStateMachine

    ds = generate_multi_symbol_dataset(["EURUSD"], n_days=300)
    ctx = build_symbol_engine_data("EURUSD", ds["EURUSD"].bars)

    for family in ("breakout", "retest", "reversal"):
        strat = OpeningRangeStateMachine(entry_family=family)
        signals, rejected = strat.scan(ctx)
        funnel = build_detailed_funnel(signals, rejected)
        print(family, funnel)
    print("OK")
