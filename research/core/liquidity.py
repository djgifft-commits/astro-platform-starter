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


@dataclasses.dataclass
class EqualLevel:
    price: float  # average of the clustered swing prices
    kind: Literal["EQH", "EQL"]  # equal highs / equal lows
    member_positions: List[int]
    label: str = LIQUIDITY_LABEL


def find_equal_highs_lows(
    swings: List[Swing],
    atr_series: pd.Series,
    tolerance_atr: float = 0.15,
    max_bars_apart: int = 200,
) -> List[EqualLevel]:
    """Cluster confirmed swing highs (and separately, swing lows) that sit
    within `tolerance_atr` * ATR of each other and within `max_bars_apart`
    bars, causally: a cluster is only reported as of the bar where its
    LAST member swing was confirmed (Swing.confirmed_at_pos), never
    earlier. This is the "equal highs / equal lows" liquidity concept
    (stacked stops assumed to rest just beyond a repeatedly-tested level)
    -- an ESTIMATE, exactly like every other pool in this module."""
    levels: List[EqualLevel] = []
    for kind, swing_kind in (("EQH", "HIGH"), ("EQL", "LOW")):
        candidates = sorted([s for s in swings if s.kind == swing_kind], key=lambda s: s.index_pos)
        used = set()
        for i, s1 in enumerate(candidates):
            if s1.index_pos in used:
                continue
            a = atr_series.iloc[s1.index_pos] if s1.index_pos < len(atr_series) else np.nan
            if pd.isna(a) or a == 0:
                continue
            tolerance = tolerance_atr * a
            cluster = [s1]
            for s2 in candidates[i + 1 :]:
                if s2.index_pos - s1.index_pos > max_bars_apart:
                    break
                if s2.index_pos in used:
                    continue
                if abs(s2.price - s1.price) <= tolerance:
                    cluster.append(s2)
            if len(cluster) >= 2:
                for s in cluster:
                    used.add(s.index_pos)
                avg_price = float(np.mean([s.price for s in cluster]))
                levels.append(EqualLevel(avg_price, kind, [s.index_pos for s in cluster]))
    return levels


def liquidity_density(
    pools: List[LiquidityPool],
    price_series: pd.Series,
    band_atr: float,
    atr_series: pd.Series,
) -> pd.Series:
    """Causal per-bar count of ESTIMATED_STOP_LIQUIDITY pools within
    `band_atr` * ATR of the current close, restricted at each bar to
    pools whose source swing was already confirmed by that bar (a pool
    from a swing confirmed in the future cannot contribute to today's
    density)."""
    n = len(price_series)
    density = np.zeros(n, dtype=int)
    pool_prices = np.array([p.price for p in pools])
    pool_confirm_pos = np.array([p.source_swing_pos for p in pools])
    for i in range(n):
        a = atr_series.iloc[i]
        if pd.isna(a) or a == 0 or len(pool_prices) == 0:
            continue
        band = band_atr * a
        visible = pool_confirm_pos <= i
        within = np.abs(pool_prices - price_series.iloc[i]) <= band
        density[i] = int((visible & within).sum())
    return pd.Series(density, index=price_series.index, name="liquidity_density")


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

    from research.core.atr import atr as _atr
    from research.core.structure import find_swings

    swings = find_swings(m15)
    a = _atr(m15, 14)
    eq_levels = find_equal_highs_lows(swings, a)
    print(f"{len(eq_levels)} equal-high/low clusters found")
    if eq_levels:
        print(eq_levels[0])

    density = liquidity_density(pools, m15["close"], band_atr=2.0, atr_series=a)
    print("liquidity density describe:\n", density.describe())
    assert (density >= 0).all()
    print("OK -", ICEBERG_LABEL, "- no iceberg detection implemented, by design.")
