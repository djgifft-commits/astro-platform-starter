"""
Phase 2 — Data quality / causality audit.

Runs structural checks on a bar DataFrame and returns a report dict. This
module never raises on a finding; it records the finding so the caller can
decide (typically: log it into the audit report) rather than silently
passing or crashing mid-experiment.
"""
from __future__ import annotations

import dataclasses
from typing import Any, Dict, List

import pandas as pd


@dataclasses.dataclass
class QualityReport:
    symbol: str
    timeframe: str
    n_bars: int
    n_duplicate_timestamps: int
    n_missing_bars: int
    n_ohlc_violations: int
    n_non_monotonic: int
    tz_aware: bool
    first_ts: pd.Timestamp
    last_ts: pd.Timestamp
    notes: List[str]

    def to_dict(self) -> Dict[str, Any]:
        d = dataclasses.asdict(self)
        d["first_ts"] = str(self.first_ts)
        d["last_ts"] = str(self.last_ts)
        return d


def audit_bars(df: pd.DataFrame, symbol: str, timeframe: str, expected_freq_minutes: int) -> QualityReport:
    notes: List[str] = []

    tz_aware = df.index.tz is not None
    if not tz_aware:
        notes.append("INDEX_NOT_TZ_AWARE: causal session logic requires tz-aware timestamps.")

    n_dupe = int(df.index.duplicated().sum())
    if n_dupe:
        notes.append(f"{n_dupe} duplicate timestamps found.")

    is_monotonic = df.index.is_monotonic_increasing
    n_non_monotonic = 0 if is_monotonic else 1
    if not is_monotonic:
        notes.append("Index is not monotonically increasing.")

    ohlc_violations = 0
    if {"open", "high", "low", "close"}.issubset(df.columns):
        high_ok = df["high"] >= df[["open", "close", "low"]].max(axis=1)
        low_ok = df["low"] <= df[["open", "close", "high"]].min(axis=1)
        ohlc_violations = int((~high_ok).sum() + (~low_ok).sum())
        if ohlc_violations:
            notes.append(f"{ohlc_violations} OHLC integrity violations (high/low outside open/close/range).")
    else:
        notes.append("Missing OHLC columns; integrity check skipped.")

    n_missing = 0
    if is_monotonic and len(df) > 1:
        expected = pd.date_range(df.index[0], df.index[-1], freq=f"{expected_freq_minutes}min", tz=df.index.tz)
        n_missing = int(len(expected) - len(expected.intersection(df.index)))
        if n_missing:
            notes.append(
                f"{n_missing} expected bars missing within the observed span "
                f"(weekday-only calendar can explain most of this; investigate if it exceeds the weekend gap count)."
            )

    if not notes:
        notes.append("No issues detected.")

    return QualityReport(
        symbol=symbol,
        timeframe=timeframe,
        n_bars=len(df),
        n_duplicate_timestamps=n_dupe,
        n_missing_bars=n_missing,
        n_ohlc_violations=ohlc_violations,
        n_non_monotonic=n_non_monotonic,
        tz_aware=tz_aware,
        first_ts=df.index[0] if len(df) else pd.NaT,
        last_ts=df.index[-1] if len(df) else pd.NaT,
        notes=notes,
    )


def assert_no_lookahead(feature_timestamp: pd.Timestamp, decision_timestamp: pd.Timestamp) -> None:
    """FEATURE_TIMESTAMP <= DECISION_TIMESTAMP, enforced as a hard invariant."""
    if feature_timestamp > decision_timestamp:
        raise AssertionError(
            f"LOOKAHEAD VIOLATION: feature_timestamp={feature_timestamp} > decision_timestamp={decision_timestamp}"
        )


def assert_outcome_after_decision(outcome_timestamp: pd.Timestamp, decision_timestamp: pd.Timestamp) -> None:
    """OUTCOME_TIMESTAMP > DECISION_TIMESTAMP, enforced as a hard invariant."""
    if outcome_timestamp <= decision_timestamp:
        raise AssertionError(
            f"CAUSALITY VIOLATION: outcome_timestamp={outcome_timestamp} <= decision_timestamp={decision_timestamp}"
        )


if __name__ == "__main__":
    from research.data.synthetic import generate_multi_symbol_dataset

    ds = generate_multi_symbol_dataset(["EURUSD"], n_days=5)
    report = audit_bars(ds["EURUSD"].bars, "EURUSD", "M1", 1)
    print(report.to_dict())
    assert report.n_ohlc_violations == 0
    assert report.tz_aware
    print("OK")
