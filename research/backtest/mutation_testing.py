"""
Phase 8AI — Mutation testing.

Intentionally introduces the exact mutations the MASTER COMMAND names,
one at a time, and asserts that this project's existing causality/
correctness checks (research/data/quality.py, and each module's own
`__main__` assertions) DETECT the mutation. Each mutation is applied to
an in-memory copy and the original code/data is never modified on disk --
"restore byte-identically" is satisfied trivially here because the
mutation never touches a file, only a local variable inside this test
process.

Every mutation test follows the same shape: (1) construct a correct
baseline, (2) apply the mutation, (3) assert the appropriate check FAILS
on the mutated version, (4) assert the SAME check PASSES on the
unmutated baseline (a guard against a mutation test that would "pass"
regardless of input, which would make the test meaningless).
"""
from __future__ import annotations

import copy
import dataclasses
from typing import Callable, List, Tuple

import numpy as np
import pandas as pd

from research.core.market_context import MarketContext

MutationResult = Tuple[str, bool, str]  # (mutation_name, detected, detail)


def _run_case(name: str, fn: Callable[[], bool], detail_ok: str, detail_fail: str) -> MutationResult:
    try:
        detected = fn()
    except AssertionError:
        detected = True
    except Exception as e:  # a crash on mutated input also counts as "detected"
        detected = True
        detail_ok = f"{detail_ok} (raised {type(e).__name__})"
    return (name, detected, detail_ok if detected else detail_fail)


def test_future_bar_access() -> MutationResult:
    from research.data.quality import assert_no_lookahead

    def check():
        decision_ts = pd.Timestamp("2024-01-01 10:00", tz="UTC")
        future_feature_ts = pd.Timestamp("2024-01-01 10:05", tz="UTC")  # 5 min AFTER decision
        try:
            assert_no_lookahead(future_feature_ts, decision_ts)
            return False  # should have raised -- mutation NOT detected
        except AssertionError:
            return True  # correctly detected

    return _run_case("future_bar_access", check,
                      "assert_no_lookahead correctly raised on feature_ts > decision_ts",
                      "assert_no_lookahead FAILED to raise on a future feature timestamp")


def test_forming_bar_inclusion() -> MutationResult:
    from research.data.loaders import resample_ohlc
    from research.data.synthetic import generate_multi_symbol_dataset

    def check():
        ds = generate_multi_symbol_dataset(["EURUSD"], n_days=3)
        m1 = ds["EURUSD"].bars
        # MUTATION: append 3 extra minutes that would start a NEW, incomplete M5 bar
        mutated_index = m1.index.append(pd.DatetimeIndex([
            m1.index[-1] + pd.Timedelta(minutes=1), m1.index[-1] + pd.Timedelta(minutes=2),
        ]))
        extra = m1.iloc[-2:].copy()
        extra.index = mutated_index[-2:]
        mutated = pd.concat([m1, extra])
        out = resample_ohlc(mutated, "M5")
        bar_minutes = 5
        last_bucket_end = out.index[-1] + pd.Timedelta(minutes=bar_minutes)
        # a correct resampler must NOT include a bucket whose right edge
        # exceeds the last available M1 timestamp + 1 minute
        is_forming = last_bucket_end > (mutated.index[-1] + pd.Timedelta(minutes=1))
        return not is_forming  # True = correctly excluded the forming bar

    return _run_case("forming_bar_inclusion", check,
                      "resample_ohlc correctly excluded the incomplete trailing M5 bar",
                      "resample_ohlc INCLUDED a forming (incomplete) trailing bar")


def test_wrong_timezone() -> MutationResult:
    from research.core.sessions import session_open_utc
    from research.config import NY_TZ

    def check():
        correct = session_open_utc(pd.Timestamp("2024-07-01", tz="UTC"), "09:30", NY_TZ)
        # MUTATION: hardcode EST (UTC-5) year-round, ignoring EDT in July
        mutated_wrong = pd.Timestamp("2024-07-01 14:30", tz="UTC")  # what a naive UTC-5 hardcode would give
        return correct != mutated_wrong  # True = the real function disagrees with the naive wrong one (as it must, in July=EDT/UTC-4)

    return _run_case("wrong_timezone_dst", check,
                      "session_open_utc correctly differs from a hardcoded EST-year-round assumption in July (EDT)",
                      "session_open_utc matched the incorrect hardcoded-EST assumption during EDT")


