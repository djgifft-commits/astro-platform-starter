"""
Phase 19 — Liquidity intelligence.

HARD CONSTRAINT (MASTER COMMAND absolute rules 8/9): this project has no
access to real broker order-book, iceberg, or resting-stop data. Every
value produced here is a geometric ESTIMATE derived from swing
highs/lows and round numbers, not a measurement of real liquidity.
Every public function and output column is labeled accordingly, and nothing
in this module may be described as detecting real stop orders or iceberg
orders.
"""
from __future__ import annotations

import dataclasses
from typing import List, Literal

import numpy as np
import pandas as pd

from research.core.structure import Swing, find_swings

LIQUIDITY_LABEL = "ESTIMATED_STOP_LIQUIDITY"
ICEBERG_LABEL = "ICEBERG_DATA_UNAVAILABLE"


@dataclasses.dataclass
class LiquidityPool:
    price: float
    kind: Literal["BSL", "SSL"]  # buy-side (above swing highs) / sell-side (below swing lows)
    source_swing_pos: int
    label: str = LIQUIDITY_LABEL


@dataclasses.dataclass
class LiquiditySweep:
    pool: LiquidityPool
    sweep_pos: int
    sweep_ts: pd.Timestamp
    reversal_persistence_bars: int  # consecutive bars after the sweep that close back on the origin side
    label: str = LIQUIDITY_LABEL


def estimate_liquidity_pools(df: pd.DataFrame, confirm_bars: int = 3) -> List[LiquidityPool]:
    """ESTIMATED_STOP_LIQUIDITY: treats each confirmed swing high/low as a
    plausible resting-stop cluster (retail stops are commonly placed just
    beyond recent swing extremes). This is a geometric heuristic, not a
    measurement of actual resting orders."""
    swings = find_swings(df, confirm_bars=confirm_bars)
    pools = []
    for s in swings:
        kind = "BSL" if s.kind == "HIGH" else "SSL"
        pools.append(LiquidityPool(price=s.price, kind=kind, source_swing_pos=s.index_pos))
    return pools


def detect_sweeps(df: pd.DataFrame, pools: List[LiquidityPool], reversal_check_bars: int = 10) -> List[LiquiditySweep]:
    """A sweep = price wicks beyond a pool level intrabar but the bar's
    CLOSE remains on the origin side (classic 'stop hunt' geometry).
    Reports whether price reversed (closed back beyond the pool on the
    origin side) within `reversal_check_bars`."""
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    closes = df["close"].to_numpy()
    n = len(df)
    sweeps = []

    for pool in pools:
        start = pool.source_swing_pos + 1
        if start >= n:
            continue
        for i in range(start, n):
            if pool.kind == "BSL" and highs[i] > pool.price and closes[i] < pool.price:
                # sweep bar already closes back below the pool by definition; measure
                # how many additional bars price stays below it (persistence of reversal)
                persistence = 0
                for k in range(i + 1, min(n, i + 1 + reversal_check_bars)):
                    if closes[k] < pool.price:
                        persistence += 1
                    else:
                        break
                sweeps.append(LiquiditySweep(pool, i, df.index[i], persistence))
                break
            if pool.kind == "SSL" and lows[i] < pool.price and closes[i] > pool.price:
                persistence = 0
                for k in range(i + 1, min(n, i + 1 + reversal_check_bars)):
                    if closes[k] > pool.price:
                        persistence += 1
                    else:
                        break
                sweeps.append(LiquiditySweep(pool, i, df.index[i], persistence))
                break
    return sweeps


if __name__ == "__main__":
    from research.data.synthetic import generate_multi_symbol_dataset

    ds = generate_multi_symbol_dataset(["EURUSD"], n_days=30)
    m15 = ds["EURUSD"].bars.resample("15min").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}
    ).dropna()

    pools = estimate_liquidity_pools(m15)
    print(f"{len(pools)} {LIQUIDITY_LABEL} pools")
    sweeps = detect_sweeps(m15, pools)
    print(f"{len(sweeps)} sweeps detected (label={LIQUIDITY_LABEL})")
    assert all(p.label == LIQUIDITY_LABEL for p in pools)
    print("OK -", ICEBERG_LABEL, "- no iceberg detection implemented, by design.")
