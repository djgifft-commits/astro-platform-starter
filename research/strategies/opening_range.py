"""
Strategy A — NY Opening Range Breakout (+ variants).

Implements a representative subset of the seven variants named in the
MASTER COMMAND: A1 (continuation), A2 (breakout + retest), A4 (failed
breakout), A5 (liquidity sweep of OR then reversal). A3 (breakout +
reversal) and A6/A7 (HTF-bias-aligned / structure-confirmed breakout) are
NOT implemented as separate variants here — A6/A7 are instead available by
running A1 with a `require_bias_alignment` / `require_structure_confirm`
flag rather than as distinct classes, and A3 is deferred entirely (it is
largely redundant with A5 under this project's definitions). This
narrowing is recorded in the audit report, per the instruction to STOP
rather than manufacture busywork variants that don't add a distinct,
testable hypothesis.

Breakout = first CLOSED M5 candle beyond OR_high/OR_low (never an intrabar
wick) unless `variant == "sweep_reversal"`, which is specifically about the
wick-only case.
"""
from __future__ import annotations

from typing import List, Tuple

import pandas as pd

from research.strategies.base import RejectedCandidate, Signal, Strategy, run_checklist, row_asof

MAX_BREAKOUT_MONITOR_BARS = 48  # ~4h on M5
MAX_CONFIRMATION_MONITOR_BARS = 24  # ~2h on M5
RETEST_BUFFER_ATR_MULT = 0.15