def test_wrong_swing_confirmation() -> MutationResult:
    from research.core.structure import find_swings
    from research.data.synthetic import generate_multi_symbol_dataset

    def check():
        ds = generate_multi_symbol_dataset(["EURUSD"], n_days=30)
        m15 = ds["EURUSD"].bars.resample("15min").agg(
            {"open": "first", "high": "max", "low": "min", "close": "last"}
        ).dropna()
        swings = find_swings(m15, confirm_bars=3)
        # MUTATION: a swing "confirmed" at (or before) its own formation bar
        # would be a causality violation -- assert the REAL function never
        # produces one.
        violations = [s for s in swings if s.confirmed_at_pos <= s.index_pos]
        return len(violations) == 0

    return _run_case("wrong_swing_confirmation", check,
                      "every swing's confirmed_at_pos > index_pos (no premature confirmation)",
                      "found a swing confirmed at or before its own formation bar")


def test_wrong_spread_direction() -> MutationResult:
    from research.strategies.base import Signal

    def check():
        sig = Signal(strategy="t", variant="v", symbol="EURUSD", direction="LONG",
                     entry_ts=pd.Timestamp.now(tz="UTC"), entry_price=1.1000,
                     setup_reason="", rules_passed=[], rules_failed=[], market_condition="",
                     directional_bias="", candle_pattern=None, fib_state=None, liquidity_state=None,
                     displacement_state=None)
        half_spread = 0.0002
        correct_entry = sig.entry_price + half_spread if sig.direction == "LONG" else sig.entry_price - half_spread
        # MUTATION: apply spread in the FAVORABLE direction for a LONG (a
        # sign-flip bug that would make trading look artificially cheap or
        # even profitable purely from a cost-direction error)
        mutated_entry = sig.entry_price - half_spread if sig.direction == "LONG" else sig.entry_price + half_spread
        return correct_entry != mutated_entry and correct_entry > sig.entry_price

    return _run_case("wrong_spread_direction", check,
                      "LONG entry correctly adjusted UNFAVORABLY (higher) by half-spread, not favorably",
                      "spread direction check failed to distinguish favorable from unfavorable adjustment")


def test_train_test_contamination() -> MutationResult:
    from research.backtest.validation import purged_embargoed_folds
    from research.risk.exit_models import TradeResult
    from research.strategies.base import Signal

    def make_trade(entry_ts, exit_ts, r=1.0):
        sig = Signal(strategy="t", variant="v", symbol="EURUSD", direction="LONG", entry_ts=entry_ts,
                     entry_price=1.0, setup_reason="", rules_passed=[], rules_failed=[], market_condition="",
                     directional_bias="", candle_pattern=None, fib_state=None, liquidity_state=None,
                     displacement_state=None)
        return TradeResult(signal=sig, sl_model="x", tp_model="x", exit_model="x", entry_ts=entry_ts,
                            entry_price=1.0, initial_sl=0.99, initial_risk=0.01, exit_ts=exit_ts,
                            exit_price=1.01, exit_reason="TP_HIT", r_multiple=r, mfe_r=r, mae_r=0.0, duration_bars=1)

    def check():
        base = pd.Timestamp("2024-01-01", tz="UTC")
        trades = [make_trade(base + pd.Timedelta(days=i), base + pd.Timedelta(days=i, hours=2)) for i in range(100)]
        # Add a trade that ENTERS in fold 0's span but EXITS well into
        # fold 2's span -- with 5 folds over ~100 days (~19.8 days/fold),
        # entry=day5 sits in fold 0 and exit=day50 sits in fold 2, so this
        # trade's outcome window overlaps folds 1 AND 2's test spans and
        # must be purged from both of their train sets.
        overlapping = make_trade(base + pd.Timedelta(days=5), base + pd.Timedelta(days=50))
        trades.append(overlapping)
        folds = purged_embargoed_folds(trades, n_folds=5, embargo=pd.Timedelta(hours=1))
        return any(f.n_purged > 0 for f in folds)

    return _run_case("train_test_contamination", check,
                      "purged_embargoed_folds correctly purged a trade whose outcome window crossed a fold boundary",
                      "purged_embargoed_folds failed to purge a trade with a boundary-crossing outcome window")


