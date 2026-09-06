"""
Phase 9D — Protected highs/lows and internal/external structure.

Reuses research/core/structure.py's `find_swings` / `find_structure_events`
entirely — this module adds a naming/aggregation layer on top, no new
swing- or BOS/CHOCH-detection logic, per Phase 9's explicit instruction
not to duplicate market-structure implementations.

Definitions (mechanical, causal):
- EXTERNAL structure: swings computed with a LARGER `confirm_bars` window
  (major swings) -- the broader structure a smaller countertrend move
  would not invalidate.
- INTERNAL structure: swings computed with the STANDARD (smaller)
  `confirm_bars` window already used elsewhere in this project -- minor
  swings within the external trend.
- PROTECTED LOW: in a bullish external structure, the most recent
  confirmed swing low that must hold (not be closed below) for the
  bullish structure to remain valid -- the low that preceded the most
  recent bullish BOS/CHOCH. Breaking it is definitionally a bearish
  CHOCH on that same swing set.
- PROTECTED HIGH: the symmetric case for bearish external structure.
"""
from __future__ import annotations

import dataclasses
from typing import List, Optional

import pandas as pd

from research.core.structure import Swing, StructureEvent, find_structure_events, find_swings

EXTERNAL_CONFIRM_BARS = 8
INTERNAL_CONFIRM_BARS = 3


@dataclasses.dataclass
class StructureLayers:
    external_swings: List[Swing]
    external_events: List[StructureEvent]
    internal_swings: List[Swing]
    internal_events: List[StructureEvent]


def compute_structure_layers(
    df: pd.DataFrame,
    external_confirm_bars: int = EXTERNAL_CONFIRM_BARS,
    internal_confirm_bars: int = INTERNAL_CONFIRM_BARS,
) -> StructureLayers:
    return StructureLayers(
        external_swings=find_swings(df, confirm_bars=external_confirm_bars),
        external_events=find_structure_events(df, confirm_bars=external_confirm_bars),
        internal_swings=find_swings(df, confirm_bars=internal_confirm_bars),
        internal_events=find_structure_events(df, confirm_bars=internal_confirm_bars),
    )


def compute_protected_levels(df: pd.DataFrame, events: List[StructureEvent], swings: List[Swing]) -> pd.DataFrame:
    """Causal per-bar protected_high / protected_low series. At bar i, the
    value reflects only events/swings confirmed at or before i."""
    n = len(df)
    protected_high = pd.Series(float("nan"), index=df.index)
    protected_low = pd.Series(float("nan"), index=df.index)

    swings_by_confirm: dict[int, List[Swing]] = {}
    for s in swings:
        swings_by_confirm.setdefault(s.confirmed_at_pos, []).append(s)

    events_by_pos: dict[int, List[StructureEvent]] = {}
    for e in events:
        events_by_pos.setdefault(e.index_pos, []).append(e)

    latest_high: Optional[Swing] = None
    latest_low: Optional[Swing] = None
    cur_protected_high = float("nan")
    cur_protected_low = float("nan")
    bias = "NEUTRAL"

    for i in range(n):
        for s in swings_by_confirm.get(i, []):
            if s.kind == "HIGH":
                latest_high = s
            else:
                latest_low = s

        for e in events_by_pos.get(i, []):
            if e.direction == "BULLISH":
                bias = "BULLISH"
                if latest_low is not None:
                    cur_protected_low = latest_low.price
            else:
                bias = "BEARISH"
                if latest_high is not None:
                    cur_protected_high = latest_high.price

        protected_high.iloc[i] = cur_protected_high if bias == "BEARISH" else float("nan")
        protected_low.iloc[i] = cur_protected_low if bias == "BULLISH" else float("nan")

    return pd.DataFrame({"protected_high": protected_high, "protected_low": protected_low}, index=df.index)


if __name__ == "__main__":
    from research.data.synthetic import generate_multi_symbol_dataset

    ds = generate_multi_symbol_dataset(["EURUSD"], n_days=60)
    m5 = ds["EURUSD"].bars.resample("5min").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}
    ).dropna()

    layers = compute_structure_layers(m5)
    print(f"external: {len(layers.external_swings)} swings, {len(layers.external_events)} events")
    print(f"internal: {len(layers.internal_swings)} swings, {len(layers.internal_events)} events")
    assert len(layers.internal_swings) >= len(layers.external_swings), "smaller confirm_bars must find >= swings"

    protected = compute_protected_levels(m5, layers.external_events, layers.external_swings)
    print(protected.dropna(how="all").head(10))

    # causality: protected level at bar i must never reference a swing/event
    # confirmed after i (spot-check via truncated recompute)
    cutoff = 300
    layers_trunc = compute_structure_layers(m5.iloc[:cutoff])
    protected_trunc = compute_protected_levels(m5.iloc[:cutoff], layers_trunc.external_events, layers_trunc.external_swings)
    common = protected.index[:cutoff - EXTERNAL_CONFIRM_BARS - 5]
    mism_high = (protected.loc[common, "protected_high"].fillna(-1) != protected_trunc.loc[common, "protected_high"].fillna(-1)).sum()
    mism_low = (protected.loc[common, "protected_low"].fillna(-1) != protected_trunc.loc[common, "protected_low"].fillna(-1)).sum()
    print("mismatches (should be 0):", mism_high, mism_low)
    assert mism_high == 0 and mism_low == 0
    print("OK")