class OpeningRangeBreakout(Strategy):
    name = "opening_range_breakout"

    def __init__(self, variant: str = "continuation", require_bias_alignment: bool = False,
                 require_structure_confirm: bool = False):
        assert variant in ("continuation", "retest", "failed_breakout", "sweep_reversal")
        self.variant = variant
        self.require_bias_alignment = require_bias_alignment
        self.require_structure_confirm = require_structure_confirm

    def scan(self, ctx) -> Tuple[List[Signal], List[RejectedCandidate]]:
        exec_df = ctx.frames[ctx.execution_tf]
        fb = ctx.feature_bars
        signals: List[Signal] = []
        rejected: List[RejectedCandidate] = []

        for orr in ctx.opening_ranges:
            checks = [
                ("or_sufficient_data", orr.sufficient_data, f"OR window had enough bars"),
                ("or_range_positive", orr.or_range_size > 0, "OR high > OR low"),
            ]
            ok, checklist, first_fail = run_checklist(checks)
            if not ok:
                rejected.append(RejectedCandidate(self.name, self.variant, ctx.symbol, orr.or_close_utc,
                                                    "SETUP_FORMING", first_fail, checklist))
                continue

            post = exec_df.loc[exec_df.index >= orr.or_close_utc]
            post = post.iloc[: MAX_BREAKOUT_MONITOR_BARS]
            if post.empty:
                rejected.append(RejectedCandidate(self.name, self.variant, ctx.symbol, orr.or_close_utc,
                                                    "SETUP_READY", "no_post_or_data", checklist))
                continue

            breakout_pos = None
            breakout_dir = None
            sweep_pos = None
            sweep_dir = None
            for pos, (ts, row) in enumerate(post.iterrows()):
                if row["close"] > orr.or_high:
                    breakout_pos, breakout_dir = pos, "LONG"
                    break
                if row["close"] < orr.or_low:
                    breakout_pos, breakout_dir = pos, "SHORT"
                    break
                if row["high"] > orr.or_high and sweep_pos is None:
                    sweep_pos, sweep_dir = pos, "SHORT"  # swept buy-side liquidity -> bias reversal short
                if row["low"] < orr.or_low and sweep_pos is None:
                    sweep_pos, sweep_dir = pos, "LONG"

            if self.variant == "sweep_reversal":
                self._scan_sweep_reversal(ctx, orr, post, sweep_pos, sweep_dir, checklist, signals, rejected)
                continue

            if breakout_pos is None:
                rejected.append(RejectedCandidate(self.name, self.variant, ctx.symbol, orr.or_close_utc,
                                                    "CONFIRMATION_PENDING", "no_confirmed_breakout_close", checklist))
                continue

            breakout_ts = post.index[breakout_pos]
            extra_checks = list(checks)
            if self.require_bias_alignment:
                bias_row = fb.loc[fb.index <= breakout_ts].iloc[-1] if len(fb.loc[fb.index <= breakout_ts]) else None
                aligned = bias_row is not None and (
                    (breakout_dir == "LONG" and bias_row["bias_bias"] in ("LONG", "STRONG_LONG"))
                    or (breakout_dir == "SHORT" and bias_row["bias_bias"] in ("SHORT", "STRONG_SHORT"))
                )
                extra_checks.append(("htf_bias_aligned", bool(aligned), "A6: HTF bias must agree with breakout direction"))
            if self.require_structure_confirm:
                aligned_struct = any(
                    e.index_pos <= exec_df.index.get_indexer([breakout_ts])[0]
                    and ((breakout_dir == "LONG" and e.direction == "BULLISH") or (breakout_dir == "SHORT" and e.direction == "BEARISH"))
                    for e in ctx.structure_events
                )
                extra_checks.append(("structure_confirms_breakout", aligned_struct, "A7: a same-direction BOS/CHOCH must exist"))

            ok2, checklist2, first_fail2 = run_checklist(extra_checks)
            if not ok2:
                rejected.append(RejectedCandidate(self.name, self.variant, ctx.symbol, breakout_ts,
                                                    "CONFIRMATION_PENDING", first_fail2, checklist2))
                continue

            if self.variant == "continuation":
                self._emit(signals, ctx, orr, breakout_ts, post.iloc[breakout_pos]["close"], breakout_dir, checklist2,
                           "OR breakout, confirmed M5 close beyond range")
            elif self.variant == "failed_breakout":
                self._scan_failed_breakout(ctx, orr, post, breakout_pos, breakout_dir, checklist2, signals, rejected)
            elif self.variant == "retest":
                self._scan_retest(ctx, orr, exec_df, post, breakout_pos, breakout_dir, checklist2, signals, rejected)

        return signals, rejected

    def _emit(self, signals, ctx, orr, ts, price, direction, checklist, reason):
        passed = [c.name for c in checklist if c.passed]
        failed = [c.name for c in checklist if not c.passed]
        feature_row = row_asof(ctx.feature_bars, ts)
        market_condition = str(feature_row["regime_regime"]) if feature_row is not None else ""
        directional_bias = str(feature_row["bias_bias"]) if feature_row is not None else ""
        pattern_hit = None
        if ts in ctx.patterns.index:
            prow = ctx.patterns.loc[ts]
            hits = [p for p in prow.index if prow.get(p, False)]
            pattern_hit = hits[0] if hits else None
        signals.append(Signal(
            strategy=self.name, variant=self.variant, symbol=ctx.symbol, direction=direction,
            entry_ts=ts, entry_price=float(price), setup_reason=reason,
            rules_passed=passed, rules_failed=failed,
            market_condition=market_condition, directional_bias=directional_bias, candle_pattern=pattern_hit,
            fib_state=None, liquidity_state=None, displacement_state=None,
            meta={"or_high": orr.or_high, "or_low": orr.or_low, "or_mid": orr.or_mid},
        ))

    def _scan_retest(self, ctx, orr, exec_df, post, breakout_pos, breakout_dir, checklist, signals, rejected):
        atr_at = ctx.atr_series.reindex(post.index).iloc[breakout_pos]
        buffer = (atr_at if pd.notna(atr_at) else 0) * RETEST_BUFFER_ATR_MULT
        boundary = orr.or_high if breakout_dir == "LONG" else orr.or_low
        window = post.iloc[breakout_pos + 1: breakout_pos + 1 + MAX_CONFIRMATION_MONITOR_BARS]
        for ts, row in window.iterrows():
            touched = (row["low"] <= boundary + buffer) if breakout_dir == "LONG" else (row["high"] >= boundary - buffer)
            if not touched:
                continue
            resumed = (row["close"] > boundary) if breakout_dir == "LONG" else (row["close"] < boundary)
            if resumed:
                self._emit(signals, ctx, orr, ts, row["close"], breakout_dir, checklist,
                           "OR breakout + retest of range boundary + resumption close")
                return
        rejected.append(RejectedCandidate(self.name, self.variant, ctx.symbol, post.index[breakout_pos],
                                            "CONFIRMATION_PENDING", "no_retest_resumption_within_window", checklist))

    def _scan_failed_breakout(self, ctx, orr, post, breakout_pos, breakout_dir, checklist, signals, rejected):
        opposite = orr.or_low if breakout_dir == "LONG" else orr.or_high
        window = post.iloc[breakout_pos + 1: breakout_pos + 1 + MAX_CONFIRMATION_MONITOR_BARS]
        reversal_dir = "SHORT" if breakout_dir == "LONG" else "LONG"
        for ts, row in window.iterrows():
            failed = (row["close"] < opposite) if breakout_dir == "LONG" else (row["close"] > opposite)
            if failed:
                self._emit(signals, ctx, orr, ts, row["close"], reversal_dir, checklist,
                           "OR breakout failed: reversed through opposite OR boundary")
                return
        rejected.append(RejectedCandidate(self.name, self.variant, ctx.symbol, post.index[breakout_pos],
                                            "CONFIRMATION_PENDING", "breakout_did_not_fail_within_window", checklist))

    def _scan_sweep_reversal(self, ctx, orr, post, sweep_pos, sweep_dir, checklist, signals, rejected):
        if sweep_pos is None:
            rejected.append(RejectedCandidate(self.name, self.variant, ctx.symbol, orr.or_close_utc,
                                                "CONFIRMATION_PENDING", "no_liquidity_sweep_of_or_detected", checklist))
            return
        window = post.iloc[sweep_pos + 1: sweep_pos + 1 + MAX_CONFIRMATION_MONITOR_BARS]
        target = orr.or_low if sweep_dir == "LONG" else orr.or_high
        for ts, row in window.iterrows():
            confirmed = (row["close"] > orr.or_mid) if sweep_dir == "LONG" else (row["close"] < orr.or_mid)
            if confirmed:
                self._emit(signals, ctx, orr, ts, row["close"], sweep_dir, checklist,
                           "Liquidity sweep of OR boundary (wick only) + reversal close through OR midpoint")
                return
        rejected.append(RejectedCandidate(self.name, self.variant, ctx.symbol, post.index[sweep_pos],
                                            "CONFIRMATION_PENDING", "sweep_did_not_confirm_reversal", checklist))


if __name__ == "__main__":
    from research.core.feature_bar import build_symbol_engine_data
    from research.data.synthetic import generate_multi_symbol_dataset

    ds = generate_multi_symbol_dataset(["EURUSD"], n_days=90)
    data = build_symbol_engine_data("EURUSD", ds["EURUSD"].bars)

    for variant in ("continuation", "retest", "failed_breakout", "sweep_reversal"):
        strat = OpeningRangeBreakout(variant=variant)
        signals, rejected = strat.scan(data)
        print(f"{variant}: {len(signals)} signals, {len(rejected)} rejected")
        if signals:
            print("  e.g.", signals[0])
    print("OK")
