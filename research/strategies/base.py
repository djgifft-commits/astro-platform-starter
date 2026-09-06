"""
Phase 8 — Entry trigger engine scaffolding, shared by every strategy.

Separates BIAS (research/core/bias.py) from SETUP from CONFIRMATION from
ENTRY, per MASTER COMMAND rule 10. Every strategy subclasses `Strategy`
and implements `scan`, returning both the signals it generated AND every
rejected candidate with its first failing rule (Phase 24: "why did the
system NOT enter" is mandatory, not optional).
"""
from __future__ import annotations

import dataclasses
import enum
from typing import Dict, List, Optional, Tuple

import pandas as pd


class EntryState(str, enum.Enum):
    NO_SETUP = "NO_SETUP"
    SETUP_FORMING = "SETUP_FORMING"
    SETUP_READY = "SETUP_READY"
    CONFIRMATION_PENDING = "CONFIRMATION_PENDING"
    CONFIRMED = "CONFIRMED"
    ENTRY_TRIGGERED = "ENTRY_TRIGGERED"
    INVALIDATED = "INVALIDATED"
    EXPIRED = "EXPIRED"


@dataclasses.dataclass
class RuleCheck:
    name: str
    passed: bool
    detail: str = ""


@dataclasses.dataclass
class Signal:
    strategy: str
    variant: str
    symbol: str
    direction: str  # "LONG" / "SHORT"
    entry_ts: pd.Timestamp
    entry_price: float
    setup_reason: str
    rules_passed: List[str]
    rules_failed: List[str]
    market_condition: str
    directional_bias: str
    candle_pattern: Optional[str]
    fib_state: Optional[str]
    liquidity_state: Optional[str]
    displacement_state: Optional[str]
    meta: Dict = dataclasses.field(default_factory=dict)


@dataclasses.dataclass
class RejectedCandidate:
    strategy: str
    variant: str
    symbol: str
    ts: pd.Timestamp
    entry_state_reached: EntryState
    first_failing_rule: str
    rules_checked: List[RuleCheck]
    meta: Dict = dataclasses.field(default_factory=dict)


def row_asof(df: pd.DataFrame, ts: pd.Timestamp):
    """O(log n) equivalent of df.loc[df.index <= ts].iloc[-1] (or None if
    nothing qualifies)."""
    pos = df.index.searchsorted(ts, side="right") - 1
    if pos < 0:
        return None
    return df.iloc[pos]


def window_after(df: pd.DataFrame, ts: pd.Timestamp, n: int) -> pd.DataFrame:
    """O(log n) equivalent of df.loc[df.index > ts].iloc[:n] via binary
    search on the (sorted, monotonic) index, instead of an O(n) boolean
    mask per call — this matters when called once per candidate over many
    thousands of candidates."""
    pos = df.index.searchsorted(ts, side="right")
    return df.iloc[pos : pos + n]


def run_checklist(checks: List[Tuple[str, bool, str]]) -> Tuple[bool, List[RuleCheck], Optional[str]]:
    """Evaluate an ordered list of (name, passed, detail) checks. Returns
    (all_passed, full_checklist, first_failing_rule_name_or_None). Every
    check is evaluated (so the log shows the full picture), but the
    "first failing rule" is the first one in declared order that failed —
    this is what Phase 24's trade inspector shows as "why not."""
    results = [RuleCheck(name, passed, detail) for name, passed, detail in checks]
    first_failing = next((r.name for r in results if not r.passed), None)
    return (first_failing is None), results, first_failing


class Strategy:
    """ctx passed to `scan` is a research.core.feature_bar.SymbolEngineData
    — everything precomputed causally by the engine, once per run. No
    strategy recomputes its own features or sees any timestamp beyond the
    row it is currently evaluating."""
    name: str = "base"

    def scan(self, ctx) -> Tuple[List[Signal], List[RejectedCandidate]]:
        raise NotImplementedError
