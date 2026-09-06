"""
Phase 9B/9L — ENTRY_DECISION object.

A richer, explicitly-auditable superset of research/strategies/base.py's
existing `Signal` / `RejectedCandidate` dataclasses (not a replacement —
those remain the source of truth every strategy actually emits; this
module converts one of them, plus a MarketContext, into the exact shape
Phase 9L asks for). Separates CONTEXT (the MarketContext) from
CONFIRMATION (rules_passed) from TRIGGER (the entry itself) explicitly.
"""
from __future__ import annotations

import dataclasses
import enum
from typing import List, Optional

import pandas as pd

from research.core.market_context import MarketContext
from research.strategies.base import RejectedCandidate, Signal


class BlockingCode(str, enum.Enum):
    NONE = "NONE"
    TRADE_BLOCKED_REGIME = "TRADE_BLOCKED_REGIME"
    TRADE_BLOCKED_DIRECTION = "TRADE_BLOCKED_DIRECTION"
    TRADE_BLOCKED_STRUCTURE = "TRADE_BLOCKED_STRUCTURE"
    TRADE_BLOCKED_VOLATILITY = "TRADE_BLOCKED_VOLATILITY"
    TRADE_BLOCKED_CONFIRMATION = "TRADE_BLOCKED_CONFIRMATION"
    TRADE_BLOCKED_POSITION_OVERLAP = "TRADE_BLOCKED_POSITION_OVERLAP"
    TRADE_BLOCKED_RISK = "TRADE_BLOCKED_RISK"
    TRADE_BLOCKED_CORRELATION = "TRADE_BLOCKED_CORRELATION"
    TRADE_BLOCKED_SESSION = "TRADE_BLOCKED_SESSION"
    TRADE_BLOCKED_SPREAD = "TRADE_BLOCKED_SPREAD"
    TRADE_BLOCKED_RR = "TRADE_BLOCKED_RR"


@dataclasses.dataclass
class EntryDecision:
    decision: str  # "ENTRY_CONFIRMED" / "TRADE_BLOCKED" / "TRADE_EXECUTED"
    score: float  # fraction of declared rules passed, in [0, 1]
    reasons: List[str]
    failed_conditions: List[str]
    market_context: MarketContext
    entry_type: str  # "BREAKOUT" / "RETEST" / "REVERSAL" / strategy name
    direction: Optional[str]
    confirmation_timestamp: Optional[pd.Timestamp]
    entry_timestamp: Optional[pd.Timestamp]
    confidence: float
    risk_state: str
    blocking_code: str


def _score(rules_passed: List[str], rules_failed: List[str]) -> float:
    total = len(rules_passed) + len(rules_failed)
    return (len(rules_passed) / total) if total else 0.0


def from_signal(signal: Signal, market_context: MarketContext, entry_type: Optional[str] = None) -> EntryDecision:
    return EntryDecision(
        decision="ENTRY_CONFIRMED",
        score=_score(signal.rules_passed, signal.rules_failed),
        reasons=list(signal.rules_passed) + ([signal.setup_reason] if signal.setup_reason else []),
        failed_conditions=list(signal.rules_failed),
        market_context=market_context,
        entry_type=entry_type or signal.variant,
        direction=signal.direction,
        confirmation_timestamp=signal.entry_ts,
        entry_timestamp=signal.entry_ts,
        confidence=market_context.bias_confidence or 0.0,
        risk_state="RISK_UNASSESSED_AT_SIGNAL_TIME",
        blocking_code=BlockingCode.NONE.value,
    )


