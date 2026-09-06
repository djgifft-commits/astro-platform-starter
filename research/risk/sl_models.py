"""
Phase 9 — Stop-loss research.

Every model returns a stop-loss PRICE computed only from information
available at/before the signal's entry timestamp (causal). No model here
is assumed superior; research/backtest/validation.py is where that
question gets an answer, per-strategy, per-regime.

Implemented: FIXED_ATR, STRUCTURE_INVALIDATION, SWING_EXTREME,
OR_OPPOSITE_BOUNDARY, VOLATILITY_ADAPTIVE (Phase 7), FIBONACCI_INVALIDATION
and LIQUIDITY_BASED (Phase 8O), plus BREAKOUT_CANDLE (Phase 9N: stop
beyond the M5 breakout candle's own opposite extreme — only usable for
signals whose strategy attaches `breakout_candle_low`/
`breakout_candle_high` to `signal.meta`, e.g.
research/strategies/opening_range_v2.py). OB_INVALIDATION remains
deferred: this project has no order-block detector (scope narrowing, see
audit report); implementing one solely to produce a near-duplicate of
STRUCTURE_INVALIDATION would not test a distinct hypothesis.
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


def fibonacci_invalidation(signal: Signal, buffer_atr: float = 0.1, atr_at_entry: float = 0.0) -> Optional[StopLoss]:
    """Stop beyond the originating impulse's own start price (the "0%/100%"
    Fibonacci anchor) -- only usable for signals produced by a retracement-
    based strategy (research/strategies/trend_pullback.py,
    research/strategies/fib_pullback.py), which attach
    `impulse_start_price` to `signal.meta`."""
    start_price = signal.meta.get("impulse_start_price")
    if start_price is None:
        return None
    buffer = buffer_atr * atr_at_entry
    price = start_price - buffer if signal.direction == "LONG" else start_price + buffer
    dist = abs(signal.entry_price - price)
    if dist <= 0:
        return None
    return StopLoss("FIBONACCI_INVALIDATION", price, dist)


def liquidity_based(signal: Signal, liquidity_pools: list, buffer_atr: float = 0.05, atr_at_entry: float = 0.0) -> Optional[StopLoss]:
    """Stop just beyond the nearest ESTIMATED_STOP_LIQUIDITY pool on the
    invalidating side of entry (e.g. the nearest SSL pool below entry for
    a LONG). This is a geometric heuristic (research/core/liquidity.py) —
    not a claim about real resting stop orders."""
    kind_needed = "SSL" if signal.direction == "LONG" else "BSL"
    candidates = [p for p in liquidity_pools if p.kind == kind_needed]
    if signal.direction == "LONG":
        candidates = [p for p in candidates if p.price < signal.entry_price]
    else:
        candidates = [p for p in candidates if p.price > signal.entry_price]
    if not candidates:
        return None
    nearest = min(candidates, key=lambda p: abs(p.price - signal.entry_price))
    buffer = buffer_atr * atr_at_entry
    price = nearest.price - buffer if signal.direction == "LONG" else nearest.price + buffer
    dist = abs(signal.entry_price - price)
    if dist <= 0:
        return None
    return StopLoss("LIQUIDITY_BASED", price, dist)


def breakout_candle(signal: Signal, buffer_atr: float = 0.05, atr_at_entry: float = 0.0) -> Optional[StopLoss]:
    """Stop just beyond the M5 breakout candle's own opposite extreme
    (Phase 9N). Requires `breakout_candle_low`/`breakout_candle_high` in
    signal.meta -- only opening_range_v2.py's signals carry these."""
    key = "breakout_candle_low" if signal.direction == "LONG" else "breakout_candle_high"
    level = signal.meta.get(key)
    if level is None:
        return None
    buffer = buffer_atr * atr_at_entry
    price = level - buffer if signal.direction == "LONG" else level + buffer
    dist = abs(signal.entry_price - price)
    if dist <= 0:
        return None
    return StopLoss("BREAKOUT_CANDLE", price, dist)


SL_MODELS = [
    "FIXED_ATR", "STRUCTURE_INVALIDATION", "SWING_EXTREME", "OR_OPPOSITE_BOUNDARY",
    "VOLATILITY_ADAPTIVE", "FIBONACCI_INVALIDATION", "LIQUIDITY_BASED", "BREAKOUT_CANDLE",
]
