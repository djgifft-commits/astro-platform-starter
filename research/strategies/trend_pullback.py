"""
Strategy D — Trend Pullback.

Strong trend (Phase 3 regime) + significant impulse (Phase 7 impulse
detector, on the fib_tf frame) + controlled retracement (structure
preserved, depth in a plausible continuation band) + a confirmation
candle (Phase 6 pattern) as the entry trigger.
"""
from __future__ import annotations

from typing import List, Tuple

import pandas as pd

from research.strategies.base import RejectedCandidate, Signal, Strategy, run_checklist, row_asof, window_after

TREND_REGIMES_LONG = {"UP_TREND", "STRONG_UPTREND"}
TREND_REGIMES_SHORT = {"DOWN_TREND", "STRONG_DOWNTREND"}
CONFIRM_WINDOW_BARS = 12
BULLISH_CONFIRM_PATTERNS = ["bullish_engulfing", "hammer", "pin_bar", "morning_star", "three_white_soldiers"]
BEARISH_CONFIRM_PATTERNS = ["bearish_engulfing", "shooting_star", "pin_bar", "evening_star", "three_black_crows"]


class TrendPullback(Strategy):
    name = "trend_pullback"
    variant = "default"

    def __init__(self, min_depth: float = 0.30, max_depth: float = 0.65, min_persistence: float = 0.55):
        self.min_depth = min_depth
        self.max_depth = max_depth
        self.min_persistence = min_persistence

    def scan(self, ctx) -> Tuple[List[Signal], List[RejectedCandidate]]:
        exec_df = ctx.frames[ctx.execution_tf]
        fb = ctx.feature_bars
        signals: List[Signal] = []
        rejected: List[RejectedCandidate] = []

        for outcome in ctx.retracement_outcomes:
            if not (self.min_depth <= outcome.level <= self.max_depth):
                continue
            imp = outcome.impulse
            trend_direction = "LONG" if imp.direction == "UP" else "SHORT"
            target_regimes = TREND_REGIMES_LONG if trend_direction == "LONG" else TREND_REGIMES_SHORT

            regime_row = row_asof(fb, imp.end_ts)

            checks = [
                ("regime_available", regime_row is not None, "regime feature available at impulse end"),
                ("trend_regime_matches", bool(regime_row is not None and regime_row["regime_regime"] in target_regimes),
                 f"regime must be one of {target_regimes}"),
                ("trend_persistence_sufficient", bool(regime_row is not None and regime_row["regime_trend_persistence"] >= self.min_persistence),
                 f">= {self.min_persistence}"),
                ("retracement_touched", outcome.touched, "price must actually reach the retracement zone"),
                ("structure_preserved", outcome.structure_preserved, "impulse origin must not be violated during retracement"),
            ]
            ok, checklist, first_fail = run_checklist(checks)
            if not ok:
                rejected.append(RejectedCandidate(self.name, self.variant, ctx.symbol, imp.end_ts,
                                                    "SETUP_FORMING", first_fail, checklist))
                continue

            # locate confirmation window on execution_tf starting at the retracement touch
            fib_frame_index = ctx.frames.get("M15", exec_df).index
            touch_pos_fib = outcome.touch_pos
            if touch_pos_fib is None:
                rejected.append(RejectedCandidate(self.name, self.variant, ctx.symbol, imp.end_ts,
                                                    "CONFIRMATION_PENDING", "retracement_touched_flag_inconsistent", checklist))
                continue
            touch_ts_actual = fib_frame_index[touch_pos_fib]
            window = window_after(exec_df, touch_ts_actual, CONFIRM_WINDOW_BARS)
            confirm_patterns = BULLISH_CONFIRM_PATTERNS if trend_direction == "LONG" else BEARISH_CONFIRM_PATTERNS

            entered = False
            for ts, row in window.iterrows():
                pattern_row = ctx.patterns.loc[ts] if ts in ctx.patterns.index else None
                if pattern_row is None:
                    continue
                hit = [p for p in confirm_patterns if pattern_row.get(p, False)]
                if hit:
                    signals.append(Signal(
                        strategy=self.name, variant=self.variant, symbol=ctx.symbol, direction=trend_direction,
                        entry_ts=ts, entry_price=float(row["close"]),
                        setup_reason=f"Trend pullback to {outcome.level:.3f} retracement + {hit[0]} confirmation",
                        rules_passed=[c.name for c in checklist],
                        rules_failed=[],
                        market_condition=str(regime_row["regime_regime"]), directional_bias=str(regime_row.get("bias_bias", "")),
                        candle_pattern=hit[0], fib_state=f"level_{outcome.level}", liquidity_state=None,
                        displacement_state=f"impulse_size_atr_mult={imp.size:.5f}",
                        meta={"retracement_level": outcome.level, "impulse_start": str(imp.start_ts), "impulse_end": str(imp.end_ts),
                              "impulse_start_price": imp.start_price, "impulse_end_price": imp.end_price},
                    ))
                    entered = True
                    break
            if not entered:
                rejected.append(RejectedCandidate(self.name, self.variant, ctx.symbol, touch_ts_actual,
                                                    "CONFIRMATION_PENDING", "no_confirmation_candle_within_window", checklist))
        return signals, rejected


if __name__ == "__main__":
    from research.core.feature_bar import build_symbol_engine_data
    from research.data.synthetic import generate_multi_symbol_dataset

    ds = generate_multi_symbol_dataset(["EURUSD"], n_days=90)
    data = build_symbol_engine_data("EURUSD", ds["EURUSD"].bars)
    strat = TrendPullback()
    signals, rejected = strat.scan(data)
    print(f"{len(signals)} signals, {len(rejected)} rejected")
    if signals:
        print(signals[0])
    print("OK")