def from_rejected(rejected: RejectedCandidate, market_context: MarketContext, entry_type: Optional[str] = None) -> EntryDecision:
    passed = [c.name for c in rejected.rules_checked if c.passed]
    failed = [c.name for c in rejected.rules_checked if not c.passed]
    blocking_code = _infer_blocking_code(rejected.first_failing_rule)
    return EntryDecision(
        decision="TRADE_BLOCKED",
        score=_score(passed, failed),
        reasons=passed,
        failed_conditions=failed or [rejected.first_failing_rule],
        market_context=market_context,
        entry_type=entry_type or rejected.variant,
        direction=None,
        confirmation_timestamp=None,
        entry_timestamp=None,
        confidence=0.0,
        risk_state="NOT_APPLICABLE",
        blocking_code=blocking_code.value,
    )


_BLOCKING_CODE_KEYWORDS = [
    ("regime", BlockingCode.TRADE_BLOCKED_REGIME),
    ("trend_regime", BlockingCode.TRADE_BLOCKED_REGIME),
    ("bias", BlockingCode.TRADE_BLOCKED_DIRECTION),
    ("structure", BlockingCode.TRADE_BLOCKED_STRUCTURE),
    ("volatility", BlockingCode.TRADE_BLOCKED_VOLATILITY),
    ("liquidity", BlockingCode.TRADE_BLOCKED_STRUCTURE),
    ("confirmation", BlockingCode.TRADE_BLOCKED_CONFIRMATION),
    ("confirm", BlockingCode.TRADE_BLOCKED_CONFIRMATION),
    ("session", BlockingCode.TRADE_BLOCKED_SESSION),
    ("spread", BlockingCode.TRADE_BLOCKED_SPREAD),
    ("rr", BlockingCode.TRADE_BLOCKED_RR),
    ("risk", BlockingCode.TRADE_BLOCKED_RISK),
    ("overlap", BlockingCode.TRADE_BLOCKED_POSITION_OVERLAP),
    ("correlation", BlockingCode.TRADE_BLOCKED_CORRELATION),
]


def _infer_blocking_code(first_failing_rule: str) -> BlockingCode:
    rule_lower = (first_failing_rule or "").lower()
    for keyword, code in _BLOCKING_CODE_KEYWORDS:
        if keyword in rule_lower:
            return code
    return BlockingCode.TRADE_BLOCKED_CONFIRMATION


if __name__ == "__main__":
    from research.core.feature_bar import build_symbol_engine_data
    from research.core.market_context import build_market_context
    from research.core.protected_levels import compute_protected_levels, compute_structure_layers
    from research.core.regime import _current_structure_direction
    from research.data.synthetic import generate_multi_symbol_dataset
    from research.strategies.opening_range import OpeningRangeBreakout

    ds = generate_multi_symbol_dataset(["EURUSD"], n_days=90)
    ctx = build_symbol_engine_data("EURUSD", ds["EURUSD"].bars)
    exec_df = ctx.frames[ctx.execution_tf]
    layers = compute_structure_layers(exec_df)
    protected = compute_protected_levels(exec_df, layers.external_events, layers.external_swings)
    ext_dir = _current_structure_direction(exec_df, layers.external_events)
    int_dir = _current_structure_direction(exec_df, layers.internal_events)

    strat = OpeningRangeBreakout(variant="continuation")
    signals, rejected = strat.scan(ctx)

    if signals:
        mc = build_market_context(ctx, signals[0].entry_ts, protected, layers.external_events, ext_dir, int_dir)
        ed = from_signal(signals[0], mc, entry_type="BREAKOUT")
        print("Signal -> EntryDecision:")
        print(" decision:", ed.decision, "score:", ed.score, "blocking_code:", ed.blocking_code)
        print(" market_context.market_regime:", ed.market_context.market_regime)

    if rejected:
        mc2 = build_market_context(ctx, rejected[0].ts, protected, layers.external_events, ext_dir, int_dir)
        ed2 = from_rejected(rejected[0], mc2, entry_type="BREAKOUT")
        print("RejectedCandidate -> EntryDecision:")
        print(" decision:", ed2.decision, "blocking_code:", ed2.blocking_code, "failed:", ed2.failed_conditions)

    assert signals and rejected, "expected both signals and rejections in this sample"
    print("OK")
