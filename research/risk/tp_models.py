"""
Phase 10 — Take-profit research.

Implemented (subset of the 12 named): FIXED_R (1R/1.5R/2R/3R), ATR_TARGET,
STRUCTURE_TARGET (nearest already-confirmed opposing swing extreme that
lies beyond entry in the favorable direction — causal: only uses swings
confirmed before entry, never a future swing). Liquidity-pool target,
Fibonacci-extension target, and partial+runner are deferred: partial+
runner and the liquidity/structure "next pool" target are more naturally
EXIT models (they require walking the trade forward, see
research/risk/exit_models.py) rather than a single static price fixed at
entry, and are covered there instead of being duplicated as a TP model.
"""
from __future__ import annotations

import dataclasses
from typing import Optional

from research.strategies.base import Signal


@dataclasses.dataclass
class TakeProfit:
    model: str
    price: float
    distance: float


def fixed_r(signal: Signal, sl_distance: float, r_multiple: float) -> TakeProfit:
    dist = sl_distance * r_multiple
    price = signal.entry_price + dist if signal.direction == "LONG" else signal.entry_price - dist
    return TakeProfit(f"FIXED_{r_multiple}R", price, dist)


def atr_target(signal: Signal, atr_at_entry: float, mult: float = 2.0) -> TakeProfit:
    dist = atr_at_entry * mult
    price = signal.entry_price + dist if signal.direction == "LONG" else signal.entry_price - dist
    return TakeProfit("ATR_TARGET", price, dist)


def structure_target(signal: Signal, swings: list, entry_pos: int) -> Optional[TakeProfit]:
    kind_needed = "HIGH" if signal.direction == "LONG" else "LOW"
    candidates = [s for s in swings if s.confirmed_at_pos <= entry_pos and s.kind == kind_needed]
    if signal.direction == "LONG":
        candidates = [s for s in candidates if s.price > signal.entry_price]
    else:
        candidates = [s for s in candidates if s.price < signal.entry_price]
    if not candidates:
        return None
    nearest = min(candidates, key=lambda s: abs(s.price - signal.entry_price))
    dist = abs(nearest.price - signal.entry_price)
    if dist <= 0:
        return None
    return TakeProfit("STRUCTURE_TARGET", nearest.price, dist)


def or_extension(signal: Signal, extension_mult: float = 1.0) -> Optional[TakeProfit]:
    """Phase 8P: opening-range extension target -- projects the OR's own
    range beyond the boundary the trade broke out through (a "measured
    move" of the OR). Only usable for opening_range_breakout signals,
    which attach or_high/or_low/or_mid to `signal.meta`."""
    if "or_high" not in signal.meta or "or_low" not in signal.meta:
        return None
    or_range = signal.meta["or_high"] - signal.meta["or_low"]
    if or_range <= 0:
        return None
    dist = or_range * extension_mult
    price = signal.entry_price + dist if signal.direction == "LONG" else signal.entry_price - dist
    return TakeProfit(f"OR_EXTENSION_{extension_mult}x", price, dist)


TP_MODELS = [
    "FIXED_1R", "FIXED_1.5R", "FIXED_2R", "FIXED_3R", "ATR_TARGET", "STRUCTURE_TARGET",
    "OR_EXTENSION_1.0x",
]
