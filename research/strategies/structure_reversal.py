"""
Strategy C — Structure Reversal.

Requires measurable evidence for a reversal, not just a countertrend move:
an ESTIMATED_STOP_LIQUIDITY sweep, opposite-direction displacement, a
CHOCH/MSS event (research/core/structure.py), and a retest/POI reaction
as the entry trigger.
"""
from __future__ import annotations

from typing import List, Tuple

import pandas as pd

from research.strategies.base import RejectedCandidate, Signal, Strategy, run_checklist, row_asof, window_after

LOOKBACK_BARS_FOR_CONTEXT = 40
CONFIRM_WINDOW_BARS = 16
RETEST_BUFFER_ATR_MULT = 0.25
BULLISH_CONFIRM_PATTERNS = ["bullish_engulfing", "hammer", "pin_bar", "morning_star", "dragonfly_doji"]
BEARISH_CONFIRM_PATTERNS = ["bearish_engulfing", "shooting_star", "pin_bar", "evening_star", "gravestone_doji"]


class StructureReversal(Strategy):
    name = "structure_reversal"
    variant = "default"

    def scan(self, ctx) -> Tuple[List[Signal], List[RejectedCandidate]]:
        exec_df = ctx.frames[ctx.execution_tf]
        signals: List[Signal] = []
        rejected: List[RejectedCandidate] = []

        choch_events = [e for e in ctx.structure_events if e.kind == "CHOCH"]
        for event in choch_events:
            direction = "LONG" if event.direction == "BULLISH" else "SHORT"
            lookback_start = event.timestamp - pd.Timedelta(minutes=15 * LOOKBACK_BARS_FOR_CONTEXT)

            # a reversal to the upside should be preceded by a SELL-side liquidity sweep
            # (stops below a prior low swept, then price reverses up) and vice versa
            required_pool = "SSL" if direction == "LONG" else "BSL"
            preceding_sweep = any(
                lookback_start <= s.sweep_ts <= event.timestamp and s.pool.kind == required_pool
                for s in ctx.liquidity_sweeps
            )
            opposite_displacement = any(
                lookback_start <= imp.end_ts <= event.timestamp
                and ((direction == "LONG" and imp.direction == "UP") or (direction == "SHORT" and imp.direction == "DOWN"))
                for imp in ctx.impulses
            )

            checks = [
                ("liquidity_sweep_precedes_choch", preceding_sweep, f"{required_pool} sweep within lookback"),
                ("reversal_displacement_present", opposite_displacement, "impulse in the NEW direction within lookback"),
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
                    feature_row = row_asof(ctx.feature_bars, ts)
                    market_condition = str(feature_row["regime_regime"]) if feature_row is not None else ""
                    signals.append(Signal(
                        strategy=self.name, variant=self.variant, symbol=ctx.symbol, direction=direction,
                        entry_ts=ts, entry_price=float(row["close"]),
                        setup_reason=f"Liquidity sweep + opposite displacement + CHOCH + retest + {hit[0]}",
                        rules_passed=[c.name for c in checklist], rules_failed=[],
                        market_condition=market_condition, directional_bias=direction,
                        candle_pattern=hit[0], fib_state=None, liquidity_state="ESTIMATED_STOP_LIQUIDITY_SWEPT",
                        displacement_state="CONFIRMED",
                        meta={"choch_ts": str(event.timestamp), "broken_level": poi},
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
    strat = StructureReversal()
    signals, rejected = strat.scan(data)
    print(f"{len(signals)} signals, {len(rejected)} rejected")
    if signals:
        print(signals[0])
    print("OK")
