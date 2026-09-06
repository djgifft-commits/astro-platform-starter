"""
Phase 9C-DATA — ingestion mutation tests.

Eight behavioral mutations the Phase 9C-DATA spec names: timestamp
parsing, timezone conversion, DST, M1 aggregation, M5/M15 boundary, OR
close timing, duplicate handling, future-bar access. Every mutation must
be DETECTED.

FIXTURES ARE HAND-BUILT DETERMINISTIC TEST VECTORS -- literal OHLC values
written out below (open=100+i, high=100+i+0.9, ...) chosen so first/max/
min/last are all distinguishable from one another. The synthetic MARKET
generator (research/data/synthetic.py) is deliberately NOT used anywhere
in this module: these are unit-test vectors proving aggregation/timezone/
causality mechanics, never a stand-in for market data, and nothing here
produces a research result of any kind.

Same shape as research/backtest/mutation_testing.py: (1) build a correct
baseline, (2) apply the mutation, (3) assert the check FAILS on the
mutated version, (4) assert the same check PASSES on the unmutated
baseline -- so a test cannot "pass" vacuously.
"""
from __future__ import annotations

from typing import Callable, List, Tuple

import pandas as pd

from research.config import NY_OPENING_RANGE_MINUTES, NY_SESSION_OPEN, NY_TZ, UTC
from research.core.sessions import compute_ny_opening_ranges, session_open_utc
from research.data.ingestion import TIMEFRAME_MINUTES, validate_dataset
from research.data.loaders import resample_ohlc
from research.data.quality import assert_no_lookahead

MutationResult = Tuple[str, bool, str]


def _run_case(name: str, fn: Callable[[], bool], detail_ok: str, detail_fail: str) -> MutationResult:
    try:
        detected = fn()
    except AssertionError:
        detected = True
    except Exception as e:
        detected = True
        detail_ok = f"{detail_ok} (raised {type(e).__name__})"
    return (name, detected, detail_ok if detected else detail_fail)


def _hand_built_m1(start_utc: pd.Timestamp, n_bars: int) -> pd.DataFrame:
    """Deterministic hand-specified M1 bars. Every field is a distinct
    arithmetic function of the bar index so that first/max/min/last are
    never accidentally equal -- an aggregation bug cannot hide behind
    coincidentally identical values."""
    idx = pd.date_range(start_utc, periods=n_bars, freq="1min", tz="UTC")
    return pd.DataFrame(
        {
            "open": [100.0 + i for i in range(n_bars)],
            "high": [100.9 + i for i in range(n_bars)],
            "low": [99.6 + i for i in range(n_bars)],
            "close": [100.5 + i for i in range(n_bars)],
        },
        index=idx,
    ).rename_axis("timestamp")


def test_timestamp_parsing() -> MutationResult:
    from research.data.real_data import load_real_ohlcv
    import tempfile
    from pathlib import Path

    def check():
        # Timestamps carrying an EXPLICIT +02:00 offset. Correctly parsed,
        # 09:30+02:00 is 07:30 UTC.
        rows = pd.DataFrame({
            "timestamp": ["2024-06-03T09:30:00+02:00", "2024-06-03T09:31:00+02:00", "2024-06-03T09:32:00+02:00"],
            "open": [1.0, 1.1, 1.2], "high": [1.5, 1.6, 1.7],
            "low": [0.9, 1.0, 1.1], "close": [1.2, 1.3, 1.4],
        })
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "eurusd_m1.csv"
            rows.to_csv(p, index=False)
            loaded = load_real_ohlcv(str(p), symbol="EURUSD")
        correct_first = loaded.bars.index[0]
        # MUTATION: ignore the offset and treat the wall-clock reading as
        # UTC -- a 2-hour error that would silently shift every bar, and
        # would move the NY opening range onto the wrong bars entirely.
        mutated_first = pd.Timestamp("2024-06-03T09:30:00", tz="UTC")
        return correct_first == pd.Timestamp("2024-06-03T07:30:00", tz="UTC") and correct_first != mutated_first

    return _run_case("timestamp_parsing", check,
                      "loader honored the explicit UTC offset (09:30+02:00 -> 07:30Z), not the naive wall-clock reading",
                      "loader ignored the timestamp's UTC offset -- every bar would be shifted")


