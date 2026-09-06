"""
Phase 17 — Market session engine (timezone-aware, DST-correct).

Session_open is expressed as a LOCAL exchange time in a named IANA
timezone and converted to UTC per-day via zoneinfo, so New York's 09:30
open lands on a different UTC instant either side of the US DST
transition. This module NEVER hard-codes "09:30 ET" as a fixed UTC
offset (Phase 2 requirement).
"""
from __future__ import annotations

import dataclasses
from typing import List, Optional

import pandas as pd

from research.config import LONDON_TZ, NY_SESSION_OPEN, NY_TZ, NY_OPENING_RANGE_MINUTES, UTC

ASIA_TZ = "Asia/Tokyo"
SYDNEY_TZ = "Australia/Sydney"


def session_open_utc(date: pd.Timestamp, local_time: str = NY_SESSION_OPEN, tz=NY_TZ) -> pd.Timestamp:
    """Convert a LOCAL session-open time on a given calendar date to UTC,
    correctly handling DST for that specific date."""
    hh, mm = (int(x) for x in local_time.split(":"))
    naive = pd.Timestamp(date.year, date.month, date.day, hh, mm)
    local = naive.tz_localize(tz)
    return local.tz_convert(UTC)


def detect_dst_transitions(dates: pd.DatetimeIndex, tz=NY_TZ, local_time: str = NY_SESSION_OPEN) -> List[pd.Timestamp]:
    """Return the dates on which the UTC offset of `local_time` in `tz`
    changes vs. the previous calendar day (Phase 2: 'record DST
    transitions explicitly')."""
    hh, mm = (int(x) for x in local_time.split(":"))

    def _offset(d: pd.Timestamp):
        naive = pd.Timestamp(d.year, d.month, d.day, hh, mm)
        return naive.tz_localize(tz).utcoffset()

    offsets = [_offset(d) for d in dates]
    transitions = []
    for i in range(1, len(offsets)):
        if offsets[i] != offsets[i - 1]:
            transitions.append(dates[i])
    return transitions


def _local_hour(ts_utc: pd.DatetimeIndex, tz) -> pd.Index:
    return ts_utc.tz_convert(tz).hour + ts_utc.tz_convert(tz).minute / 60.0


def classify_session(index_utc: pd.DatetimeIndex) -> pd.Series:
    """Classify each UTC timestamp into SYDNEY / ASIA / LONDON / NEW_YORK /
    LONDON_NY_OVERLAP / OFF_HOURS using real local-time windows per venue.
    A timestamp can fall in more than one venue window; overlap is called
    out explicitly, otherwise venue precedence is LONDON_NY_OVERLAP >
    NEW_YORK > LONDON > ASIA > SYDNEY > OFF_HOURS (Sydney is listed last
    because its trading hours are almost entirely subsumed by the Asia
    window; it is only distinguishable in the early Asia pre-Tokyo-open
    hours)."""
    sydney_h = _local_hour(index_utc, SYDNEY_TZ)
    asia_h = _local_hour(index_utc, ASIA_TZ)
    london_h = _local_hour(index_utc, LONDON_TZ)
    ny_h = _local_hour(index_utc, NY_TZ)

    in_sydney = (sydney_h >= 8) & (sydney_h < 17)
    in_asia = (asia_h >= 9) & (asia_h < 18)
    in_london = (london_h >= 8) & (london_h < 17)
    in_ny = (ny_h >= 8) & (ny_h < 17)
    overlap = in_london & in_ny

    out = pd.Series("OFF_HOURS", index=index_utc)
    out[in_sydney] = "SYDNEY"
    out[in_asia] = "ASIA"
    out[in_london] = "LONDON"
    out[in_ny] = "NEW_YORK"
    out[overlap] = "LONDON_NY_OVERLAP"
    return out.rename("session")


@dataclasses.dataclass
class OpeningRange:
    date: pd.Timestamp
    session_open_utc: pd.Timestamp
    or_close_utc: pd.Timestamp
    or_high: float
    or_low: float
    or_mid: float
    or_range_size: float
    or_body_ratio: float
    or_upper_wick: float
    or_lower_wick: float
    sufficient_data: bool


def compute_ny_opening_ranges(
    m1: pd.DataFrame,
    or_minutes: int = NY_OPENING_RANGE_MINUTES,
) -> List[OpeningRange]:
    """First `or_minutes` of M1 bars after each day's NY 09:30 local open,
    aggregated into one synthetic candle. Causal by construction: only uses
    bars inside [open, open + or_minutes)."""
    if m1.empty:
        return []
    dates = pd.DatetimeIndex(sorted(set(m1.index.tz_convert(NY_TZ).normalize())))
    ranges: List[OpeningRange] = []
    for d in dates:
        open_utc = session_open_utc(d, NY_SESSION_OPEN, NY_TZ)
        close_utc = open_utc + pd.Timedelta(minutes=or_minutes)
        window = m1.loc[(m1.index >= open_utc) & (m1.index < close_utc)]
        sufficient = len(window) >= or_minutes
        if len(window) == 0:
            continue
        o = window["open"].iloc[0]
        c = window["close"].iloc[-1]
        h = window["high"].max()
        l = window["low"].min()
        rng = h - l
        body = abs(c - o)
        ranges.append(
            OpeningRange(
                date=d,
                session_open_utc=open_utc,
                or_close_utc=close_utc,
                or_high=h,
                or_low=l,
                or_mid=(h + l) / 2.0,
                or_range_size=rng,
                or_body_ratio=(body / rng) if rng > 0 else 0.0,
                or_upper_wick=(h - max(o, c)),
                or_lower_wick=(min(o, c) - l),
                sufficient_data=sufficient,
            )
        )
    return ranges


if __name__ == "__main__":
    from research.data.synthetic import generate_multi_symbol_dataset

    ds = generate_multi_symbol_dataset(["EURUSD"], n_days=30)
    m1 = ds["EURUSD"].bars

    sess = classify_session(m1.index)
    print(sess.value_counts())

    ors = compute_ny_opening_ranges(m1)
    print(f"{len(ors)} opening ranges computed")
    print(ors[0])
    assert all(r.or_high >= r.or_low for r in ors)
    assert all(r.sufficient_data for r in ors), "all should be sufficient in clean synthetic data"

    dst_dates = pd.date_range("2024-01-01", "2024-12-31", freq="D", tz=UTC)
    transitions = detect_dst_transitions(dst_dates)
    print("DST transitions detected:", transitions)
    assert len(transitions) == 2, "US DST has exactly 2 transitions/year"
    print("OK")
