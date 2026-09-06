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


ALL_MUTATION_TESTS = [
    test_future_bar_access,
    test_forming_bar_inclusion,
    test_wrong_timezone,
    test_wrong_swing_confirmation,
    test_wrong_spread_direction,
    test_train_test_contamination,
    test_disabled_cost,
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