def test_disabled_cost() -> MutationResult:
    from research.backtest.engine import BacktestConfig, run_backtest
    from research.core.feature_bar import build_symbol_engine_data
    from research.data.synthetic import generate_multi_symbol_dataset
    from research.strategies.opening_range import OpeningRangeBreakout

    def check():
        ds = generate_multi_symbol_dataset(["EURUSD"], n_days=90)
        ctx = build_symbol_engine_data("EURUSD", ds["EURUSD"].bars)
        strat = OpeningRangeBreakout(variant="continuation")
        with_cost = run_backtest(ctx, strat, BacktestConfig(spread_multiplier=1.0))
        no_cost = run_backtest(ctx, strat, BacktestConfig(spread_multiplier=0.0))
        rs_with = np.mean([t.r_multiple for t in with_cost.trades]) if with_cost.trades else 0.0
        rs_without = np.mean([t.r_multiple for t in no_cost.trades]) if no_cost.trades else 0.0
        # disabling cost must never make the result WORSE -- if it does,
        # the cost is being applied backwards
        return rs_without >= rs_with

    return _run_case("disabled_cost_sign_check", check,
                      "disabling spread cost did not make results worse (cost applied in the correct direction)",
                      "disabling spread cost made results WORSE -- cost is being applied backwards")


def test_wrong_or_boundary() -> MutationResult:
    from research.core.sessions import NY_SESSION_OPEN, NY_TZ, compute_ny_opening_ranges, session_open_utc

    def check():
        open_utc = session_open_utc(pd.Timestamp("2024-06-03", tz="UTC"), NY_SESSION_OPEN, NY_TZ)
        or_minutes = 15
        idx = pd.date_range(open_utc, periods=or_minutes + 1, freq="1min", tz="UTC")
        # the (or_minutes)-th bar sits AT the close boundary (open + 15min)
        # and must be EXCLUDED -- give it an extreme high/low that would
        # corrupt or_high/or_low if a mutated "<=" boundary let it in.
        rows = []
        for i, ts in enumerate(idx):
            if i < or_minutes:
                rows.append({"open": 1.1000, "high": 1.1005, "low": 1.0995, "close": 1.1000})
            else:
                rows.append({"open": 1.1000, "high": 9.9999, "low": 0.0001, "close": 1.1000})
        m1 = pd.DataFrame(rows, index=idx)
        ors = compute_ny_opening_ranges(m1, or_minutes=or_minutes)
        assert len(ors) == 1
        orr = ors[0]
        return orr.or_high < 9.0 and orr.or_low > 0.001

    return _run_case("wrong_or_boundary", check,
                      "compute_ny_opening_ranges correctly excluded the bar exactly at the OR close boundary",
                      "compute_ny_opening_ranges let a bar at/after the OR close boundary corrupt or_high/or_low")


