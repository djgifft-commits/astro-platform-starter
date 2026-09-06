"""
Phase 9B — Opening Range state machine (1UP / 2DOWN).

This is an evolution of research/strategies/opening_range.py (Phase 7),
not a fork: it reuses every underlying engine module (sessions, structure,
regime, bias, fibonacci, liquidity, candle_anatomy — see the REUSE MAP at
the bottom of this docstring) and adds exactly what Phase 9B asks for that
Phase 7's version did not have:

  1. An explicit state machine per NY session day (OR_CREATED -> OR_ACTIVE
     -> OR_BROKEN_UP/DOWN -> OR_RETEST/OR_REVERSAL -> ENTRY_CANDIDATE ->
     ENTRY_CONFIRMED/TRADE_BLOCKED), with a state history retained for
     replay/inspection.
  2. A genuine timeframe separation: OR construction on the aggregated
     15-minute candle (M1-sourced, same causal method as Phase 7),
     BREAKOUT/RETEST/REVERSAL *confirmation* on closed M5 candles, and
     entry *execution* on M1 bars strictly after the M5 confirmation
     timestamp — Phase 7's version entered directly on the M5
     confirmation bar. This is the one behavior change from Phase 7.
  3. A bias-hierarchy check (HTF bias / internal+external structure /
     regime direction / liquidity-implied direction) producing
     BULLISH/BEARISH/NEUTRAL/CONFLICTED — a setup is never assumed
     bullish just because price broke OR_high.
  4. MARKET_CONTEXT + EntryDecision objects attached to every candidate,
     confirmed or rejected.
  5. Fibonacci retracement depth (for the RETEST family) reported as
     information (depth bin), never as a gating rule on its own.

REUSE MAP (nothing below is reimplemented, only orchestrated):
  research/core/sessions.py            -> NY opening range construction
  research/core/structure.py            -> swings, BOS/CHOCH (via protected_levels)
  research/core/protected_levels.py      -> internal/external structure, protected hi/lo
  research/core/regime.py                 -> market regime, trend direction
  research/core/bias.py                    -> HTF weighted directional bias
  research/core/fibonacci.py                -> retracement level/depth measurement
  research/core/liquidity.py                 -> liquidity sweep detection
  research/core/candle_anatomy.py             -> M1 entry-candle confirmation
  research/core/market_context.py              -> MARKET_CONTEXT assembly
  research/strategies/entry_decision.py         -> ENTRY_DECISION assembly
  research/strategies/base.py                    -> Signal/RejectedCandidate/row_asof/window_after
"""
from __future__ import annotations

import dataclasses
import enum
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd

from research.core.fibonacci import FIB_LEVELS
from research.core.market_context import MarketContext, build_market_context
from research.strategies.base import RejectedCandidate, Signal, Strategy, run_checklist, window_after
from research.strategies.entry_decision import EntryDecision, from_rejected, from_signal

M1_ENTRY_MONITOR_BARS = 15  # how many M1 bars after M5 confirmation to search for the entry trigger
M5_BREAKOUT_MONITOR_BARS = 48  # ~4h
M5_RETEST_MONITOR_BARS = 24  # ~2h
RETEST_BUFFER_ATR_MULT = 0.15
BULLISH_M1_PATTERNS = ["bullish_engulfing", "hammer", "pin_bar", "marubozu", "dragonfly_doji"]
BEARISH_M1_PATTERNS = ["bearish_engulfing", "shooting_star", "pin_bar", "marubozu", "gravestone_doji"]


class ORState(str, enum.Enum):
    OR_CREATED = "OR_CREATED"
    OR_ACTIVE = "OR_ACTIVE"
    OR_BROKEN_UP = "OR_BROKEN_UP"
    OR_BROKEN_DOWN = "OR_BROKEN_DOWN"
    OR_RETEST = "OR_RETEST"
    OR_REVERSAL = "OR_REVERSAL"
    OR_INVALIDATED = "OR_INVALIDATED"
    OR_EXPIRED = "OR_EXPIRED"
    ENTRY_CANDIDATE = "ENTRY_CANDIDATE"
    ENTRY_CONFIRMED = "ENTRY_CONFIRMED"
    TRADE_BLOCKED = "TRADE_BLOCKED"
    TRADE_EXECUTED = "TRADE_EXECUTED"


@dataclasses.dataclass
class ORStateEvent:
    state: str
    timestamp: pd.Timestamp
    detail: str = ""


@dataclasses.dataclass
class ORDaySummary:
    date: pd.Timestamp
    or_high: float
    or_low: float
    state_history: List[ORStateEvent]
    entry_decisions: List[EntryDecision]


