"""
Phase 9 — Stop-loss research.

Every model returns a stop-loss PRICE computed only from information
available at/before the signal's entry timestamp (causal). No model here
is assumed superior; research/backtest/validation.py is where that
question gets an answer, per-strategy, per-regime.

Implemented (5 of the 8 named in the MASTER COMMAND): FIXED_ATR,
STRUCTURE_INVALIDATION, SWING_EXTREME, OR_OPPOSITE_BOUNDARY,
VOLATILITY_ADAPTIVE (a hybrid of ATR + regime volatility state, which also
covers the "hybrid structure + ATR buffer" case when combined with
STRUCTURE_INVALIDATION's buffer argument). LIQUIDITY_INVALIDATION and
OB_INVALIDATION are deferred: this project has no order-block detector
(scope narrowing, see audit report) and liquidity-based stops would
duplicate STRUCTURE_INVALIDATION under this project's swing-based
liquidity-pool definition (research/core/liquidity.py) — implementing both
would test the same hypothesis twice under different names.
"""
from __future__ import annotations

import dataclasses
from typing import Optional

import pandas as pd

from research.strategies.base import Signal


@dataclasses.dataclass
class StopLoss:
    model: str
    price: float
    distance: float


def fixed_atr(signal: Signal, atr_at_entry: float, mult: float = 1.5) -> StopLoss:
    dist = atr_at_entry * mult
    price = signal.entry_price - dist if signal.direction == "LONG" else signal.entry_price + dist
    return StopLoss("FIXED_ATR", price, dist)


def structure_invalidation(signal: Signal, structure_events: list, entry_pos: int, buffer: float = 0.0) -> Optional[StopLoss]:
    """Nearest same-side structure break price before entry, in the
    direction that would invalidate the trade thesis if breached."""
    candidates = [e for e in structure_events if e.index_pos < entry_pos]
    if not candidates:
        return None
    last = candidates[-1]
    if signal.direction == "LONG":
        price = last.broken_swing_price - buffer
    else:
        price = last.broken_swing_price + buffer
    dist = abs(signal.entry_price - price)
    if dist <= 0:
        return None
    return StopLoss("STRUCTURE_INVALIDATION", price, dist)


def swing_extreme(signal: Signal, swings: list, entry_pos: int, buffer_atr: float = 0.1, atr_at_entry: float = 0.0) -> Optional[StopLoss]:
    """Most recent opposite-type confirmed swing before entry (a classic
    'stop beyond the last swing low/high')."""
    kind_needed = "LOW" if signal.direction == "LONG" else "HIGH"
    candidates = [s for s in swings if s.confirmed_at_pos <= entry_pos and s.kind == kind_needed]
    if not candidates:
        return None
    last = candidates[-1]
    buffer = buffer_atr * atr_at_entry
    price = last.price - buffer if signal.direction == "LONG" else last.price + buffer
    dist = abs(signal.entry_price - price)
    if dist <= 0:
        return None
    return StopLoss("SWING_EXTREME", price, dist)


def or_opposite_boundary(signal: Signal) -> Optional[StopLoss]:
    if "or_high" not in signal.meta or "or_low" not in signal.meta:
        return None
    price = signal.meta["or_low"] if signal.direction == "LONG" else signal.meta["or_high"]
    dist = abs(signal.entry_price - price)
    if dist <= 0:
        return None
    return StopLoss("OR_OPPOSITE_BOUNDARY", price, dist)


def volatility_adaptive(signal: Signal, atr_at_entry: float, volatility_state: str) -> StopLoss:
    """ATR-multiple stop that widens in HIGH_VOLATILITY and tightens in
    LOW_VOLATILITY, instead of using one constant multiple regardless of
    regime."""
    mult = {"HIGH_VOLATILITY": 2.5, "LOW_VOLATILITY": 1.0, "NORMAL": 1.5}.get(volatility_state, 1.5)
    dist = atr_at_entry * mult
    price = signal.entry_price - dist if signal.direction == "LONG" else signal.entry_price + dist
    return StopLoss("VOLATILITY_ADAPTIVE", price, dist)


SL_MODELS = ["FIXED_ATR", "STRUCTURE_INVALIDATION", "SWING_EXTREME", "OR_OPPOSITE_BOUNDARY", "VOLATILITY_ADAPTIVE"]