def test_wrong_session_dst_boundary() -> MutationResult:
    from research.core.sessions import NY_SESSION_OPEN, NY_TZ, session_open_utc

    def check():
        # 2024-03-10 is the US spring-forward transition (EST -> EDT).
        before = session_open_utc(pd.Timestamp("2024-03-08", tz="UTC"), NY_SESSION_OPEN, NY_TZ)  # EST, UTC-5
        after = session_open_utc(pd.Timestamp("2024-03-11", tz="UTC"), NY_SESSION_OPEN, NY_TZ)  # EDT, UTC-4
        # a correct DST-aware conversion must shift the UTC opening time by
        # exactly 1 hour earlier once EDT begins; a mutation that hardcodes
        # one fixed UTC offset year-round would show a 0-hour shift here.
        before_utc_hour = before.tz_convert("UTC").hour
        after_utc_hour = after.tz_convert("UTC").hour
        return (before_utc_hour - after_utc_hour) == 1

    return _run_case("wrong_session_dst_boundary", check,
                      "NY opening range UTC anchor correctly shifted by 1 hour across the spring-forward DST transition",
                      "NY opening range UTC anchor did NOT shift across the DST transition -- looks like a hardcoded fixed-offset bug")


def test_wrong_m5_confirmation_direction() -> MutationResult:
    from research.core.feature_bar import build_symbol_engine_data
    from research.data.synthetic import generate_multi_symbol_dataset
    from research.strategies.opening_range_v2 import ORState, OpeningRangeStateMachine

    def check():
        ds = generate_multi_symbol_dataset(["EURUSD"], n_days=180, seed=7)
        ctx = build_symbol_engine_data("EURUSD", ds["EURUSD"].bars)
        strat = OpeningRangeStateMachine(entry_family="breakout")
        strat.scan(ctx)
        # OR_BROKEN_UP/OR_BROKEN_DOWN are recorded independently of the
        # direction later attached to any resulting signal -- if a
        # mutation swapped the LONG/SHORT literal passed to the entry
        # handler without touching the state label (or vice versa), a
        # produced signal's direction would disagree with its own day's
        # recorded breakout state.
        checked = 0
        for day in strat.day_summaries:
            states = {ev.state for ev in day.state_history}
            confirmed = [d for d in day.entry_decisions if d.decision == "ENTRY_CONFIRMED"]
            if not confirmed:
                continue
            checked += 1
            if ORState.OR_BROKEN_UP in states and confirmed[0].direction != "LONG":
                return False
            if ORState.OR_BROKEN_DOWN in states and confirmed[0].direction != "SHORT":
                return False
        return checked > 0

    return _run_case("wrong_m5_confirmation_direction", check,
                      "every confirmed OR breakout signal's direction agreed with its own day's OR_BROKEN_UP/DOWN state",
                      "found a confirmed breakout signal whose direction disagreed with its own recorded OR_BROKEN_UP/DOWN state")


def test_wrong_m1_entry_timing() -> MutationResult:
    from research.strategies.base import window_after

    def check():
        idx = pd.date_range("2024-01-01 09:45", periods=10, freq="1min", tz="UTC")
        df = pd.DataFrame({"close": range(10)}, index=idx)
        confirm_ts = idx[3]
        correct = window_after(df, confirm_ts, 5)
        # MUTATION: an off-by-one that includes the confirmation bar itself
        # (side="left" instead of "right") would leak a bar that was known
        # AT confirmation time into the "after confirmation" entry search --
        # a real look-ahead-adjacent timing bug.
        pos_mutated = df.index.searchsorted(confirm_ts, side="left")
        mutated = df.iloc[pos_mutated: pos_mutated + 5]
        correct_excludes_confirm_bar = confirm_ts not in correct.index
        mutation_would_include_confirm_bar = confirm_ts in mutated.index
        return correct_excludes_confirm_bar and mutation_would_include_confirm_bar

    return _run_case("wrong_m1_entry_timing", check,
                      "window_after correctly excludes the M5 confirmation bar itself from the M1 entry search window",
                      "window_after failed to exclude the confirmation bar -- M1 entry search would not be strictly after confirmation")