def classify_bias_hierarchy(mc: MarketContext, candidate_direction: str) -> Tuple[str, List[str], List[str]]:
    """BULLISH/BEARISH/NEUTRAL/CONFLICTED from independent signal sources.
    A setup is NEVER assumed bullish just because price broke OR_high --
    this function is what a caller must check before treating a breakout
    as a directional bias, not the breakout direction itself."""
    votes = {
        "htf_bias": {"LONG": "BULLISH", "STRONG_LONG": "BULLISH", "SHORT": "BEARISH", "STRONG_SHORT": "BEARISH"}.get(mc.htf_bias, "NEUTRAL"),
        "external_structure": {"LONG": "BULLISH", "SHORT": "BEARISH"}.get(mc.swing_structure, "NEUTRAL"),
        "internal_structure": {"LONG": "BULLISH", "SHORT": "BEARISH"}.get(mc.internal_structure, "NEUTRAL"),
        "regime_trend": {"LONG": "BULLISH", "SHORT": "BEARISH"}.get(mc.trend_state, "NEUTRAL"),
        "liquidity": {"RECENT_SSL_SWEEP": "BULLISH", "RECENT_BSL_SWEEP": "BEARISH"}.get(mc.liquidity_state, "NEUTRAL"),
    }
    candidate_label = "BULLISH" if candidate_direction == "LONG" else "BEARISH"
    agreeing = [k for k, v in votes.items() if v == candidate_label]
    conflicting = [k for k, v in votes.items() if v not in ("NEUTRAL", candidate_label)]
    neutral = [k for k, v in votes.items() if v == "NEUTRAL"]

    if len(conflicting) >= 2 and len(agreeing) >= 1:
        return "CONFLICTED", agreeing, conflicting
    if len(agreeing) >= 2:
        return candidate_label, agreeing, conflicting
    if len(neutral) == len(votes):
        return "NEUTRAL", agreeing, conflicting
    return "CONFLICTED" if conflicting else "NEUTRAL", agreeing, conflicting


def _fib_depth_bin(level: float) -> str:
    if level < 0.236:
        return "NO_RETRACEMENT"
    if level <= 0.382:
        return "SHALLOW_RETRACEMENT"
    if level <= 0.618:
        return "NORMAL_RETRACEMENT"
    if level <= 0.786:
        return "DEEP_RETRACEMENT"
    return "NO_RETRACEMENT"  # beyond 78.6% is treated as invalidation territory, not a "deep" retracement


def _m1_entry_trigger(m1_after: pd.DataFrame, patterns_m1: pd.DataFrame, direction: str) -> Optional[Tuple[pd.Timestamp, float, str]]:
    """M1 entry execution: the first M1 bar, strictly after M5 confirmation,
    whose close continues in `direction` AND shows a qualifying candle
    confirmation. Returns (entry_ts, entry_price, pattern_name) or None."""
    confirm_set = BULLISH_M1_PATTERNS if direction == "LONG" else BEARISH_M1_PATTERNS
    for ts, row in m1_after.iterrows():
        continues = (row["close"] > row["open"]) if direction == "LONG" else (row["close"] < row["open"])
        if not continues:
            continue
        if ts not in patterns_m1.index:
            continue
        prow = patterns_m1.loc[ts]
        hit = [p for p in confirm_set if prow.get(p, False)]
        if hit:
            return ts, float(row["close"]), hit[0]
    return None


