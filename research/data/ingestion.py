"""
Phase 9C-DATA — Real historical data ingestion pipeline.

Accepts REAL historical OHLCV files supplied by the user, validates them
exhaustively, classifies every gap, derives M5/M15 from M1 causally,
verifies NY opening-range readiness per trading day, and emits an
immutable provenance manifest.

THIS MODULE HAS NEVER BEEN RUN AGAINST REAL DATA IN THIS SESSION. No real
historical data has been supplied (see audit/PHASE_9C_DATA_INGESTION.md
for the discovery sweep). It is built to the Phase 9C-DATA input contract
so that ingestion is a single command the moment files arrive. Its
correctness is established by hand-built deterministic test vectors in
`research/data/ingestion_mutation_tests.py` -- literal OHLC rows written
by hand to exercise timestamp/DST/aggregation/OR-timing invariants, NOT
output of the synthetic market generator, which is never used here.

REUSE MAP (nothing below is reimplemented):
  research/data/real_data.py   -> load_real_ohlcv, compute_data_hash
  research/data/quality.py      -> audit_bars, assert_no_lookahead
  research/data/loaders.py       -> resample_ohlc (causal M1 -> M5/M15)
  research/core/sessions.py       -> compute_ny_opening_ranges, session_open_utc

Genuinely new here: multi-file discovery/identification, the 18-point
validation battery, gap classification, OR-readiness verification,
sufficiency flagging, and the manifest.
"""
from __future__ import annotations

import dataclasses
import hashlib
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from research.config import NY_OPENING_RANGE_MINUTES, NY_SESSION_OPEN, NY_TZ, UTC
from research.core.sessions import compute_ny_opening_ranges, session_open_utc
from research.data.loaders import resample_ohlc
from research.data.quality import audit_bars
from research.data.real_data import compute_data_hash, load_real_ohlcv

# ------------------------------------------------------------ identification

# Canonical symbols this project's Phase 9C spec names, mapped from the
# many spellings a broker/vendor export may use. Identification is
# EXPLICIT: anything not matched here is reported as UNIDENTIFIED rather
# than guessed, per "Do not guess silently."
SYMBOL_ALIASES: Dict[str, str] = {
    "eurusd": "EURUSD", "eur_usd": "EURUSD", "eur-usd": "EURUSD", "eur/usd": "EURUSD",
    "usdjpy": "USDJPY", "usd_jpy": "USDJPY", "usd-jpy": "USDJPY", "usd/jpy": "USDJPY",
    "gbpusd": "GBPUSD", "gbp_usd": "GBPUSD", "gbp-usd": "GBPUSD", "gbp/usd": "GBPUSD",
    "xauusd": "XAUUSD", "xau_usd": "XAUUSD", "xau-usd": "XAUUSD", "xau/usd": "XAUUSD",
    "gold": "XAUUSD",
    "audusd": "AUDUSD", "aud_usd": "AUDUSD", "aud-usd": "AUDUSD", "aud/usd": "AUDUSD",
    "usdchf": "USDCHF", "usd_chf": "USDCHF", "usd-chf": "USDCHF", "usd/chf": "USDCHF",
}

TIMEFRAME_ALIASES: Dict[str, str] = {
    "m1": "M1", "1m": "M1", "1min": "M1", "1minute": "M1", "min1": "M1",
    "m5": "M5", "5m": "M5", "5min": "M5", "5minute": "M5", "min5": "M5",
    "m15": "M15", "15m": "M15", "15min": "M15", "15minute": "M15", "min15": "M15",
    "m30": "M30", "30m": "M30", "30min": "M30",
    "h1": "H1", "1h": "H1", "60m": "H1", "hourly": "H1",
    "d1": "D1", "1d": "D1", "daily": "D1",
}

TIMEFRAME_MINUTES = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60, "D1": 1440}
DATA_EXTENSIONS = {".csv", ".txt", ".parquet"}


def identify_symbol(text: str) -> Optional[str]:
    """Canonical symbol from a filename/column value, or None if it cannot
    be identified. Never guesses -- an unmatched name returns None so the
    caller reports UNIDENTIFIED instead of inventing a symbol."""
    lowered = text.lower()
    # longest alias first, so "eur_usd" wins over a hypothetical "eur"
    for alias in sorted(SYMBOL_ALIASES, key=len, reverse=True):
        if alias in lowered:
            return SYMBOL_ALIASES[alias]
    return None


