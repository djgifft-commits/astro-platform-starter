"""
Assembles the per-symbol, per-execution-bar causal feature stream that
strategies and the backtest engine consume. This is the "engine" referred
to throughout the MASTER COMMAND: built once per (symbol, config), reused
by every strategy, rather than each strategy recomputing its own
approximate copy of regime/structure/bias.

Every column here is causal: a row at timestamp T is computed using only
information available at or before T (enforced by construction in each
underlying module, and spot-checked in each module's own __main__ test).
"""
from __future__ import annotations

import dataclasses

import pandas as pd

from research.core.atr import atr
from research.core.bias import compute_bias_series
from research.core.candle_anatomy import compute_anatomy, recognize_patterns
from research.core.fibonacci import evaluate_retracements, find_impulses
from research.core.liquidity import detect_sweeps, estimate_liquidity_pools
from research.core.regime import classify_regime, compute_regime_features
from research.core.sessions import classify_session, compute_ny_opening_ranges
from research.core.structure import find_structure_events, find_swings
from research.data.loaders import resample_all


@dataclasses.dataclass
class SymbolEngineData:
    symbol: str
    execution_tf: str
    frames: dict  # {tf: OHLC df}
    feature_bars: pd.DataFrame  # merged causal features on execution_tf index
    atr_series: pd.Series
    anatomy: pd.DataFrame
    patterns: pd.DataFrame
    opening_ranges: list
    structure_events: list
    swings: list
    liquidity_pools: list
    liquidity_sweeps: list
    impulses: list
    retracement_outcomes: list


def _asof_merge_regime(regime_df: pd.DataFrame, target_index: pd.DatetimeIndex) -> pd.DataFrame:
    r = regime_df.reindex(regime_df.index.union(target_index)).ffill()
    return r.reindex(target_index)


def build_symbol_engine_data(
    symbol: str,
    m1: pd.DataFrame,
    execution_tf: str = "M5",
    regime_tf: str = "H1",
    fib_tf: str = "M15",
    atr_period: int = 14,
    structure_confirm_bars: int = 3,
) -> SymbolEngineData:
    frames = resample_all(m1, ("M5", "M15", "M30", "H1", "H4", "D1"))
    frames["M1"] = m1
    exec_df = frames[execution_tf]

    a = atr(exec_df, atr_period)
    anatomy = compute_anatomy(exec_df, atr_period)
    patterns = recognize_patterns(exec_df, anatomy)

    regime_feats = compute_regime_features(frames[regime_tf], structure_confirm_bars=structure_confirm_bars)
    regime_state = classify_regime(regime_feats)
    regime_on_exec = _asof_merge_regime(regime_state, exec_df.index)

    bias_series = compute_bias_series(
        {tf: frames[tf] for tf in ("M5", "M15", "M30", "H1", "H4", "D1") if len(frames[tf]) > 20},
        confirm_bars=structure_confirm_bars,
    )
    bias_on_exec = _asof_merge_regime(bias_series, exec_df.index)

    session = classify_session(exec_df.index)

    opening_ranges = compute_ny_opening_ranges(m1)
    structure_events = find_structure_events(exec_df, confirm_bars=structure_confirm_bars)
    swings = find_swings(exec_df, confirm_bars=structure_confirm_bars)
    liquidity_pools = estimate_liquidity_pools(frames[fib_tf], confirm_bars=structure_confirm_bars)
    liquidity_sweeps = detect_sweeps(frames[fib_tf], liquidity_pools)
    fib_atr = atr(frames[fib_tf], atr_period)
    impulses = find_impulses(frames[fib_tf], fib_atr)
    retracement_outcomes = evaluate_retracements(frames[fib_tf], impulses, fib_atr)

    feature_bars = pd.concat(
        [
            regime_on_exec.add_prefix("regime_"),
            bias_on_exec.add_prefix("bias_"),
            pd.DataFrame({"session": session}),
            pd.DataFrame({"atr": a}),
        ],
        axis=1,
    )

    return SymbolEngineData(
        symbol=symbol,
        execution_tf=execution_tf,
        frames=frames,
        feature_bars=feature_bars,
        atr_series=a,
        anatomy=anatomy,
        patterns=patterns,
        opening_ranges=opening_ranges,
        structure_events=structure_events,
        swings=swings,
        liquidity_pools=liquidity_pools,
        liquidity_sweeps=liquidity_sweeps,
        impulses=impulses,
        retracement_outcomes=retracement_outcomes,
    )


if __name__ == "__main__":
    from research.data.synthetic import generate_multi_symbol_dataset

    ds = generate_multi_symbol_dataset(["EURUSD"], n_days=60)
    data = build_symbol_engine_data("EURUSD", ds["EURUSD"].bars)
    print(data.feature_bars.tail())
    print(data.feature_bars["regime_regime"].value_counts())
    print(data.feature_bars["bias_bias"].value_counts())
    assert len(data.feature_bars) == len(data.frames["M5"])
    print("OK")
