"""
Phase 22 — Economic backtest engine.

BACKTEST = REAL ENGINE FUNCTIONS + HISTORICAL(SYNTHETIC) DATA + SIMULATED
EXECUTION. This module does not reimplement strategy logic: it calls each
Strategy's `scan` (research/strategies/*), applies one named SL model
(research/risk/sl_models.py) and one named TP model
(research/risk/tp_models.py), then simulates the trade with one named exit
model (research/risk/exit_models.py). No forced trades: if a strategy
produces zero signals for a symbol/config, this reports zero trades rather
than relaxing anything to manufacture activity.

Costs: spread is deducted at entry and exit (half-spread each side against
the trader), consistent with the causal spread series generated for the
synthetic data.
"""
from __future__ import annotations

import dataclasses
from typing import List, Optional

from research.core.feature_bar import SymbolEngineData
from research.risk import sl_models, tp_models
from research.risk.exit_models import EXIT_MODELS, TradeResult, simulate_trade
from research.strategies.base import RejectedCandidate, Signal, Strategy


@dataclasses.dataclass
class BacktestConfig:
    sl_model: str = "FIXED_ATR"
    sl_atr_mult: float = 1.5
    tp_model: Optional[str] = "FIXED_2R"
    exit_model: str = "FIXED"
    apply_spread_cost: bool = True


@dataclasses.dataclass
class BacktestRun:
    symbol: str
    strategy: str
    variant: str
    config: BacktestConfig
    signals: List[Signal]
    rejected: List[RejectedCandidate]
    trades: List[TradeResult]


def _entry_pos(ctx: SymbolEngineData, ts) -> int:
    return ctx.frames[ctx.execution_tf].index.searchsorted(ts)


def apply_sl_model(model: str, signal: Signal, ctx: SymbolEngineData, atr_at_entry: float, mult: float) -> Optional[sl_models.StopLoss]:
    entry_pos = _entry_pos(ctx, signal.entry_ts)
    if model == "FIXED_ATR":
        return sl_models.fixed_atr(signal, atr_at_entry, mult)
    if model == "STRUCTURE_INVALIDATION":
        return sl_models.structure_invalidation(signal, ctx.structure_events, entry_pos)
    if model == "SWING_EXTREME":
        return sl_models.swing_extreme(signal, ctx.swings, entry_pos, atr_at_entry=atr_at_entry)
    if model == "OR_OPPOSITE_BOUNDARY":
        return sl_models.or_opposite_boundary(signal)
    if model == "VOLATILITY_ADAPTIVE":
        row = ctx.feature_bars.asof(signal.entry_ts)
        vol_state = row.get("regime_volatility_state", "NORMAL") if row is not None else "NORMAL"
        return sl_models.volatility_adaptive(signal, atr_at_entry, vol_state)
    raise ValueError(f"unknown SL model {model}")


def apply_tp_model(model: Optional[str], signal: Signal, sl: sl_models.StopLoss, ctx: SymbolEngineData, atr_at_entry: float) -> Optional[tp_models.TakeProfit]:
    if model is None:
        return None
    entry_pos = _entry_pos(ctx, signal.entry_ts)
    if model.startswith("FIXED_") and model.endswith("R"):
        r_mult = float(model[len("FIXED_"):-1])
        return tp_models.fixed_r(signal, sl.distance, r_mult)
    if model == "ATR_TARGET":
        return tp_models.atr_target(signal, atr_at_entry)
    if model == "STRUCTURE_TARGET":
        return tp_models.structure_target(signal, ctx.swings, entry_pos)
    raise ValueError(f"unknown TP model {model}")


def run_backtest(ctx: SymbolEngineData, strategy: Strategy, config: BacktestConfig) -> BacktestRun:
    signals, rejected = strategy.scan(ctx)
    exec_df = ctx.frames[ctx.execution_tf]
    trades: List[TradeResult] = []

    for sig in signals:
        atr_at_entry = ctx.atr_series.asof(sig.entry_ts)
        if atr_at_entry is None or atr_at_entry != atr_at_entry:  # NaN check without importing pandas here
            continue

        entry_price = sig.entry_price
        if config.apply_spread_cost:
            spread_row = exec_df["spread"].asof(sig.entry_ts) if "spread" in exec_df.columns else 0.0
            half_spread = (spread_row or 0.0) / 2.0
            entry_price = entry_price + half_spread if sig.direction == "LONG" else entry_price - half_spread
            sig = dataclasses.replace(sig, entry_price=entry_price)

        sl = apply_sl_model(config.sl_model, sig, ctx, atr_at_entry, config.sl_atr_mult)
        if sl is None:
            continue
        tp = apply_tp_model(config.tp_model, sig, sl, ctx, atr_at_entry)

        result = simulate_trade(
            sig, exec_df, ctx.atr_series, sl.price, config.exit_model,
            initial_tp=(tp.price if tp else None),
            structure_events=ctx.structure_events, swings=ctx.swings,
            sl_model_name=sl.model, tp_model_name=(tp.model if tp else None),
        )
        trades.append(result)

    return BacktestRun(symbol=ctx.symbol, strategy=strategy.name, variant=getattr(strategy, "variant", ""),
                        config=config, signals=signals, rejected=rejected, trades=trades)


if __name__ == "__main__":
    from research.core.feature_bar import build_symbol_engine_data
    from research.data.synthetic import generate_multi_symbol_dataset
    from research.strategies.opening_range import OpeningRangeBreakout

    ds = generate_multi_symbol_dataset(["EURUSD"], n_days=180)
    data = build_symbol_engine_data("EURUSD", ds["EURUSD"].bars)
    strat = OpeningRangeBreakout(variant="continuation")

    for exit_model in EXIT_MODELS:
        cfg = BacktestConfig(exit_model=exit_model)
        run = run_backtest(data, strat, cfg)
        rs = [t.r_multiple for t in run.trades]
        avg_r = sum(rs) / len(rs) if rs else float("nan")
        print(f"{exit_model}: {len(run.trades)} trades, avg_R={avg_r:.3f}, {len(run.rejected)} rejected candidates")
    print("OK")
