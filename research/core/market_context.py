"""
Phase 9B — MARKET_CONTEXT composite object.

Pure aggregation: every field here is read from an already-computed,
already-causal source (research/core/feature_bar.py's SymbolEngineData,
research/core/protected_levels.py, research/core/sessions.py). No new
market-structure/regime/bias/liquidity computation happens in this
module -- it exists only to bundle those existing outputs into the single
named object Phase 9B asks for, via `row_asof` (research/strategies/
base.py) so every field is read as-of the requested timestamp and never
from a later bar.
"""
from __future__ import annotations

import dataclasses
from typing import Optional

import pandas as pd

from research.strategies.base import row_asof


@dataclasses.dataclass
class MarketContext:
    symbol: str
    session: Optional[str]
    timestamp: pd.Timestamp
    timeframe: str

    htf_bias: Optional[str]
    bias_confidence: Optional[float]
    market_regime: Optional[str]
    trend_state: Optional[str]
    volatility_state: Optional[str]

    swing_structure: Optional[str]  # external structure direction (LONG/SHORT/NEUTRAL)
    internal_structure: Optional[str]  # internal structure direction
    protected_high: Optional[float]
    protected_low: Optional[float]
    last_bos_or_choch: Optional[str]  # "BOS_BULLISH" / "CHOCH_BEARISH" / None

    liquidity_state: Optional[str]  # "NONE" / "RECENT_SSL_SWEEP" / "RECENT_BSL_SWEEP"

    or_state: Optional[str]
    or_high: Optional[float]
    or_low: Optional[float]
    or_width: Optional[float]
    price_location_vs_or: Optional[str]  # "ABOVE_OR" / "INSIDE_OR" / "BELOW_OR"

    atr: Optional[float]
    spread: Optional[float]
    cost_assumption: str  # human-readable note on what cost model is in effect


def _last_structure_event_label(structure_events: list, as_of_ts: pd.Timestamp) -> Optional[str]:
    prior = [e for e in structure_events if e.timestamp <= as_of_ts]
    if not prior:
        return None
    last = prior[-1]
    return f"{last.kind}_{last.direction}"


def _liquidity_state(liquidity_sweeps: list, as_of_ts: pd.Timestamp, lookback: pd.Timedelta) -> str:
    recent = [s for s in liquidity_sweeps if as_of_ts - lookback <= s.sweep_ts <= as_of_ts]
    if not recent:
        return "NONE"
    last = recent[-1]
    return f"RECENT_{last.pool.kind}_SWEEP"


def _current_opening_range(opening_ranges: list, as_of_ts: pd.Timestamp):
    active = [o for o in opening_ranges if o.session_open_utc <= as_of_ts]
    return active[-1] if active else None


def build_market_context(
    ctx,
    as_of_ts: pd.Timestamp,
    protected_levels: pd.DataFrame,
    external_events: list,
    external_structure_direction: pd.Series,
    internal_structure_direction: pd.Series,
    cost_assumption: str = "half-spread deducted at entry and exit",
    liquidity_lookback: pd.Timedelta = pd.Timedelta(hours=4),
) -> MarketContext:
    fb_row = row_asof(ctx.feature_bars, as_of_ts)
    exec_df = ctx.frames[ctx.execution_tf]

    session = None
    if fb_row is not None and "session" in fb_row.index:
        session = str(fb_row["session"])

    or_active = _current_opening_range(ctx.opening_ranges, as_of_ts)
    or_state, or_high, or_low, or_width, price_location = None, None, None, None, None
    if or_active is not None:
        or_high, or_low = or_active.or_high, or_active.or_low
        or_width = or_active.or_range_size
        price_row = exec_df.loc[exec_df.index <= as_of_ts]
        if len(price_row):
            last_close = price_row["close"].iloc[-1]
            if last_close > or_high:
                price_location = "ABOVE_OR"
            elif last_close < or_low:
                price_location = "BELOW_OR"
            else:
                price_location = "INSIDE_OR"
        or_state = "OR_ACTIVE" if or_active.or_close_utc > as_of_ts else "OR_ESTABLISHED"

    protected_row = row_asof(protected_levels, as_of_ts)
    ext_dir_row = row_asof(pd.DataFrame({"d": external_structure_direction}), as_of_ts)
    int_dir_row = row_asof(pd.DataFrame({"d": internal_structure_direction}), as_of_ts)

    atr_val = ctx.atr_series.asof(as_of_ts) if len(ctx.atr_series) else None
    spread_val = exec_df["spread"].asof(as_of_ts) if "spread" in exec_df.columns else None

    return MarketContext(
        symbol=ctx.symbol,
        session=session,
        timestamp=as_of_ts,
        timeframe=ctx.execution_tf,
        htf_bias=str(fb_row["bias_bias"]) if fb_row is not None else None,
        bias_confidence=float(fb_row["bias_bias_confidence"]) if fb_row is not None else None,
        market_regime=str(fb_row["regime_regime"]) if fb_row is not None else None,
        trend_state=str(fb_row["regime_direction"]) if fb_row is not None else None,
        volatility_state=str(fb_row["regime_volatility_state"]) if fb_row is not None else None,
        swing_structure=str(ext_dir_row["d"]) if ext_dir_row is not None else None,
        internal_structure=str(int_dir_row["d"]) if int_dir_row is not None else None,
        protected_high=float(protected_row["protected_high"]) if protected_row is not None and pd.notna(protected_row["protected_high"]) else None,
        protected_low=float(protected_row["protected_low"]) if protected_row is not None and pd.notna(protected_row["protected_low"]) else None,
        last_bos_or_choch=_last_structure_event_label(external_events, as_of_ts),
        liquidity_state=_liquidity_state(ctx.liquidity_sweeps, as_of_ts, liquidity_lookback),
        or_state=or_state,
        or_high=or_high, or_low=or_low, or_width=or_width,
        price_location_vs_or=price_location,
        atr=float(atr_val) if atr_val is not None and pd.notna(atr_val) else None,
        spread=float(spread_val) if spread_val is not None and pd.notna(spread_val) else None,
        cost_assumption=cost_assumption,
    )


if __name__ == "__main__":
    from research.core.feature_bar import build_symbol_engine_data
    from research.core.protected_levels import compute_protected_levels, compute_structure_layers
    from research.core.regime import _current_structure_direction  # reused, not duplicated
    from research.data.synthetic import generate_multi_symbol_dataset

    ds = generate_multi_symbol_dataset(["EURUSD"], n_days=60)
    ctx = build_symbol_engine_data("EURUSD", ds["EURUSD"].bars)
    exec_df = ctx.frames[ctx.execution_tf]

    layers = compute_structure_layers(exec_df)
    protected = compute_protected_levels(exec_df, layers.external_events, layers.external_swings)
    ext_dir = _current_structure_direction(exec_df, layers.external_events)
    int_dir = _current_structure_direction(exec_df, layers.internal_events)

    sample_ts = exec_df.index[5000]
    mc = build_market_context(ctx, sample_ts, protected, layers.external_events, ext_dir, int_dir)
    print(mc)
    assert mc.timestamp == sample_ts
    assert mc.symbol == "EURUSD"
    print("OK")