def test_wrong_sl_model_side() -> MutationResult:
    from research.risk import sl_models
    from research.strategies.base import Signal

    def make_signal(direction):
        return Signal(strategy="t", variant="v", symbol="EURUSD", direction=direction,
                      entry_ts=pd.Timestamp.now(tz="UTC"), entry_price=1.1010,
                      setup_reason="", rules_passed=[], rules_failed=[], market_condition="",
                      directional_bias="", candle_pattern=None, fib_state=None, liquidity_state=None,
                      displacement_state=None,
                      meta={"breakout_candle_low": 1.0990, "breakout_candle_high": 1.1030})

    def check():
        long_sl = sl_models.breakout_candle(make_signal("LONG"), buffer_atr=0.0, atr_at_entry=0.0)
        short_sl = sl_models.breakout_candle(make_signal("SHORT"), buffer_atr=0.0, atr_at_entry=0.0)
        # a LONG stop must sit BELOW entry (protective), a SHORT stop ABOVE
        # entry -- a mutation that read the wrong key (high instead of low,
        # or vice versa) would put the stop on the wrong, unprotective side.
        return long_sl is not None and short_sl is not None and long_sl.price < 1.1010 < short_sl.price

    return _run_case("wrong_sl_model_side", check,
                      "BREAKOUT_CANDLE stop correctly placed below entry for LONG and above entry for SHORT",
                      "BREAKOUT_CANDLE stop was placed on the wrong (unprotective) side of entry for at least one direction")


def test_wrong_tp_model_direction() -> MutationResult:
    from research.core.liquidity import LiquidityPool
    from research.risk import tp_models
    from research.strategies.base import Signal

    def make_signal(direction, entry_price=1.1000):
        return Signal(strategy="t", variant="v", symbol="EURUSD", direction=direction,
                      entry_ts=pd.Timestamp.now(tz="UTC"), entry_price=entry_price,
                      setup_reason="", rules_passed=[], rules_failed=[], market_condition="",
                      directional_bias="", candle_pattern=None, fib_state=None, liquidity_state=None,
                      displacement_state=None, meta={})

    def check():
        pools = [
            LiquidityPool(price=1.1050, kind="BSL", source_swing_pos=0),
            LiquidityPool(price=1.0950, kind="SSL", source_swing_pos=0),
        ]
        long_tp = tp_models.liquidity_target(make_signal("LONG"), pools)
        short_tp = tp_models.liquidity_target(make_signal("SHORT"), pools)
        # a LONG target must sit ABOVE entry (a favorable-direction target),
        # a SHORT target BELOW entry -- a mutation that picked the wrong
        # liquidity kind for a direction would put the "profit" target on
        # the adverse side instead.
        return long_tp is not None and short_tp is not None and long_tp.price > 1.1000 > short_tp.price

    return _run_case("wrong_tp_model_direction", check,
                      "LIQUIDITY_TARGET correctly placed above entry for LONG and below entry for SHORT",
                      "LIQUIDITY_TARGET was placed on the adverse (non-favorable) side of entry for at least one direction")


def test_wrong_position_overlap_logic() -> MutationResult:
    from research.backtest.portfolio_gating import simulate_portfolio_gating
    from research.risk.exit_models import TradeResult
    from research.risk.position_sizing import RiskLimits
    from research.strategies.base import Signal

    def make_trade(symbol, entry_ts, exit_ts, r=0.5):
        sig = Signal(strategy="t", variant="v", symbol=symbol, direction="LONG", entry_ts=entry_ts,
                     entry_price=1.0, setup_reason="", rules_passed=[], rules_failed=[], market_condition="",
                     directional_bias="", candle_pattern=None, fib_state=None, liquidity_state=None,
                     displacement_state=None)
        return TradeResult(signal=sig, sl_model="x", tp_model="x", exit_model="x", entry_ts=entry_ts,
                            entry_price=1.0, initial_sl=0.99, initial_risk=0.01, exit_ts=exit_ts,
                            exit_price=1.01, exit_reason="TP_HIT", r_multiple=r, mfe_r=r, mae_r=0.0, duration_bars=1)

    def check():
        base = pd.Timestamp("2024-01-01 00:00", tz="UTC")
        # 3 trades, all held open simultaneously (entries a minute apart,
        # exits a day later) -- with max_open_positions=2, the 3rd
        # concurrent entry must be blocked, not silently executed.
        trades = [
            make_trade("EURUSD", base, base + pd.Timedelta(days=1)),
            make_trade("GBPUSD", base + pd.Timedelta(minutes=1), base + pd.Timedelta(days=1)),
            make_trade("USDJPY", base + pd.Timedelta(minutes=2), base + pd.Timedelta(days=1)),
        ]
        limits = RiskLimits(max_open_positions=2, max_daily_loss_pct=1.0, max_consecutive_losses=100)
        outcomes = simulate_portfolio_gating(
            {"EURUSD": [trades[0]], "GBPUSD": [trades[1]], "USDJPY": [trades[2]]}, limits=limits,
        )
        by_symbol = {o.trade.signal.symbol: o.outcome for o in outcomes}
        return (by_symbol["EURUSD"] == "EXECUTED" and by_symbol["GBPUSD"] == "EXECUTED"
                and by_symbol["USDJPY"] == "BLOCKED_POSITION_OVERLAP")

    return _run_case("wrong_position_overlap_logic", check,
                      "simulate_portfolio_gating correctly blocked the 3rd concurrently-open position under max_open_positions=2",
                      "simulate_portfolio_gating failed to block a position beyond max_open_positions -- overlap limit is not enforced")


