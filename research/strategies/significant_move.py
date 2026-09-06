"""
Strategy F — Significant-Move Continuation.

Classifies each detected impulse (research/core/fibonacci.py's impulse
detector, run on the fib_tf frame) into STRONG / MODERATE / WEAK using
move-size/ATR, body/ATR, consecutive directional candles and close-
location-value — never candle/move size alone (MASTER COMMAND Phase 5F:
"do not equate candle size alone with strength") — then tests whether the
strength class is informative about continuation past the impulse's own
end, after a bounded retracement.
"""
from __future__ import annotations

from typing import List, Tuple

import numpy as np
import pandas as pd

from research.strategies.base import RejectedCandidate, Signal, Strategy, run_checklist, row_asof, window_after

MAX_RETRACEMENT_FOR_ENTRY = 0.5  # only proceed if pullback stayed shallower than 50% of the impulse
CONTINUATION_LOOKAHEAD_BARS = 12
CONFIRM_WINDOW_BARS = 12
BULLISH_CONFIRM_PATTERNS = ["bullish_engulfing", "hammer", "pin_bar", "marubozu"]
BEARISH_CONFIRM_PATTERNS = ["bearish_engulfing", "shooting_star", "pin_bar", "marubozu"]


def classify_move_strength(imp, fib_df: pd.DataFrame, atr_series: pd.Series) -> Tuple[str, dict]:
    a = atr_series.iloc[imp.end_pos]
    if pd.isna(a) or a == 0:
        return "UNKNOWN", {}
    seg_o = fib_df["open"].to_numpy()[imp.start_pos : imp.end_pos + 1]
    seg_h = fib_df["high"].to_numpy()[imp.start_pos : imp.end_pos + 1]
    seg_l = fib_df["low"].to_numpy()[imp.start_pos : imp.end_pos + 1]
    seg_c = fib_df["close"].to_numpy()[imp.start_pos : imp.end_pos + 1]

    body = np.abs(seg_c - seg_o)
    rng = np.where((seg_h - seg_l) == 0, np.nan, seg_h - seg_l)
    close_location = (seg_c - seg_l) / rng

    move_atr_mult = imp.size / a
    avg_body_atr = float(np.nanmean(body) / a)
    direction_sign = 1 if imp.direction == "UP" else -1
    diffs = np.diff(seg_c)
    consecutive = int((np.sign(diffs) == direction_sign).sum())
    consecutive_ratio = consecutive / max(1, len(seg_c) - 1)
    clv = float(np.nanmean(close_location)) if imp.direction == "UP" else float(np.nanmean(1 - close_location))

    score = 0
    score += int(move_atr_mult >= 3.0) + int(move_atr_mult >= 5.0)
    score += int(avg_body_atr >= 0.5)
    score += int(consecutive_ratio >= 0.65)
    score += int(clv >= 0.6)

    if score >= 4:
        strength = "STRONG_MOVE"
    elif score >= 2:
        strength = "MODERATE_MOVE"
    else:
        strength = "WEAK_MOVE"

    return strength, {
        "move_atr_mult": move_atr_mult,
        "avg_body_atr": avg_body_atr,
        "consecutive_ratio": consecutive_ratio,
        "close_location_value": float(clv),
        "score": score,
    }


