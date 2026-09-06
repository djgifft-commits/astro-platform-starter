"""
Phase 3 inputs / Phase 5 SMC modules — market structure.

IMPORTANT (RESEARCH_CARDS.md cards E/F/G): "BOS", "CHOCH", "MSS" have no
standardized, falsifiable academic definition — they come from retail
(ICT/SMC) educational material. This module gives them an explicit,
mechanical, causal definition so they can be tested rather than assumed:

- A swing high/low is CONFIRMED only `confirm_bars` bars after it forms
  (a fractal: the highest/lowest of a `2*confirm_bars+1` window, known
  only once the trailing bars exist) — this is what makes swing detection
  causal: a swing at index i is not usable until index i + confirm_bars.
- HH/HL/LH/LL are relative to the immediately preceding confirmed swing of
  the same type.
- BOS = a confirmed CLOSE beyond the most recent confirmed swing extreme
  in the direction of the prevailing structure (continuation).
- CHOCH/MSS = a confirmed CLOSE beyond the most recent confirmed swing
  extreme AGAINST the prevailing structure (the first such break is
  CHOCH; the label MSS is used interchangeably here for the same event,
  since no source distinguishes them mechanically).

Every one of these has free parameters (confirm_bars). Report results
across a small grid, never a single hand-picked value, per RESEARCH_CARDS.
"""
from __future__ import annotations

import dataclasses
from typing import List, Literal

import numpy as np
import pandas as pd

SwingType = Literal["HIGH", "LOW"]


@dataclasses.dataclass
class Swing:
    index_pos: int
    timestamp: pd.Timestamp
    price: float
    kind: SwingType
    label: str  # HH, HL, LH, LL, or "" if not yet classifiable (first swing of its kind)
    confirmed_at_pos: int  # bar position at which this swing became knowable


@dataclasses.dataclass
class StructureEvent:
    index_pos: int
    timestamp: pd.Timestamp
    kind: Literal["BOS", "CHOCH"]
    direction: Literal["BULLISH", "BEARISH"]
    broken_swing_price: float


def find_swings(df: pd.DataFrame, confirm_bars: int = 3) -> List[Swing]:
    """Causal fractal swing detection. A bar at position i is a swing high
    if its high is the max over [i-confirm_bars, i+confirm_bars]; that fact
    is only KNOWABLE at position i+confirm_bars (once the trailing bars
    exist), which is recorded as confirmed_at_pos."""
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    n = len(df)
    swings: List[Swing] = []
    last_high = None
    last_low = None

    for i in range(confirm_bars, n - confirm_bars):
        window_h = highs[i - confirm_bars : i + confirm_bars + 1]
        window_l = lows[i - confirm_bars : i + confirm_bars + 1]
        confirmed_at = i + confirm_bars

        if highs[i] == window_h.max() and np.argmax(window_h) == confirm_bars:
            label = ""
            if last_high is not None:
                label = "HH" if highs[i] > last_high.price else "LH"
            swing = Swing(i, df.index[i], float(highs[i]), "HIGH", label, confirmed_at)
            swings.append(swing)
            last_high = swing

        if lows[i] == window_l.min() and np.argmin(window_l) == confirm_bars:
            label = ""
            if last_low is not None:
                label = "HL" if lows[i] > last_low.price else "LL"
            swing = Swing(i, df.index[i], float(lows[i]), "LOW", label, confirmed_at)
            swings.append(swing)
            last_low = swing

    swings.sort(key=lambda s: s.confirmed_at_pos)
    return swings


def find_structure_events(df: pd.DataFrame, confirm_bars: int = 3) -> List[StructureEvent]:
    """Walk forward bar-by-bar (causal). At each bar, check whether the
    CLOSE breaks the most recently CONFIRMED opposite-type swing extreme
    known as of that bar. Prevailing bias starts NEUTRAL and flips on each
    break; the direction of a break relative to the current bias determines
    BOS (same direction) vs CHOCH (opposite direction)."""
    swings = find_swings(df, confirm_bars)
    closes = df["close"].to_numpy()
    n = len(df)

    # swings become usable only once confirmed; index them by confirmed_at_pos
    swings_by_confirm: dict[int, List[Swing]] = {}
    for s in swings:
        swings_by_confirm.setdefault(s.confirmed_at_pos, []).append(s)

    events: List[StructureEvent] = []
    latest_high: Swing | None = None
    latest_low: Swing | None = None
    bias: str | None = None  # "BULLISH" / "BEARISH"
    broken_high_price = None
    broken_low_price = None

    for i in range(n):
        for s in swings_by_confirm.get(i, []):
            if s.kind == "HIGH":
                latest_high = s
            else:
                latest_low = s

        if latest_high is not None and closes[i] > latest_high.price and latest_high.price != broken_high_price:
            direction = "BULLISH"
            kind = "BOS" if bias == "BULLISH" else "CHOCH"
            events.append(StructureEvent(i, df.index[i], kind, direction, latest_high.price))
            broken_high_price = latest_high.price
            bias = "BULLISH"

        if latest_low is not None and closes[i] < latest_low.price and latest_low.price != broken_low_price:
            direction = "BEARISH"
            kind = "BOS" if bias == "BEARISH" else "CHOCH"
            events.append(StructureEvent(i, df.index[i], kind, direction, latest_low.price))
            broken_low_price = latest_low.price
            bias = "BEARISH"

    events.sort(key=lambda e: e.index_pos)
    return events


if __name__ == "__main__":
    from research.data.synthetic import generate_multi_symbol_dataset

    ds = generate_multi_symbol_dataset(["EURUSD"], n_days=30)
    m15 = ds["EURUSD"].bars.resample("15min").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}
    ).dropna()

    swings = find_swings(m15, confirm_bars=3)
    print(f"{len(swings)} swings found")
    for s in swings[:5]:
        print(s)
    # causality check: confirmed_at_pos must strictly exceed index_pos
    assert all(s.confirmed_at_pos > s.index_pos for s in swings)

    events = find_structure_events(m15, confirm_bars=3)
    print(f"{len(events)} structure events found")
    from collections import Counter

    print(Counter((e.kind, e.direction) for e in events))
    print("OK")
