"""
Phase 8C — Real historical-data engine.

THIS PROJECT HAS NO REAL DATA IN THIS SESSION. See
audit/PHASE_8A_ARCHITECTURE_AUDIT.md Section 4 for the direct evidence
(filesystem search + 5-host network probe, all rejected by this session's
egress policy). This module is a real-data-CAPABLE loader built and
proven against a synthetic fixture ONLY, exactly under Phase 8C's own
carve-out: "Synthetic data ONLY for infrastructure/unit tests. Do not mix
synthetic and real results." It has never been run against real data, and
nothing produced by it in this session should be read as a real-market
number -- only as a demonstration that the loader mechanics work.

Expected input schema (CSV or Parquet), one file per symbol+timeframe or
one long file with a `symbol` column:

    timestamp   (ISO-8601 or epoch seconds; any standard tz or naive-as-UTC)
    open, high, low, close    (float, required)
    volume | tick_volume       (float, optional)
    spread                      (float, optional, in price units)
    symbol                       (string, required if multi-symbol file)

If your export uses different column names (e.g. MT5's "time", "tick_volume",
"real_volume"), pass `column_map` to `load_real_ohlcv`.
"""
from __future__ import annotations

import dataclasses
import hashlib
from pathlib import Path
from typing import Dict, Optional

import numpy as np
import pandas as pd

from research.config import UTC
from research.data.quality import QualityReport, audit_bars

REQUIRED_COLUMNS = {"timestamp", "open", "high", "low", "close"}
OPTIONAL_COLUMNS = {"volume", "tick_volume", "spread", "symbol"}


class RealDataSchemaError(ValueError):
    pass


@dataclasses.dataclass
class RealDataset:
    symbol: str
    source_path: str
    bars: pd.DataFrame
    data_hash: str
    provenance: str  # human-readable note on where this came from


def compute_data_hash(df: pd.DataFrame) -> str:
    """Deterministic hash of a bar DataFrame's content (index + OHLC),
    so two runs against the same file are provably using the same data,
    and any silent re-download/edit is detectable."""
    h = hashlib.sha256()
    h.update(df.index.astype("int64").to_numpy().tobytes())
    for col in ("open", "high", "low", "close"):
        if col in df.columns:
            h.update(np.ascontiguousarray(df[col].to_numpy(dtype="float64")).tobytes())
    return h.hexdigest()