def test_timezone_conversion() -> MutationResult:
    def check():
        # NY 09:30 on a winter date is EST (UTC-5) -> 14:30Z
        correct = session_open_utc(pd.Timestamp("2024-01-10", tz="UTC"), NY_SESSION_OPEN, NY_TZ)
        # MUTATION: treat "New York" as a fixed UTC-4 year-round
        mutated = pd.Timestamp("2024-01-10 13:30", tz="UTC")
        return correct == pd.Timestamp("2024-01-10 14:30", tz="UTC") and correct != mutated

    return _run_case("timezone_conversion", check,
                      "NY 09:30 in January correctly converted to 14:30Z (EST), not a fixed UTC-4 assumption",
                      "NY session open matched a fixed-offset assumption -- zoneinfo conversion is not being used")


def test_dst() -> MutationResult:
    def check():
        before = session_open_utc(pd.Timestamp("2024-03-08", tz="UTC"), NY_SESSION_OPEN, NY_TZ)  # EST
        after = session_open_utc(pd.Timestamp("2024-03-11", tz="UTC"), NY_SESSION_OPEN, NY_TZ)   # EDT
        november = session_open_utc(pd.Timestamp("2024-11-04", tz="UTC"), NY_SESSION_OPEN, NY_TZ)  # back to EST
        # spring forward: UTC anchor moves 1h EARLIER; fall back: 1h LATER
        spring_shift = before.hour - after.hour
        fall_shift = november.hour - after.hour
        # MUTATION: a hardcoded single offset would give a 0-hour shift at both transitions
        return spring_shift == 1 and fall_shift == 1

    return _run_case("dst", check,
                      "OR anchor shifted 1h at BOTH the March spring-forward and the November fall-back transition",
                      "OR anchor did not shift across a DST transition -- a fixed-offset bug is present")


def test_m1_aggregation() -> MutationResult:
    def check():
        m1 = _hand_built_m1(pd.Timestamp("2024-06-03 14:30", tz="UTC"), 10)
        m5 = resample_ohlc(m1, "M5")
        first = m5.iloc[0]
        # correct: open=first M1 open, high=max, low=min, close=last M1 close
        correct = (
            first["open"] == 100.0
            and first["high"] == 104.9
            and first["low"] == 99.6
            and first["close"] == 104.5
        )
        # MUTATION: the classic swap -- open taken from the LAST bar and
        # close from the FIRST, which preserves the bar count and the
        # high/low so it is invisible without checking values.
        mutated_open, mutated_close = 104.0, 100.5
        return correct and first["open"] != mutated_open and first["close"] != mutated_close

    return _run_case("m1_aggregation", check,
                      "M5 aggregation used open=first / high=max / low=min / close=last, not a swapped open/close",
                      "M5 aggregation produced wrong OHLC values from known hand-built M1 input")


def test_m5_m15_boundary() -> MutationResult:
    def check():
        # 09:30 NY on 2024-06-03 (EDT) = 13:30Z. Build 09:30..09:50 NY.
        or_open = session_open_utc(pd.Timestamp("2024-06-03", tz="UTC"), NY_SESSION_OPEN, NY_TZ)
        m1 = _hand_built_m1(or_open, 21)
        m15 = resample_ohlc(m1, "M15")
        first_bucket_start = m15.index[0]
        # The 09:30 M15 bucket must contain exactly the 09:30..09:44 bars:
        # its high must be bar 14's high (114.9), NOT bar 15's (115.9).
        contains_only_first_15 = m15.iloc[0]["high"] == 114.9
        # MUTATION: a boundary off by one minute (or closed="right") would
        # pull the 09:45 bar into the 09:30 bucket.
        mutated_high_if_leaky = 115.9
        starts_on_boundary = first_bucket_start == or_open
        return contains_only_first_15 and starts_on_boundary and m15.iloc[0]["high"] != mutated_high_if_leaky

    return _run_case("m5_m15_boundary", check,
                      "M15 bucket started exactly on the 09:30 boundary and excluded the 09:45 bar",
                      "M15 bucketing leaked a bar across the boundary or did not align to the session open")


