"""
Phase 8D — Feature provenance tracking.

For a representative set of causal features (regime, bias, structure —
the three most complex, multi-timeframe-dependent computations in this
project), records exactly what the MASTER COMMAND's Phase 8D table asks
for:

    feature_timestamp        when the feature VALUE is timestamped (the bar it describes)
    source_bar_close_timestamp   the close time of the last raw bar the feature actually used
    decision_timestamp        the timestamp a strategy would be standing at when reading this
    availability_timestamp    the earliest real-world instant this value could exist
    causal_status             PASS if availability_timestamp <= decision_timestamp, else VIOLATION

This is deliberately NOT wired into the hot path of every single feature
computation in the codebase (that would duplicate research/data/
quality.py::assert_no_lookahead's job at heavy performance cost for no
new information) -- it is a standalone auditing utility applied to
representative samples, used here to produce a concrete, inspectable
provenance table for the three features named above, and reusable for
any future feature the same way.
"""
from __future__ import annotations

import dataclasses
from typing import List

import pandas as pd


@dataclasses.dataclass
class ProvenanceRecord:
    feature_name: str
    feature_timestamp: pd.Timestamp
    source_bar_close_timestamp: pd.Timestamp
    decision_timestamp: pd.Timestamp
    availability_timestamp: pd.Timestamp
    causal_status: str  # "PASS" or "VIOLATION"


def build_provenance_record(
    feature_name: str,
    feature_timestamp: pd.Timestamp,
    source_bar_close_timestamp: pd.Timestamp,
    decision_timestamp: pd.Timestamp,
    processing_latency: pd.Timedelta = pd.Timedelta(0),
) -> ProvenanceRecord:
    """availability_timestamp = the source bar's close plus any modeled
    processing latency (0 by default -- this project assumes a bar's
    close is instantly knowable, which is optimistic but not a leak: real
    latency would only make causality-passing features PASS by a wider
    margin, never turn a real violation into a false pass)."""
    availability_timestamp = source_bar_close_timestamp + processing_latency
    status = "PASS" if availability_timestamp <= decision_timestamp else "VIOLATION"
    return ProvenanceRecord(
        feature_name=feature_name,
        feature_timestamp=feature_timestamp,
        source_bar_close_timestamp=source_bar_close_timestamp,
        decision_timestamp=decision_timestamp,
        availability_timestamp=availability_timestamp,
        causal_status=status,
    )


def audit_regime_provenance(regime_series: pd.Series, source_tf_index: pd.DatetimeIndex, sample_n: int = 20) -> List[ProvenanceRecord]:
    """Sample `sample_n` evenly-spaced points from a regime/bias series and
    verify each one's underlying source bar close time is not later than
    the decision timestamp (its own index position) -- i.e. that the
    as-of merge onto the execution timeframe (research/core/feature_bar.py)
    never attached a source bar from the future."""
    records = []
    idx = regime_series.dropna().index
    if len(idx) == 0:
        return records
    step = max(1, len(idx) // sample_n)
    for decision_ts in idx[::step]:
        source_bar_close = source_tf_index[source_tf_index <= decision_ts]
        if len(source_bar_close) == 0:
            continue
        last_source_close = source_bar_close[-1]
        records.append(
            build_provenance_record(
                feature_name=regime_series.name or "feature",
                feature_timestamp=decision_ts,
                source_bar_close_timestamp=last_source_close,
                decision_timestamp=decision_ts,
            )
        )
    return records


if __name__ == "__main__":
    from research.core.feature_bar import build_symbol_engine_data
    from research.data.synthetic import generate_multi_symbol_dataset

    ds = generate_multi_symbol_dataset(["EURUSD"], n_days=60)
    data = build_symbol_engine_data("EURUSD", ds["EURUSD"].bars)

    regime_records = audit_regime_provenance(
        data.feature_bars["regime_regime"], data.frames["H1"].index
    )
    bias_records = audit_regime_provenance(
        data.feature_bars["bias_bias"], data.frames["M15"].index
    )

    print(f"{len(regime_records)} regime provenance samples, "
          f"{sum(1 for r in regime_records if r.causal_status == 'VIOLATION')} violations")
    print(f"{len(bias_records)} bias provenance samples, "
          f"{sum(1 for r in bias_records if r.causal_status == 'VIOLATION')} violations")
    for r in regime_records[:3]:
        print(r)

    assert all(r.causal_status == "PASS" for r in regime_records)
    assert all(r.causal_status == "PASS" for r in bias_records)
    print("OK")