def load_real_ohlcv(
    path: str,
    symbol: Optional[str] = None,
    column_map: Optional[Dict[str, str]] = None,
    assume_naive_tz: str = "UTC",
) -> RealDataset:
    """Load a real historical OHLCV file (CSV or Parquet) into the same
    shape `research/data/synthetic.py` produces, so it can be handed
    straight to `research/core/feature_bar.py::build_symbol_engine_data`
    with zero changes to any downstream module (Phase 8A Section 2/4).

    NEVER CALLED WITH REAL DATA IN THIS SESSION -- see module docstring.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"No such file: {path}")

    if p.suffix.lower() == ".parquet":
        df = pd.read_parquet(p)
    elif p.suffix.lower() in (".csv", ".txt"):
        df = pd.read_csv(p)
    else:
        raise RealDataSchemaError(f"Unsupported file extension: {p.suffix}")

    if column_map:
        df = df.rename(columns=column_map)
    df.columns = [c.strip().lower() for c in df.columns]

    if "symbol" in df.columns and symbol is not None:
        df = df[df["symbol"] == symbol].drop(columns=["symbol"])
    elif "symbol" in df.columns and symbol is None:
        symbols_present = df["symbol"].unique().tolist()
        raise RealDataSchemaError(
            f"File contains multiple symbols {symbols_present}; pass `symbol=` to select one."
        )

    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise RealDataSchemaError(
            f"Missing required column(s) {missing}. Found columns: {list(df.columns)}. "
            f"Pass `column_map={{'your_col': 'timestamp', ...}}` to rename."
        )

    ts = pd.to_datetime(df["timestamp"], utc=False, errors="raise")
    if ts.dt.tz is None:
        ts = ts.dt.tz_localize(assume_naive_tz)
    df = df.set_index(ts.dt.tz_convert(UTC)).drop(columns=["timestamp"])
    df.index.name = "timestamp"
    df = df.sort_index()

    if "tick_volume" in df.columns and "volume" not in df.columns:
        df = df.rename(columns={"tick_volume": "volume"})

    keep_cols = [c for c in ("open", "high", "low", "close", "volume", "spread") if c in df.columns]
    df = df[keep_cols].astype({c: "float64" for c in keep_cols})

    data_hash = compute_data_hash(df)
    return RealDataset(
        symbol=symbol or "UNKNOWN",
        source_path=str(p.resolve()),
        bars=df,
        data_hash=data_hash,
        provenance=f"loaded from {p.name} via research.data.real_data.load_real_ohlcv",
    )


def extended_quality_audit(dataset: RealDataset, expected_freq_minutes: int) -> Dict:
    """Real-data-specific checks beyond research/data/quality.py::audit_bars
    (Phase 8C requirement: zero/negative prices, spread anomalies, volume
    anomalies -- none of these can occur in the synthetic generator by
    construction, so they were never needed until real data existed)."""
    df = dataset.bars
    base_report: QualityReport = audit_bars(df, dataset.symbol, "raw", expected_freq_minutes)

    zero_or_negative_price = int(((df[["open", "high", "low", "close"]] <= 0).any(axis=1)).sum())

    spread_anomalies = 0
    if "spread" in df.columns:
        spread_anomalies = int(((df["spread"] < 0) | (df["spread"] > df["close"] * 0.05)).sum())

    volume_anomalies = 0
    if "volume" in df.columns:
        volume_anomalies = int((df["volume"] < 0).sum())

    extreme_bar_moves = int((df["close"].pct_change().abs() > 0.20).sum())  # >20% single-bar move

    return {
        "base_report": base_report.to_dict(),
        "zero_or_negative_price_bars": zero_or_negative_price,
        "spread_anomalies": spread_anomalies,
        "volume_anomalies": volume_anomalies,
        "extreme_single_bar_moves_gt_20pct": extreme_bar_moves,
        "data_hash": dataset.data_hash,
        "source_path": dataset.source_path,
        "provenance": dataset.provenance,
    }


if __name__ == "__main__":
    # INFRASTRUCTURE / UNIT TEST ONLY (Phase 8C carve-out): round-trip the
    # loader against a file written FROM the synthetic generator, purely to
    # prove the CSV/Parquet -> RealDataset -> quality-audit path works. This
    # is not, and must never be read as, a real-market result.
    import tempfile

    from research.data.synthetic import generate_multi_symbol_dataset

    ds = generate_multi_symbol_dataset(["EURUSD"], n_days=5)
    m1 = ds["EURUSD"].bars.reset_index()
    m1["symbol"] = "EURUSD"

    with tempfile.TemporaryDirectory() as tmp:
        csv_path = Path(tmp) / "eurusd_fixture.csv"
        m1.to_csv(csv_path, index=False)

        loaded = load_real_ohlcv(str(csv_path), symbol="EURUSD")
        print("Loaded shape:", loaded.bars.shape, "hash:", loaded.data_hash[:16])

        original = ds["EURUSD"].bars[["open", "high", "low", "close", "spread"]]
        aligned = loaded.bars.reindex(original.index)
        max_diff = (aligned[["open", "high", "low", "close"]] - original[["open", "high", "low", "close"]]).abs().max().max()
        print("Max OHLC round-trip diff (should be ~0, float64 CSV precision):", max_diff)
        assert max_diff < 1e-8

        report = extended_quality_audit(loaded, expected_freq_minutes=1)
        print("Extended quality audit:", {k: v for k, v in report.items() if k != "base_report"})
        assert report["zero_or_negative_price_bars"] == 0
        assert report["spread_anomalies"] == 0

        # Parquet preserves float64 bits exactly (unlike CSV's text round-trip,
        # which loses the last bit or two) -- so compare the Parquet-loaded
        # hash against a hash computed directly from the original in-memory
        # data, not against the CSV-loaded hash (those legitimately differ).
        parquet_path = Path(tmp) / "eurusd_fixture.parquet"
        m1.to_parquet(parquet_path, index=False)
        loaded_pq = load_real_ohlcv(str(parquet_path), symbol="EURUSD")
        original_hash = compute_data_hash(ds["EURUSD"].bars[["open", "high", "low", "close", "spread"]])
        assert loaded_pq.data_hash == original_hash, "Parquet round-trip must be byte-exact vs. the source data"
        print("Parquet round-trip hash matches source exactly:", loaded_pq.data_hash[:16])

    print("OK (infrastructure round-trip test only -- no real data was used)")