class OpeningRangeStateMachine(Strategy):
    """entry_family: 'breakout' | 'retest' | 'reversal'"""
    name = "opening_range_v2"

    def __init__(self, entry_family: str = "breakout", require_bias_agreement: bool = True):
        assert entry_family in ("breakout", "retest", "reversal")
        self.entry_family = entry_family
        self.variant = entry_family
        self.require_bias_agreement = require_bias_agreement
        self.day_summaries: List[ORDaySummary] = []  # populated by scan(), for replay/inspection

    def scan(self, ctx) -> Tuple[List[Signal], List[RejectedCandidate]]:
        from research.core.protected_levels import compute_protected_levels, compute_structure_layers
        from research.core.regime import _current_structure_direction

        exec_df = ctx.frames[ctx.execution_tf]  # M5
        m1_df = ctx.frames.get("M1", exec_df)
        layers = compute_structure_layers(exec_df)
        protected = compute_protected_levels(exec_df, layers.external_events, layers.external_swings)
        ext_dir = _current_structure_direction(exec_df, layers.external_events)
        int_dir = _current_structure_direction(exec_df, layers.internal_events)

        signals: List[Signal] = []
        rejected: List[RejectedCandidate] = []
        self.day_summaries = []

        for orr in ctx.opening_ranges:
            history = [ORStateEvent(ORState.OR_CREATED, orr.session_open_utc, "OR window opened")]
            decisions: List[EntryDecision] = []

            if not orr.sufficient_data or orr.or_range_size <= 0:
                history.append(ORStateEvent(ORState.OR_INVALIDATED, orr.or_close_utc, "insufficient OR data or zero range"))
                self.day_summaries.append(ORDaySummary(orr.date, orr.or_high, orr.or_low, history, decisions))
                continue
            history.append(ORStateEvent(ORState.OR_ACTIVE, orr.or_close_utc, f"OR_high={orr.or_high:.5f} OR_low={orr.or_low:.5f}"))

            post_m5 = window_after(exec_df, orr.or_close_utc, M5_BREAKOUT_MONITOR_BARS)
            if post_m5.empty:
                history.append(ORStateEvent(ORState.OR_EXPIRED, orr.or_close_utc, "no post-OR M5 data"))
                self.day_summaries.append(ORDaySummary(orr.date, orr.or_high, orr.or_low, history, decisions))
                continue

            breakout_ts, breakout_dir, breakout_price = None, None, None
            sweep_ts, sweep_dir = None, None
            for ts, row in post_m5.iterrows():
                if row["close"] > orr.or_high:
                    breakout_ts, breakout_dir, breakout_price = ts, "LONG", row["close"]
                    history.append(ORStateEvent(ORState.OR_BROKEN_UP, ts, f"M5 close {row['close']:.5f} > OR_high"))
                    break
                if row["close"] < orr.or_low:
                    breakout_ts, breakout_dir, breakout_price = ts, "SHORT", row["close"]
                    history.append(ORStateEvent(ORState.OR_BROKEN_DOWN, ts, f"M5 close {row['close']:.5f} < OR_low"))
                    break
                if row["high"] > orr.or_high and sweep_ts is None:
                    sweep_ts, sweep_dir = ts, "SHORT"
                if row["low"] < orr.or_low and sweep_ts is None:
                    sweep_ts, sweep_dir = ts, "LONG"

            if self.entry_family in ("breakout", "retest") and breakout_ts is None:
                history.append(ORStateEvent(ORState.OR_EXPIRED, post_m5.index[-1], "no confirmed M5 breakout within monitor window"))
                self._reject(rejected, ctx, orr.or_close_utc, protected, layers.external_events, ext_dir, int_dir,
                             "SETUP_FORMING", "no_confirmed_m5_breakout")
                self.day_summaries.append(ORDaySummary(orr.date, orr.or_high, orr.or_low, history, decisions))
                continue

            if self.entry_family == "breakout":
                self._handle_breakout(ctx, orr, breakout_ts, breakout_dir, m1_df, protected, layers.external_events,
                                       ext_dir, int_dir, history, decisions, signals, rejected)
            elif self.entry_family == "retest":
                self._handle_retest(ctx, orr, exec_df, post_m5, breakout_ts, breakout_dir, m1_df, protected,
                                     layers.external_events, ext_dir, int_dir, history, decisions, signals, rejected)
            else:
                self._handle_reversal(ctx, orr, post_m5, sweep_ts, sweep_dir, m1_df, protected,
                                       layers.external_events, ext_dir, int_dir, history, decisions, signals, rejected)

            self.day_summaries.append(ORDaySummary(orr.date, orr.or_high, orr.or_low, history, decisions))

        return signals, rejected

    def _reject(self, rejected, ctx, ts, protected, ext_events, ext_dir, int_dir, state, reason):
        mc = build_market_context(ctx, ts, protected, ext_events, ext_dir, int_dir)
        checks = [(reason, False, "")]
        _, checklist, first_fail = run_checklist(checks)
        rc = RejectedCandidate(self.name, self.variant, ctx.symbol, ts, state, first_fail, checklist)
        rejected.append(rc)
        return from_rejected(rc, mc, entry_type=self.entry_family.upper())

    def _try_confirm_and_enter(self, ctx, orr, direction, confirm_ts, m1_df, protected, ext_events, ext_dir, int_dir,
                                history, decisions, signals, rejected, setup_reason_prefix, extra_meta=None):
        mc = build_market_context(ctx, confirm_ts, protected, ext_events, ext_dir, int_dir)
        bias_label, agreeing, conflicting = classify_bias_hierarchy(mc, direction)

        checks = [
            ("bias_not_conflicted", (not self.require_bias_agreement) or bias_label != "CONFLICTED",
             f"bias sources: agree={agreeing} conflict={conflicting}"),
            ("bias_agrees_or_neutral", (not self.require_bias_agreement) or bias_label in ("BULLISH", "BEARISH", "NEUTRAL")
             and (bias_label == "NEUTRAL" or (bias_label == "BULLISH") == (direction == "LONG")),
             f"bias_label={bias_label}"),
        ]
        ok, checklist, first_fail = run_checklist(checks)
        history.append(ORStateEvent(ORState.ENTRY_CANDIDATE, confirm_ts, f"bias={bias_label}"))

        if not ok:
            history.append(ORStateEvent(ORState.TRADE_BLOCKED, confirm_ts, first_fail))
            rc = RejectedCandidate(self.name, self.variant, ctx.symbol, confirm_ts, "ENTRY_CANDIDATE", first_fail, checklist)
            rejected.append(rc)
            decisions.append(from_rejected(rc, mc, entry_type=self.entry_family.upper()))
            return

        m1_window = window_after(m1_df, confirm_ts, M1_ENTRY_MONITOR_BARS)
        from research.core.candle_anatomy import compute_anatomy, recognize_patterns
        anatomy_m1 = compute_anatomy(m1_window) if not m1_window.empty else m1_window
        patterns_m1 = recognize_patterns(m1_window, anatomy_m1) if not m1_window.empty else pd.DataFrame()

        trigger = _m1_entry_trigger(m1_window, patterns_m1, direction) if not m1_window.empty else None
        if trigger is None:
            history.append(ORStateEvent(ORState.TRADE_BLOCKED, confirm_ts, "no_m1_entry_trigger_within_window"))
            rc = RejectedCandidate(self.name, self.variant, ctx.symbol, confirm_ts, "CONFIRMATION_PENDING",
                                    "no_m1_entry_trigger_within_window", checklist)
            rejected.append(rc)
            decisions.append(from_rejected(rc, mc, entry_type=self.entry_family.upper()))
            return

        entry_ts, entry_price, pattern = trigger
        history.append(ORStateEvent(ORState.ENTRY_CONFIRMED, entry_ts, f"M1 {pattern}"))
        history.append(ORStateEvent(ORState.TRADE_EXECUTED, entry_ts, f"entry_price={entry_price:.5f}"))

        meta = {"or_high": orr.or_high, "or_low": orr.or_low, "or_mid": orr.or_mid,
                "bias_hierarchy": bias_label, "bias_agreeing": agreeing, "bias_conflicting": conflicting}
        if extra_meta:
            meta.update(extra_meta)

        sig = Signal(
            strategy=self.name, variant=self.variant, symbol=ctx.symbol, direction=direction,
            entry_ts=entry_ts, entry_price=entry_price,
            setup_reason=f"{setup_reason_prefix} + M1 {pattern} entry trigger",
            rules_passed=[c.name for c in checklist], rules_failed=[],
            market_condition=mc.market_regime or "", directional_bias=bias_label,
            candle_pattern=pattern, fib_state=meta.get("fib_depth_bin"), liquidity_state=mc.liquidity_state,
            displacement_state=None, meta=meta,
        )
        signals.append(sig)
        decisions.append(from_signal(sig, mc, entry_type=self.entry_family.upper()))

    def _handle_breakout(self, ctx, orr, breakout_ts, direction, m1_df, protected, ext_events, ext_dir, int_dir,
                          history, decisions, signals, rejected):
        breakout_bar = ctx.frames[ctx.execution_tf].loc[breakout_ts]
        self._try_confirm_and_enter(ctx, orr, direction, breakout_ts, m1_df, protected, ext_events, ext_dir, int_dir,
                                     history, decisions, signals, rejected,
                                     setup_reason_prefix="OR breakout (M5 close beyond OR boundary)",
                                     extra_meta={"breakout_candle_low": float(breakout_bar["low"]),
                                                 "breakout_candle_high": float(breakout_bar["high"])})

    def _handle_retest(self, ctx, orr, exec_df, post_m5, breakout_ts, direction, m1_df, protected, ext_events,
                        ext_dir, int_dir, history, decisions, signals, rejected):
        atr_at = ctx.atr_series.asof(breakout_ts)
        buffer = (atr_at if pd.notna(atr_at) else 0) * RETEST_BUFFER_ATR_MULT
        boundary = orr.or_high if direction == "LONG" else orr.or_low
        window = window_after(exec_df, breakout_ts, M5_RETEST_MONITOR_BARS)

        # impulse extreme = the furthest price traveled beyond the OR boundary
        # before any retracement back toward it -- this is the "impulse" a
        # retest is measured against, tracked bar-by-bar (causal: only uses
        # bars up to and including the one under evaluation).
        running_extreme = boundary
        for ts, row in window.iterrows():
            running_extreme = max(running_extreme, row["high"]) if direction == "LONG" else min(running_extreme, row["low"])
            impulse_size = abs(running_extreme - boundary)
            if impulse_size <= 0:
                continue
            touched = (row["low"] <= boundary + buffer) if direction == "LONG" else (row["high"] >= boundary - buffer)
            if not touched:
                continue
            resumed = (row["close"] > boundary) if direction == "LONG" else (row["close"] < boundary)
            if not resumed:
                continue
            history.append(ORStateEvent(ORState.OR_RETEST, ts, "price retested OR boundary and resumed"))

            touch_price = row["low"] if direction == "LONG" else row["high"]
            depth = abs(boundary - touch_price) / impulse_size if impulse_size else 0.0
            nearest_fib = min(FIB_LEVELS, key=lambda lv: abs(lv - depth))
            fib_bin = _fib_depth_bin(depth)

            breakout_bar = exec_df.loc[breakout_ts]
            self._try_confirm_and_enter(
                ctx, orr, direction, ts, m1_df, protected, ext_events, ext_dir, int_dir, history, decisions,
                signals, rejected, setup_reason_prefix="OR breakout + retest of boundary",
                extra_meta={"retracement_depth": depth, "nearest_fib_level": nearest_fib, "fib_depth_bin": fib_bin,
                            "breakout_candle_low": float(breakout_bar["low"]), "breakout_candle_high": float(breakout_bar["high"])},
            )
            return

        history.append(ORStateEvent(ORState.OR_EXPIRED, window.index[-1] if len(window) else breakout_ts,
                                     "no qualifying retest within monitor window"))
        self._reject(rejected, ctx, breakout_ts, protected, ext_events, ext_dir, int_dir,
                     "CONFIRMATION_PENDING", "no_retest_within_window")

    def _handle_reversal(self, ctx, orr, post_m5, sweep_ts, sweep_dir, m1_df, protected, ext_events, ext_dir,
                          int_dir, history, decisions, signals, rejected):
        if sweep_ts is None:
            history.append(ORStateEvent(ORState.OR_EXPIRED, post_m5.index[-1], "no liquidity sweep of OR boundary detected"))
            self._reject(rejected, ctx, post_m5.index[-1], protected, ext_events, ext_dir, int_dir,
                         "CONFIRMATION_PENDING", "no_liquidity_sweep_detected")
            return
        history.append(ORStateEvent(ORState.OR_REVERSAL, sweep_ts, f"liquidity sweep, implied reversal={sweep_dir}"))

        window = post_m5.loc[post_m5.index > sweep_ts]
        target = orr.or_mid
        for ts, row in window.iterrows():
            confirmed = (row["close"] > target) if sweep_dir == "LONG" else (row["close"] < target)
            if confirmed:
                self._try_confirm_and_enter(
                    ctx, orr, sweep_dir, ts, m1_df, protected, ext_events, ext_dir, int_dir, history, decisions,
                    signals, rejected, setup_reason_prefix="OR liquidity sweep + failed breakout + reversal through OR mid",
                )
                return
        history.append(ORStateEvent(ORState.OR_EXPIRED, window.index[-1] if len(window) else sweep_ts,
                                     "sweep did not confirm reversal through OR midpoint"))
        self._reject(rejected, ctx, sweep_ts, protected, ext_events, ext_dir, int_dir,
                     "CONFIRMATION_PENDING", "sweep_did_not_confirm_reversal")


if __name__ == "__main__":
    from research.core.feature_bar import build_symbol_engine_data
    from research.data.synthetic import generate_multi_symbol_dataset

    ds = generate_multi_symbol_dataset(["EURUSD"], n_days=180)
    ctx = build_symbol_engine_data("EURUSD", ds["EURUSD"].bars)

    for family in ("breakout", "retest", "reversal"):
        strat = OpeningRangeStateMachine(entry_family=family)
        signals, rejected = strat.scan(ctx)
        print(f"{family}: {len(signals)} signals, {len(rejected)} rejected, {len(strat.day_summaries)} OR-days tracked")
        if signals:
            s = signals[0]
            print("  e.g. entry_ts=", s.entry_ts, "direction=", s.direction, "bias=", s.directional_bias,
                  "reason=", s.setup_reason)
        # print one full state-machine day for inspection
        for day in strat.day_summaries:
            if day.entry_decisions:
                print("  sample day state history:")
                for ev in day.state_history:
                    print("   ", ev.state, ev.timestamp, ev.detail)
                break
    print("OK")
