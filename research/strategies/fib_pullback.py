"""
Strategy E — Fibonacci Pullback.

Per RESEARCH_CARDS.md cards H/I, NO level is assumed superior; this class
is parameterized by `level` (any of research.core.fibonacci.FIB_LEVELS or
CONTROL_LEVELS) so the SAME strategy logic runs identically on Fibonacci
and non-Fibonacci depths, keeping the eventual comparison apples-to-apples
(Phase 21 statistical validation is what is allowed to say a level
"matters," not this module).
"""
from __future__ import annotations

from typing import List, Tuple

import research.core.fibonacci as fib
from research.strategies.base import RejectedCandidate, Signal, Strategy, run_checklist, row_asof, window_after

CONFIRM_WINDOW_BARS = 12
BULLISH_CONFIRM_PATTERNS = ["bullish_engulfing", "hammer", "pin_bar", "dragonfly_doji"]
BEARISH_CONFIRM_PATTERNS = ["bearish_engulfing", "shooting_star", "pin_bar", "gravestone_doji"]
TREND_REGIMES_LONG = {"UP_TREND", "STRONG_UPTREND", "WEAK_UPTREND"}
TREND_REGIMES_SHORT = {"DOWN_TREND", "STRONG_DOWNTREND", "WEAK_DOWNTREND"}


class FibonacciPullback(Strategy):
    name = "fib_pullback"

    def __init__(self, level: float):
        assert level in fib.FIB_LEVELS + fib.CONTROL_LEVELS
        self.level = level
        self.variant = f"level_{level}"

    def scan(self, ctx) -> Tuple[List[Signal], List[RejectedCandidate]]:
        exec_df = ctx.frames[ctx.execution_tf]
        fb = ctx.feature_bars
        fib_index = ctx.frames.get("M15", exec_df).index
        signals: List[Signal] = []
        rejected: List[RejectedCandidate] = []

        for outcome in ctx.retracement_outcomes:
            if outcome.level != self.level:
                continue
            imp = outcome.impulse
            trend_direction = "LONG" if imp.direction == "UP" else "SHORT"
            target_regimes = TREND_REGIMES_LONG if trend_direction == "LONG" else TREND_REGIMES_SHORT

            regime_row = row_asof(fb, imp.end_ts)

            checks = [
                ("regime_available", regime_row is not None, ""),
                ("regime_direction_matches", bool(regime_row is not None and regime_row["regime_regime"] in target_regimes),
                 f"must be one of {target_regimes}"),
                ("retracement_touched", outcome.touched, ""),
                ("structure_preserved", outcome.structure_preserved, ""),
            ]
            ok, checklist, first_fail = run_checklist(checks)
            if not ok:
                rejected.append(RejectedCandidate(self.name, self.variant, ctx.symbol, imp.end_ts,
                                                    "SETUP_FORMING", first_fail, checklist))
                continue

            touch_ts = fib_index[outcome.touch_pos]
            window = window_after(exec_df, touch_ts, CONFIRM_WINDOW_BARS)
            confirm_patterns = BULLISH_CONFIRM_PATTERNS if trend_direction == "LONG" else BEARISH_CONFIRM_PATTERNS

            entered = False
            for ts, row in window.iterrows():
                if ts not in ctx.patterns.index:
                    continue
                prow = ctx.patterns.loc[ts]
                hit = [p for p in confirm_patterns if prow.get(p, False)]
                if hit:
                    signals.append(Signal(
                        strategy=self.name, variant=self.variant, symbol=ctx.symbol, direction=trend_direction,
                        entry_ts=ts, entry_price=float(row["close"]),
                        setup_reason=f"Rejection at {self.level:.3f} retracement + {hit[0]}",
                        rules_passed=[c.name for c in checklist], rules_failed=[],
                        market_condition=str(regime_row["regime_regime"]), directional_bias=str(regime_row.get("bias_bias", "")),
                        candle_pattern=hit[0], fib_state=f"level_{self.level}", liquidity_state=None,
                        displacement_state=None,
                        meta={"level": self.level, "impulse_start": str(imp.start_ts), "impulse_end": str(imp.end_ts),
                              "impulse_start_price": imp.start_price, "impulse_end_price": imp.end_price,
                              "bars_to_touch": outcome.bars_to_touch, "displacement_after_atr": outcome.displacement_after},
                    ))
                    entered = True
                    break
            if not entered:
                rejected.append(RejectedCandidate(self.name, self.variant, ctx.symbol, touch_ts,
                                                    "CONFIRMATION_PENDING", "no_rejection_candle_within_window", checklist))
        return signals, rejected


if __name__ == "__main__":
    from research.core.feature_bar import build_symbol_engine_data
    from research.data.synthetic import generate_multi_symbol_dataset

    ds = generate_multi_symbol_dataset(["EURUSD"], n_days=240)
    data = build_symbol_engine_data("EURUSD", ds["EURUSD"].bars)
    for level in fib.FIB_LEVELS + fib.CONTROL_LEVELS:
        strat = FibonacciPullback(level)
        signals, rejected = strat.scan(data)
        print(f"level={level}: {len(signals)} signals / {len(signals) + len(rejected)} candidates")
    print("OK")