class SignificantMoveContinuation(Strategy):
    name = "significant_move_continuation"

    def __init__(self, required_strength: str = "STRONG_MOVE", strength_override: dict | None = None):
        assert required_strength in ("STRONG_MOVE", "MODERATE_MOVE", "WEAK_MOVE")
        self.required_strength = required_strength
        self.variant = required_strength.lower()
        # Phase 8X negative control hook: when provided, {id(impulse): label}
        # is used INSTEAD OF classify_move_strength's real geometry-based
        # label, so a caller can test "does the strategy's apparent edge
        # depend on the REAL strength label, or would a randomly shuffled
        # label produce the same result?" without duplicating scan logic.
        self.strength_override = strength_override

    def scan(self, ctx) -> Tuple[List[Signal], List[RejectedCandidate]]:
        exec_df = ctx.frames[ctx.execution_tf]
        fib_df = ctx.frames.get("M15", exec_df)
        signals: List[Signal] = []
        rejected: List[RejectedCandidate] = []

        fib_atr = ctx.atr_series.reindex(fib_df.index).ffill()
        for imp in ctx.impulses:
            if self.strength_override is not None:
                strength = self.strength_override.get(id(imp), "UNKNOWN")
                metrics = {}
            else:
                strength, metrics = classify_move_strength(imp, fib_df, fib_atr)
            direction = "LONG" if imp.direction == "UP" else "SHORT"

            checks = [
                ("strength_classified", strength != "UNKNOWN", ""),
                ("strength_matches_required", strength == self.required_strength, f"required {self.required_strength}"),
            ]
            ok, checklist, first_fail = run_checklist(checks)
            if not ok:
                rejected.append(RejectedCandidate(self.name, self.variant, ctx.symbol, imp.end_ts,
                                                    "SETUP_FORMING", first_fail, checklist, meta=metrics))
                continue

            # CAUSALITY: pullback depth is tracked bar-by-bar using only bars
            # up to and including the bar under evaluation -- never a fixed
            # future window computed relative to imp.end_ts regardless of
            # when (or whether) a confirmation actually fires.
            window = window_after(exec_df, imp.end_ts, CONFIRM_WINDOW_BARS)
            confirm_set = BULLISH_CONFIRM_PATTERNS if direction == "LONG" else BEARISH_CONFIRM_PATTERNS
            entered = False
            invalidated = False
            running_extreme = imp.end_price
            for ts, row in window.iterrows():
                if direction == "LONG":
                    running_extreme = min(running_extreme, row["low"])
                    retracement_so_far = (imp.end_price - running_extreme) / imp.size if imp.size > 0 else 0.0
                else:
                    running_extreme = max(running_extreme, row["high"])
                    retracement_so_far = (running_extreme - imp.end_price) / imp.size if imp.size > 0 else 0.0
                if retracement_so_far > MAX_RETRACEMENT_FOR_ENTRY:
                    invalidated = True
                    break
                if ts not in ctx.patterns.index:
                    continue
                prow = ctx.patterns.loc[ts]
                hit = [p for p in confirm_set if prow.get(p, False)]
                if hit:
                    feature_row = row_asof(ctx.feature_bars, ts)
                    market_condition = str(feature_row["regime_regime"]) if feature_row is not None else ""
                    signals.append(Signal(
                        strategy=self.name, variant=self.variant, symbol=ctx.symbol, direction=direction,
                        entry_ts=ts, entry_price=float(row["close"]),
                        setup_reason=f"{strength} impulse, shallow pullback, {hit[0]} continuation confirmation",
                        rules_passed=[c.name for c in checklist], rules_failed=[],
                        market_condition=market_condition, directional_bias=direction,
                        candle_pattern=hit[0], fib_state=None, liquidity_state=None,
                        displacement_state=strength,
                        meta={**metrics, "impulse_end": str(imp.end_ts)},
                    ))
                    entered = True
                    break
            if not entered:
                reason = "pullback_exceeded_max_retracement_before_confirmation" if invalidated else "no_continuation_confirmation_within_window"
                rejected.append(RejectedCandidate(self.name, self.variant, ctx.symbol, imp.end_ts,
                                                    "CONFIRMATION_PENDING", reason, checklist, meta=metrics))
        return signals, rejected


if __name__ == "__main__":
    from research.core.feature_bar import build_symbol_engine_data
    from research.data.synthetic import generate_multi_symbol_dataset

    ds = generate_multi_symbol_dataset(["EURUSD"], n_days=240)
    data = build_symbol_engine_data("EURUSD", ds["EURUSD"].bars)
    for strength in ("STRONG_MOVE", "MODERATE_MOVE", "WEAK_MOVE"):
        strat = SignificantMoveContinuation(strength)
        signals, rejected = strat.scan(data)
        print(f"{strength}: {len(signals)} signals / {len(signals)+len(rejected)} candidates")
    print("OK")