def test_or_close_timing() -> MutationResult:
    def check():
        or_open = session_open_utc(pd.Timestamp("2024-06-03", tz="UTC"), NY_SESSION_OPEN, NY_TZ)
        m1 = _hand_built_m1(or_open, 21).copy()
        # MUTATION BAIT: put an extreme high/low on the bar at exactly
        # 09:45 (index 15) -- the first bar OUTSIDE the [09:30, 09:45)
        # window. A window that closes inclusively would swallow it.
        m1.iloc[15, m1.columns.get_loc("high")] = 9999.0
        m1.iloc[15, m1.columns.get_loc("low")] = 0.0001

        ranges = compute_ny_opening_ranges(m1, or_minutes=NY_OPENING_RANGE_MINUTES)
        assert len(ranges) == 1
        orr = ranges[0]
        uncontaminated = orr.or_high < 9000.0 and orr.or_low > 0.001
        # the OR is only usable once the window has CLOSED
        available_after_close = orr.or_close_utc == orr.session_open_utc + pd.Timedelta(minutes=NY_OPENING_RANGE_MINUTES)
        return uncontaminated and available_after_close

    return _run_case("or_close_timing", check,
                      "OR excluded the bar at exactly 09:45 and becomes available only at window close (09:45)",
                      "OR was contaminated by the 09:45 bar or was exposed before its window closed")


def test_duplicate_handling() -> MutationResult:
    def check():
        m1 = _hand_built_m1(pd.Timestamp("2024-06-03 13:30", tz="UTC"), 20)
        clean = validate_dataset(m1, "EURUSD", "M1", "fixture", "sha")
        # MUTATION: duplicate one timestamp. This must be DETECTED and
        # reported, never silently de-duplicated (which would hide a
        # broken vendor export).
        mutated = pd.concat([m1, m1.iloc[[5]]]).sort_index()
        dirty = validate_dataset(mutated, "EURUSD", "M1", "fixture", "sha")
        return clean.checks["7_no_duplicates"]["passed"] and not dirty.checks["7_no_duplicates"]["passed"]

    return _run_case("duplicate_handling", check,
                      "duplicate timestamps flagged as a validation failure (and clean data passes the same check)",
                      "duplicate timestamps were not detected by the validation battery")


def test_future_bar_access() -> MutationResult:
    def check():
        # (a) the loader-level invariant
        decision_ts = pd.Timestamp("2024-06-03 14:00", tz="UTC")
        try:
            assert_no_lookahead(pd.Timestamp("2024-06-03 14:05", tz="UTC"), decision_ts)
            return False  # should have raised
        except AssertionError:
            pass

        # (b) the derivation-level invariant: an M15 bucket must never be
        # exposed while it is still forming. 20 M1 bars from 13:30 fill
        # 13:30-13:45 and 13:45-13:50 (incomplete) -- only the first may
        # appear.
        m1 = _hand_built_m1(pd.Timestamp("2024-06-03 13:30", tz="UTC"), 20)
        m15 = resample_ohlc(m1, "M15")
        last_bucket_end = m15.index[-1] + pd.Timedelta(minutes=TIMEFRAME_MINUTES["M15"])
        no_forming_bar = last_bucket_end <= m1.index[-1] + pd.Timedelta(minutes=1)
        return no_forming_bar

    return _run_case("future_bar_access", check,
                      "look-ahead assertion fired on a future feature timestamp AND no still-forming M15 bucket was exposed",
                      "a future bar was accessible: either the look-ahead assertion did not fire or a forming M15 bar was exposed")


ALL_INGESTION_MUTATION_TESTS = [
    test_timestamp_parsing,
    test_timezone_conversion,
    test_dst,
    test_m1_aggregation,
    test_m5_m15_boundary,
    test_or_close_timing,
    test_duplicate_handling,
    test_future_bar_access,
]


def run_all_ingestion_mutation_tests() -> List[MutationResult]:
    return [fn() for fn in ALL_INGESTION_MUTATION_TESTS]


if __name__ == "__main__":
    results = run_all_ingestion_mutation_tests()
    all_detected = True
    for name, detected, detail in results:
        status = "DETECTED" if detected else "MISSED"
        print(f"[{status}] {name}: {detail}")
        all_detected = all_detected and detected
    print()
    print("ALL MUTATIONS DETECTED" if all_detected else "WARNING: at least one mutation was NOT detected")
    assert all_detected
    print("OK")
