"""
Strategy B — SMC Structure Continuation.

HTF bias + BOS (continuation break, research/core/structure.py) + a
preceding ESTIMATED_STOP_LIQUIDITY sweep + displacement (significant
impulse) + retracement into the broken level (treated as the POI) +
execution-timeframe confirmation candle as the entry trigger.
"""
from __future__ import annotations

from typing import List, Tuple

import pandas as pd

from research.strategies.base import RejectedCandidate, Signal, Strategy, run_checklist, row_asof, window_after

LOOKBACK_BARS_FOR_CONTEXT = 40  # ~3h20m on M5, used to look for preceding sweep/displacement
CONFIRM_WINDOW_BARS = 16
RETEST_BUFFER_ATR_MULT = 0.25
BULLISH_CONFIRM_PATTERNS = ["bullish_engulfing", "hammer", "pin_bar", "morning_star"]
BEARISH_CONFIRM_PATTERNS = ["bearish_engulfing", "shooting_star", "pin_bar", "evening_star"]
BIAS_LONG = {"LONG", "STRONG_LONG"}
BIAS_SHORT = {"SHORT", "STRONG_SHORT"}


class StructureContinuation(Strategy):
    name = "structure_continuation"
    variant = "default"

    def scan(self, ctx) -> Tuple[List[Signal], List[RejectedCandidate]]:
        exec_df = ctx.frames[ctx.execution_tf]
        fb = ctx.feature_bars
        signals: List[Signal] = []
        rejected: List[RejectedCandidate] = []

        bos_events = [e for e in ctx.structure_events if e.kind == "BOS"]
        for event in bos_events:
            direction = "LONG" if event.direction == "BULLISH" else "SHORT"
            bias_row = row_asof(fb, event.timestamp)
            target_bias = BIAS_LONG if direction == "LONG" else BIAS_SHORT

            lookback_start = event.timestamp - pd.Timedelta(minutes=15 * LOOKBACK_BARS_FOR_CONTEXT)
            sweep_dir_needed = "LONG" if direction == "LONG" else "SHORT"
            preceding_sweep = any(
                s.sweep_ts <= event.timestamp and s.sweep_ts >= lookback_start
                and ((direction == "LONG" and s.pool.kind == "SSL") or (direction == "SHORT" and s.pool.kind == "BSL"))
                for s in ctx.liquidity_sweeps
            )
            preceding_displacement = any(
                imp.end_ts <= event.timestamp and imp.end_ts >= lookback_start
                and ((direction == "LONG" and imp.direction == "UP") or (direction == "SHORT" and imp.direction == "DOWN"))
                for imp in ctx.impulses
            )

            checks = [
                ("bias_available", bias_row is not None, ""),
                ("htf_bias_aligned", bool(bias_row is not None and bias_row["bias_bias"] in target_bias), f"must be in {target_bias}"),
                ("liquidity_sweep_precedes_bos", preceding_sweep, f"{sweep_dir_needed}-side sweep within lookback"),
                ("displacement_precedes_bos", preceding_displacement, "significant same-direction impulse within lookback"),
            ]
            ok, checklist, first_fail = run_checklist(checks)
            if not ok:
                rejected.append(RejectedCandidate(self.name, self.variant, ctx.symbol, event.timestamp,
                                                    "SETUP_FORMING", first_fail, checklist))
                continue

            atr_row = ctx.atr_series.asof(event.timestamp)
            buffer = (atr_row if pd.notna(atr_row) else 0) * RETEST_BUFFER_ATR_MULT
            poi = event.broken_swing_price
            window = window_after(exec_df, event.timestamp, CONFIRM_WINDOW_BARS)

            entered = False
            for ts, row in window.iterrows():
                touched_poi = (row["low"] <= poi + buffer) if direction == "LONG" else (row["high"] >= poi - buffer)
                if not touched_poi:
                    continue
                if ts not in ctx.patterns.index:
                    continue
                prow = ctx.patterns.loc[ts]
                confirm_set = BULLISH_CONFIRM_PATTERNS if direction == "LONG" else BEARISH_CONFIRM_PATTERNS
                hit = [p for p in confirm_set if prow.get(p, False)]
                resumed = (row["close"] > poi) if direction == "LONG" else (row["close"] < poi)
                if hit and resumed:
                    signals.append(Signal(
                        strategy=self.name, variant=self.variant, symbol=ctx.symbol, direction=direction,
                        entry_ts=ts, entry_price=float(row["close"]),
                        setup_reason=f"BOS + liquidity sweep + displacement + retest of broken level + {hit[0]}",
                        rules_passed=[c.name for c in checklist], rules_failed=[],
                        market_condition=str(bias_row["regime_regime"]), directional_bias=str(bias_row["bias_bias"]),
                        candle_pattern=hit[0], fib_state=None, liquidity_state="ESTIMATED_STOP_LIQUIDITY_SWEPT",
                        displacement_state="CONFIRMED",
                        meta={"bos_ts": str(event.timestamp), "broken_level": poi},
                    ))
                    entered = True
                    break
            if not entered:
                rejected.append(RejectedCandidate(self.name, self.variant, ctx.symbol, event.timestamp,
                                                    "CONFIRMATION_PENDING", "no_retest_confirmation_within_window", checklist))
        return signals, rejected


if __name__ == "__main__":
    from research.core.feature_bar import build_symbol_engine_data
    from research.data.synthetic import generate_multi_symbol_dataset

    ds = generate_multi_symbol_dataset(["EURUSD"], n_days=240)
    data = build_symbol_engine_data("EURUSD", ds["EURUSD"].bars)
    strat = StructureContinuation()
    signals, rejected = strat.scan(data)
    print(f"{len(signals)} signals, {len(rejected)} rejected")
    if signals:
        print(signals[0])
    print("OK")
