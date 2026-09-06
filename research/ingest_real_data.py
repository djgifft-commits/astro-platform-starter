"""
Phase 9C-DATA — real historical data ingestion CLI.

Scans the supported drop locations for REAL historical OHLCV files,
validates and ingests them, and writes an immutable manifest to
research/data_manifest/phase9c_manifest.json.

Run:
    research/.venv/bin/python -m research.ingest_real_data
    research/.venv/bin/python -m research.ingest_real_data --dir /path/to/my/data

This script performs NO strategy testing, NO live trading, connects to no
broker, and generates NO synthetic data. If no real data is present it
reports REAL_DATA_NOT_SUPPLIED and exits without producing any research
result.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from research.data.ingestion import ingest_directory

REPO_ROOT = Path(__file__).parent.parent
DEFAULT_SEARCH_DIRS = [
    REPO_ROOT / "data" / "historical",
    REPO_ROOT / "data",
    REPO_ROOT / "research" / "data" / "historical",
    Path("/mnt/user-data/working"),
    Path("/mnt/attach"),
]
MANIFEST_DIR = REPO_ROOT / "research" / "data_manifest"
MANIFEST_PATH = MANIFEST_DIR / "phase9c_manifest.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest real historical OHLCV data (Phase 9C-DATA).")
    parser.add_argument("--dir", action="append", default=None,
                        help="Additional directory to search (repeatable).")
    parser.add_argument("--assume-naive-tz", default="UTC",
                        help="Timezone to assume for timestamps that carry no offset (default: UTC).")
    args = parser.parse_args()

    search_dirs = list(DEFAULT_SEARCH_DIRS)
    if args.dir:
        search_dirs = [Path(d) for d in args.dir] + search_dirs

    manifest = ingest_directory(search_dirs, assume_naive_tz=args.assume_naive_tz)

    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    with open(MANIFEST_PATH, "w") as f:
        json.dump(manifest, f, indent=2, default=str)

    print(f"Searched: {', '.join(manifest['searched_locations'])}")
    print(f"Datasets ingested: {len(manifest['datasets'])}")
    for d in manifest["datasets"]:
        ready = "READY" if all(d["readiness"].values()) else "NOT_READY"
        print(f"  {d['symbol']:8s} {d['timeframe']:4s} rows={d['row_count']:>9,} "
              f"{d['first_timestamp'][:10]}..{d['last_timestamp'][:10]} "
              f"{d['sufficiency']:14s} {ready}")
        if d["or_readiness"]:
            print(f"           NY sessions={d['or_readiness'].get('ny_sessions_found')} "
                  f"usable={d['or_readiness'].get('usable_sessions')}")
    if manifest["problems"]:
        print("\nProblems:")
        for p in manifest["problems"]:
            print(f"  - {p}")

    print(f"\nGLOBAL VERDICT: {manifest['global_verdict']}")
    print(f"Manifest written to {MANIFEST_PATH}")


if __name__ == "__main__":
    main()