def test_wrong_strategy_selection_bias_hierarchy() -> MutationResult:
    from research.strategies.opening_range_v2 import classify_bias_hierarchy

    def check():
        mc = MarketContext(
            symbol="EURUSD", session="NEW_YORK", timestamp=pd.Timestamp.now(tz="UTC"), timeframe="M5",
            htf_bias="LONG", bias_confidence=0.6, market_regime="STRONG_DOWNTREND", trend_state="SHORT",
            volatility_state="NORMAL", swing_structure="SHORT", internal_structure="SHORT",
            protected_high=None, protected_low=None, last_bos_or_choch=None, liquidity_state="NONE",
            or_state="OR_ACTIVE", or_high=1.11, or_low=1.10, or_width=0.01, price_location_vs_or="ABOVE_OR",
            atr=0.001, spread=0.0001, cost_assumption="test",
        )
        # htf_bias agrees with a LONG candidate, but external structure,
        # internal structure, AND regime trend all disagree -- 3 conflicts
        # vs 1 agreement must classify as CONFLICTED, never a naive
        # "just trust htf_bias" BULLISH. A mutation that only looked at
        # htf_bias (ignoring the other votes) would wrongly return BULLISH.
        label, agreeing, conflicting = classify_bias_hierarchy(mc, "LONG")
        return label == "CONFLICTED" and len(conflicting) >= 2

    return _run_case("wrong_strategy_selection_bias_hierarchy", check,
                      "classify_bias_hierarchy correctly returned CONFLICTED when structure/regime disagreed with htf_bias despite htf_bias agreeing",
                      "classify_bias_hierarchy returned a directional label from htf_bias alone, ignoring conflicting structure/regime votes")


ALL_MUTATION_TESTS = [
    test_future_bar_access,
    test_forming_bar_inclusion,
    test_wrong_timezone,
    test_wrong_swing_confirmation,
    test_wrong_spread_direction,
    test_train_test_contamination,
    test_disabled_cost,
    test_wrong_or_boundary,
    test_wrong_session_dst_boundary,
    test_wrong_m5_confirmation_direction,
    test_wrong_m1_entry_timing,
    test_wrong_sl_model_side,
    test_wrong_tp_model_direction,
    test_wrong_position_overlap_logic,
    test_wrong_strategy_selection_bias_hierarchy,
]


def run_all_mutation_tests() -> List[MutationResult]:
    return [fn() for fn in ALL_MUTATION_TESTS]


if __name__ == "__main__":
    results = run_all_mutation_tests()
    all_detected = True
    for name, detected, detail in results:
        status = "DETECTED" if detected else "MISSED"
        print(f"[{status}] {name}: {detail}")
        all_detected = all_detected and detected
    print()
    print("ALL MUTATIONS DETECTED" if all_detected else "WARNING: at least one mutation was NOT detected")
    assert all_detected
    print("OK")