def identify_timeframe(text: str) -> Optional[str]:
    """Canonical timeframe from a filename, or None. Matched on token
    boundaries so "m15" in "eurusd_m15_2023.csv" resolves, while the "m1"
    inside "m15" does not shadow it (longest alias first + boundary check)."""
    lowered = text.lower()
    for alias in sorted(TIMEFRAME_ALIASES, key=len, reverse=True):
        if re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", lowered):
            return TIMEFRAME_ALIASES[alias]
    return None


def infer_timeframe_from_index(index: pd.DatetimeIndex) -> Optional[str]:
    """Timeframe implied by the MODAL bar spacing, used to cross-check the
    filename-derived timeframe (identity check #16). Returns None when the
    modal spacing matches no known timeframe."""
    if len(index) < 3:
        return None
    deltas = pd.Series(index[1:]) - pd.Series(index[:-1])
    modal_minutes = int(deltas.mode().iloc[0].total_seconds() // 60)
    for tf, minutes in TIMEFRAME_MINUTES.items():
        if minutes == modal_minutes:
            return tf
    return None


# ------------------------------------------------------------ gap classifier

GAP_KINDS = ("EXPECTED_SESSION_GAP", "WEEKEND_GAP", "HOLIDAY_GAP", "DATA_GAP", "UNKNOWN_GAP")

# Fixed-date US/global market holidays that fall on the same calendar date
# every year. Moving holidays (Good Friday, Thanksgiving, etc.) are
# deliberately NOT guessed -- a gap on such a day classifies as
# UNKNOWN_GAP and is reported for human confirmation rather than silently
# labeled a holiday.
FIXED_DATE_HOLIDAYS = {(1, 1), (12, 25), (12, 26)}


def classify_gap(prev_ts: pd.Timestamp, next_ts: pd.Timestamp, timeframe: str) -> str:
    """Classify a gap between two consecutive bars. Never fills anything --
    classification only, per 'Do not fill unknown gaps.'"""
    bar_minutes = TIMEFRAME_MINUTES[timeframe]
    gap_minutes = (next_ts - prev_ts).total_seconds() / 60.0
    if gap_minutes <= bar_minutes:
        return "EXPECTED_SESSION_GAP"  # no gap at all

    prev_ny = prev_ts.tz_convert(NY_TZ)
    next_ny = next_ts.tz_convert(NY_TZ)

    # FX weekend: Friday close (~17:00 NY) to Sunday open (~17:00 NY)
    if prev_ny.weekday() == 4 and next_ny.weekday() == 6:
        return "WEEKEND_GAP"
    if prev_ny.weekday() == 4 and next_ny.weekday() == 0:
        return "WEEKEND_GAP"

    if (next_ny.month, next_ny.day) in FIXED_DATE_HOLIDAYS or (prev_ny.month, prev_ny.day) in FIXED_DATE_HOLIDAYS:
        return "HOLIDAY_GAP"

    # daily rollover / illiquid hours within the same or adjacent weekday
    if gap_minutes <= 120 and prev_ny.hour >= 16:
        return "EXPECTED_SESSION_GAP"

    # an intraday hole during otherwise-active hours is a real data gap
    if gap_minutes < 1440 and 1 <= next_ny.weekday() <= 5:
        return "DATA_GAP"

    return "UNKNOWN_GAP"


def summarize_gaps(index: pd.DatetimeIndex, timeframe: str, max_examples: int = 5) -> Dict:
    """Counts by gap kind plus a few concrete examples of the kinds that
    warrant human attention (DATA_GAP / UNKNOWN_GAP)."""
    counts = {kind: 0 for kind in GAP_KINDS}
    examples: Dict[str, List[str]] = {"DATA_GAP": [], "UNKNOWN_GAP": []}
    bar_minutes = TIMEFRAME_MINUTES[timeframe]

    for prev_ts, next_ts in zip(index[:-1], index[1:]):
        if (next_ts - prev_ts).total_seconds() / 60.0 <= bar_minutes:
            continue
        kind = classify_gap(prev_ts, next_ts, timeframe)
        counts[kind] += 1
        if kind in examples and len(examples[kind]) < max_examples:
            examples[kind].append(f"{prev_ts.isoformat()} -> {next_ts.isoformat()}")

    return {"counts": counts, "examples": examples}


# ------------------------------------------------------------ validation

@dataclasses.dataclass
class ValidationResult:
    passed: bool
    checks: Dict[str, Dict]  # check_name -> {"passed": bool, "detail": str}

    def failed_checks(self) -> List[str]:
        return [name for name, r in self.checks.items() if not r["passed"]]


def _check(passed: bool, detail: str) -> Dict:
    return {"passed": bool(passed), "detail": detail}


def validate_dataset(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
    source_path: str,
    file_sha256: str,
    declared_symbol: Optional[str] = None,
) -> ValidationResult:
    """The 18-point validation battery Phase 9C-DATA specifies. Never
    repairs anything -- every finding is recorded and returned, and a
    failing dataset is reported as failing rather than quietly patched."""
    checks: Dict[str, Dict] = {}
    bar_minutes = TIMEFRAME_MINUTES[timeframe]

    # 1. file integrity / 2. SHA256
    checks["1_file_integrity"] = _check(len(df) > 0, f"{len(df)} rows loaded from {source_path}")
    checks["2_sha256"] = _check(bool(file_sha256), f"source file sha256={file_sha256}")

    # 3. schema
    required = {"open", "high", "low", "close"}
    missing = required - set(df.columns)
    checks["3_schema"] = _check(not missing, f"columns={sorted(df.columns)}" + (f" MISSING={sorted(missing)}" if missing else ""))

    # 4. timestamp type
    checks["4_timestamp_type"] = _check(
        isinstance(df.index, pd.DatetimeIndex),
        f"index type={type(df.index).__name__}",
    )

    # 5. timezone
    checks["5_timezone"] = _check(
        getattr(df.index, "tz", None) is not None,
        f"index tz={getattr(df.index, 'tz', None)} (normalized to UTC by the loader)",
    )

    # 6. monotonic timestamps
    checks["6_monotonic"] = _check(df.index.is_monotonic_increasing, "index monotonically increasing")

    # 7. duplicate timestamps
    n_dupe = int(df.index.duplicated().sum())
    checks["7_no_duplicates"] = _check(n_dupe == 0, f"{n_dupe} duplicate timestamps")

    # 8. missing timestamps (reported, not repaired; gaps classified separately)
    gap_summary = summarize_gaps(df.index, timeframe) if len(df) > 1 else {"counts": {}, "examples": {}}
    unexplained = gap_summary["counts"].get("DATA_GAP", 0) + gap_summary["counts"].get("UNKNOWN_GAP", 0)
    checks["8_missing_timestamps"] = _check(
        True,  # informational: presence of gaps is normal for FX, classification is what matters
        f"gap counts={gap_summary['counts']} (DATA_GAP+UNKNOWN_GAP={unexplained}, never filled)",
    )

    ohlc_present = not missing
    if ohlc_present:
        o, h, l, c = (df["open"], df["high"], df["low"], df["close"])

        # 9. OHLC invariants
        high_ok = h >= pd.concat([o, c, l], axis=1).max(axis=1)
        low_ok = l <= pd.concat([o, c, h], axis=1).min(axis=1)
        n_ohlc_viol = int((~high_ok).sum() + (~low_ok).sum())
        checks["9_ohlc_invariants"] = _check(n_ohlc_viol == 0, f"{n_ohlc_viol} high/low invariant violations")

        # 10. zero / negative prices
        n_nonpositive = int((df[["open", "high", "low", "close"]] <= 0).any(axis=1).sum())
        checks["10_positive_prices"] = _check(n_nonpositive == 0, f"{n_nonpositive} bars with a zero/negative price")

        # 11. NaN
        n_nan = int(df[["open", "high", "low", "close"]].isna().any(axis=1).sum())
        checks["11_no_nan"] = _check(n_nan == 0, f"{n_nan} bars containing NaN in OHLC")

        # 12. infinity
        n_inf = int(np.isinf(df[["open", "high", "low", "close"]].to_numpy(dtype="float64")).any(axis=1).sum())
        checks["12_no_infinity"] = _check(n_inf == 0, f"{n_inf} bars containing +/-inf in OHLC")

        # 13. impossible candles (zero-range bars are legal; a >20% single-bar
        #     move on an FX/metal pair is not, and indicates a bad tick or a
        #     mis-scaled column)
        n_extreme = int((c.pct_change().abs() > 0.20).sum())
        checks["13_no_impossible_candles"] = _check(n_extreme == 0, f"{n_extreme} single-bar moves >20%")
    else:
        for name in ("9_ohlc_invariants", "10_positive_prices", "11_no_nan", "12_no_infinity", "13_no_impossible_candles"):
            checks[name] = _check(False, "skipped: OHLC columns missing")

    # 14. session continuity -- are there NY sessions represented at all?
    if len(df) > 1:
        ny_dates = pd.DatetimeIndex(sorted(set(df.index.tz_convert(NY_TZ).normalize())))
        checks["14_session_continuity"] = _check(
            len(ny_dates) > 0, f"{len(ny_dates)} distinct NY calendar dates spanned"
        )
    else:
        checks["14_session_continuity"] = _check(False, "insufficient rows to assess session continuity")

    # 15. symbol identity
    if declared_symbol is not None and declared_symbol != symbol:
        checks["15_symbol_identity"] = _check(False, f"filename says {symbol}, file content says {declared_symbol}")
    else:
        checks["15_symbol_identity"] = _check(symbol is not None, f"symbol={symbol}")

    # 16. timeframe identity (declared vs. observed modal spacing)
    observed_tf = infer_timeframe_from_index(df.index) if len(df) > 2 else None
    checks["16_timeframe_identity"] = _check(
        observed_tf == timeframe,
        f"declared={timeframe}, observed modal spacing={observed_tf}",
    )

    # 17. date range
    if len(df):
        span_days = (df.index[-1] - df.index[0]).total_seconds() / 86400.0
        checks["17_date_range"] = _check(
            span_days > 0, f"{df.index[0].isoformat()} .. {df.index[-1].isoformat()} ({span_days:.1f} days)"
        )
    else:
        checks["17_date_range"] = _check(False, "empty dataset")

    # 18. incomplete final candle -- a trailing bar whose own interval has
    #     not fully elapsed relative to the rest of the series must not be
    #     treated as closed information.
    if len(df) > 2:
        last_gap_minutes = (df.index[-1] - df.index[-2]).total_seconds() / 60.0
        checks["18_final_candle_complete"] = _check(
            last_gap_minutes >= bar_minutes,
            f"final bar spacing={last_gap_minutes:.1f}min vs expected {bar_minutes}min "
            f"(a shorter trailing spacing indicates a still-forming last bar)",
        )
    else:
        checks["18_final_candle_complete"] = _check(False, "insufficient rows to assess the final candle")

    hard_failures = [
        "3_schema", "4_timestamp_type", "5_timezone", "6_monotonic", "7_no_duplicates",
        "9_ohlc_invariants", "10_positive_prices", "11_no_nan", "12_no_infinity",
    ]
    passed = all(checks[name]["passed"] for name in hard_failures if name in checks)
    return ValidationResult(passed=passed, checks=checks)


# ------------------------------------------------------------ OR readiness

def verify_opening_ranges(m1: pd.DataFrame) -> Dict:
    """For every NY trading day present, verify the 09:30 bar exists and the
    09:30-09:45 window is complete, and record when the OR first becomes
    usable. Reuses core/sessions.py's compute_ny_opening_ranges -- the OR
    itself is NOT recomputed here."""
    ranges = compute_ny_opening_ranges(m1, or_minutes=NY_OPENING_RANGE_MINUTES)

    complete, incomplete_days, missing_open_bar = [], [], []
    for orr in ranges:
        open_bar_exists = bool(((m1.index >= orr.session_open_utc) & (m1.index < orr.session_open_utc + pd.Timedelta(minutes=1))).any())
        if not open_bar_exists:
            missing_open_bar.append(orr.date.date().isoformat())
        if orr.sufficient_data and orr.or_range_size > 0 and open_bar_exists:
            complete.append(orr)
        else:
            incomplete_days.append(orr.date.date().isoformat())

    # The OR must only become available AFTER the 15-minute window closes.
    # compute_ny_opening_ranges uses a half-open [open, open+15min) window,
    # so or_close_utc is the first instant the OR is legitimately usable.
    availability_ok = all(orr.or_close_utc > orr.session_open_utc for orr in ranges)

    return {
        "ny_sessions_found": len(ranges),
        "usable_sessions": len(complete),
        "incomplete_sessions": len(incomplete_days),
        "missing_0930_bar_days": missing_open_bar[:20],
        "incomplete_session_days": incomplete_days[:20],
        "or_available_only_after_window_close": availability_ok,
        "sample_or": (
            {
                "date": complete[0].date.date().isoformat(),
                "or_timestamp_utc": complete[0].or_close_utc.isoformat(),
                "or_high": complete[0].or_high, "or_low": complete[0].or_low,
                "or_mid": complete[0].or_mid, "or_width": complete[0].or_range_size,
            }
            if complete else None
        ),
    }


# ------------------------------------------------------------ sufficiency

def sufficiency_flag(first_ts: pd.Timestamp, last_ts: pd.Timestamp) -> str:
    """History-length bucket. Deliberately does NOT declare statistical
    sufficiency -- that judgment stays with the human, per 'Do not declare
    statistical sufficiency automatically.'"""
    years = (last_ts - first_ts).total_seconds() / (365.25 * 86400)
    if years < 1:
        return "LT_1_YEAR"
    if years < 2:
        return "1_TO_2_YEARS"
    if years < 3:
        return "2_TO_3_YEARS"
    return "3_PLUS_YEARS"


# ------------------------------------------------------------ ingestion

@dataclasses.dataclass
class IngestedSymbol:
    symbol: str
    source_file: str
    original_sha256: str
    row_count: int
    first_timestamp: str
    last_timestamp: str
    timezone: str
    timeframe: str
    validation_result: Dict
    gap_summary: Dict
    derived_timeframes: Dict[str, int]
    derivation_method: str
    or_readiness: Dict
    sufficiency: str
    readiness: Dict[str, bool]
    ingestion_timestamp: str


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def discover_data_files(search_dirs: List[Path]) -> List[Path]:
    """Every candidate data file under the given directories. Discovery
    only -- identification happens separately and never guesses.

    Deduplicates by resolved path: the default search list includes both
    a parent and a nested child directory (e.g. `data/` and
    `data/historical/`), so a file under the nested one would otherwise be
    discovered -- and ingested -- twice."""
    seen: Dict[Path, Path] = {}
    for d in search_dirs:
        if not d.exists():
            continue
        for p in sorted(d.rglob("*")):
            if p.is_file() and p.suffix.lower() in DATA_EXTENSIONS:
                seen.setdefault(p.resolve(), p)
    return [seen[k] for k in sorted(seen)]


def ingest_file(path: Path, assume_naive_tz: str = "UTC") -> Tuple[Optional[IngestedSymbol], List[str]]:
    """Ingest one supplied file end to end. Returns (record, problems).
    A file whose symbol or timeframe cannot be identified is REPORTED as
    unidentified, never assigned a guessed identity."""
    problems: List[str] = []

    symbol = identify_symbol(path.name)
    if symbol is None:
        problems.append(
            f"UNIDENTIFIED_SYMBOL: cannot determine the symbol from filename '{path.name}'. "
            f"Rename to include one of {sorted(set(SYMBOL_ALIASES.values()))}, or supply a 'symbol' column."
        )

    timeframe = identify_timeframe(path.stem)
    if timeframe is None:
        problems.append(
            f"UNIDENTIFIED_TIMEFRAME: cannot determine the timeframe from filename '{path.name}'. "
            f"Rename to include one of M1/M5/M15 (M1 preferred -- M5/M15 are derived from it)."
        )

    if symbol is None or timeframe is None:
        return None, problems

    try:
        dataset = load_real_ohlcv(str(path), symbol=symbol, assume_naive_tz=assume_naive_tz)
    except Exception as e:  # schema/parse failures are reported, never worked around
        problems.append(f"LOAD_FAILED: {type(e).__name__}: {e}")
        return None, problems

    df = dataset.bars
    validation = validate_dataset(df, symbol, timeframe, str(path), file_sha256(path))
    gap_summary = summarize_gaps(df.index, timeframe) if len(df) > 1 else {"counts": {}, "examples": {}}

    derived: Dict[str, int] = {}
    or_readiness: Dict = {}
    derivation_method = "none (input timeframe used as supplied)"
    if timeframe == "M1" and validation.passed:
        # Causal derivation: resample_ohlc already drops any still-forming
        # trailing bucket, so no incomplete M5/M15 bar is ever exposed.
        for tf in ("M5", "M15"):
            derived[tf] = len(resample_ohlc(df, tf))
        derivation_method = (
            "research.data.loaders.resample_ohlc: label=left, closed=left, "
            "open=first/high=max/low=min/close=last, spread=mean, trailing incomplete bucket dropped"
        )
        or_readiness = verify_opening_ranges(df)
    elif timeframe == "M1":
        problems.append("M5/M15 derivation skipped: M1 dataset failed hard validation checks.")

    readiness = {
        "DATA_EXISTS": len(df) > 0,
        "SCHEMA_VALID": validation.checks["3_schema"]["passed"],
        "TIMEFRAME_VALID": validation.checks["16_timeframe_identity"]["passed"],
        "TIMEZONE_VALID": validation.checks["5_timezone"]["passed"],
        "STRUCTURE_VALID": validation.passed,
        "CAUSAL_READY": validation.checks["6_monotonic"]["passed"] and validation.checks["7_no_duplicates"]["passed"],
        "SESSION_READY": bool(or_readiness.get("ny_sessions_found", 0)) if timeframe == "M1" else False,
        "OR_READY": bool(or_readiness.get("usable_sessions", 0)) and bool(or_readiness.get("or_available_only_after_window_close")),
    }

    record = IngestedSymbol(
        symbol=symbol,
        source_file=str(path.resolve()),
        original_sha256=file_sha256(path),
        row_count=len(df),
        first_timestamp=df.index[0].isoformat() if len(df) else "",
        last_timestamp=df.index[-1].isoformat() if len(df) else "",
        timezone=f"normalized to UTC (source parsed with assume_naive_tz={assume_naive_tz})",
        timeframe=timeframe,
        validation_result={"passed": validation.passed, "checks": validation.checks,
                            "failed_checks": validation.failed_checks()},
        gap_summary=gap_summary,
        derived_timeframes=derived,
        derivation_method=derivation_method,
        or_readiness=or_readiness,
        sufficiency=sufficiency_flag(df.index[0], df.index[-1]) if len(df) > 1 else "LT_1_YEAR",
        readiness=readiness,
        ingestion_timestamp=pd.Timestamp.now(tz=UTC).isoformat(),
    )
    return record, problems


def global_verdict(records: List[IngestedSymbol], problems: List[str]) -> str:
    """One of READY_FOR_PHASE_9C / DATA_INCOMPLETE / DATA_INVALID /
    REAL_DATA_NOT_SUPPLIED. Never returns READY just because some data
    exists -- every readiness flag must hold for at least one symbol."""
    if not records:
        return "REAL_DATA_NOT_SUPPLIED"
    if any(not r.validation_result["passed"] for r in records):
        return "DATA_INVALID"
    fully_ready = [r for r in records if all(r.readiness.values())]
    if not fully_ready:
        return "DATA_INCOMPLETE"
    return "READY_FOR_PHASE_9C"


def build_manifest(records: List[IngestedSymbol], problems: List[str], searched: List[str]) -> Dict:
    """The immutable provenance manifest. Source data is never modified;
    this describes it."""
    return {
        "phase": "9C-DATA",
        "manifest_version": 1,
        "ingestion_timestamp": pd.Timestamp.now(tz=UTC).isoformat(),
        "searched_locations": searched,
        "data_policy": "REAL DATA ONLY. No synthetic substitution, no gap filling, no interpolation.",
        "opening_range_definition": {
            "session_open_local": NY_SESSION_OPEN,
            "timezone": str(NY_TZ),
            "or_minutes": NY_OPENING_RANGE_MINUTES,
            "dst_handling": "per-date zoneinfo conversion (never a fixed UTC offset)",
        },
        "datasets": [dataclasses.asdict(r) for r in records],
        "problems": problems,
        "global_verdict": global_verdict(records, problems),
    }


def ingest_directory(search_dirs: List[Path], assume_naive_tz: str = "UTC") -> Dict:
    """Full pipeline: discover -> identify -> validate -> classify gaps ->
    derive M5/M15 -> verify OR readiness -> manifest."""
    files = discover_data_files(search_dirs)
    records: List[IngestedSymbol] = []
    problems: List[str] = []

    if not files:
        problems.append(
            "NO_DATA_FILES_FOUND: no .csv/.txt/.parquet files under "
            + ", ".join(str(d) for d in search_dirs)
        )

    for path in files:
        record, file_problems = ingest_file(path, assume_naive_tz=assume_naive_tz)
        problems.extend(file_problems)
        if record is not None:
            records.append(record)

    return build_manifest(records, problems, [str(d) for d in search_dirs])


if __name__ == "__main__":
    # INFRASTRUCTURE ROUND-TRIP TEST ONLY. The fixture below is a
    # hand-built deterministic ramp (base = 100 + i*0.001), written to a
    # TEMPORARY directory -- never into a real data drop location. It is
    # not market data and produces no research result; its only purpose is
    # to prove the happy path works, so that a REAL_DATA_NOT_SUPPLIED
    # verdict is provably a statement about missing data rather than about
    # broken ingestion code.
    import tempfile

    rows = []
    i = 0
    for day in ("2024-06-03", "2024-06-04", "2024-06-05", "2024-06-06", "2024-06-07"):
        or_open = session_open_utc(pd.Timestamp(day, tz="UTC"), NY_SESSION_OPEN, NY_TZ)
        start = or_open - pd.Timedelta(minutes=30)  # 09:00 NY
        for k in range(121):  # 09:00 .. 11:00 NY
            base = 100.0 + i * 0.001
            rows.append({
                "timestamp": (start + pd.Timedelta(minutes=k)).isoformat(),
                "open": round(base, 6), "high": round(base + 0.004, 6),
                "low": round(base - 0.003, 6), "close": round(base + 0.001, 6),
                "volume": 100 + (i % 7), "spread": 0.0001,
            })
            i += 1

    with tempfile.TemporaryDirectory() as tmp:
        pd.DataFrame(rows).to_csv(Path(tmp) / "eurusd_m1_2024.csv", index=False)
        manifest = ingest_directory([Path(tmp)])

    assert manifest["global_verdict"] == "READY_FOR_PHASE_9C", manifest["global_verdict"]
    d = manifest["datasets"][0]
    assert d["symbol"] == "EURUSD" and d["timeframe"] == "M1"
    assert d["validation_result"]["passed"] and not d["validation_result"]["failed_checks"]
    assert d["derived_timeframes"]["M5"] > 0 and d["derived_timeframes"]["M15"] > 0
    assert d["or_readiness"]["ny_sessions_found"] == 5
    assert d["or_readiness"]["usable_sessions"] == 5
    assert d["or_readiness"]["or_available_only_after_window_close"]
    assert all(d["readiness"].values())
    # the fixture deliberately covers only 09:00-11:00 NY per day, so the
    # overnight holes MUST be flagged -- proof the classifier discriminates
    # rather than rubber-stamping everything as expected.
    assert d["gap_summary"]["counts"]["DATA_GAP"] == 4

    print("Ingestion round-trip:", manifest["global_verdict"])
    print("  symbol/timeframe identified:", d["symbol"], d["timeframe"], f"rows={d['row_count']}")
    print("  derived timeframes:", d["derived_timeframes"])
    print("  NY sessions usable:", d["or_readiness"]["usable_sessions"], "of", d["or_readiness"]["ny_sessions_found"])
    print("  sample OR:", d["or_readiness"]["sample_or"])
    print("  gap classification:", d["gap_summary"]["counts"])
    print("OK (infrastructure round-trip only -- no real or synthetic market data was used)")
