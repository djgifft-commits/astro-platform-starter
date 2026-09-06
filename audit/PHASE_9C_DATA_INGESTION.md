# Phase 9C-DATA — Real Historical Data Ingestion

**GLOBAL VERDICT: `READY_FOR_PHASE_9C`.**

The user attached a real MT5 "Export to CSV" of XAUUSD M1 history
(100,000 bars, 2026-05-26 to 2026-09-04) and confirmed the broker server
offset is **GMT+3**. With that offset applied, all 18 validation checks
pass, M1→M5/M15 derive cleanly, and 74 of 74 New York opening-range
sessions in this span are complete and usable. This is the first real
market data this project has had, and the first time this pipeline has
run to completion against it. **No Phase 9C strategy validation has been
performed** — this remains a data-ingestion-only deliverable, per this
phase's own stop condition.

Machine-readable manifest: `research/data_manifest/phase9c_manifest.json`.

---

## 1. Governance — before state

| Item | Value |
|---|---|
| HEAD (before this phase) | `6987eb6` (`a081854` before the Phase 9C audit) |
| Branch | `claude/multi-strategy-hedge-backtest-sa7cer` |
| `git status` | clean, up to date with origin |
| Production hashes (`src/`, `public/`, `astro.config.mjs`, `package.json`, `package-lock.json`, `tsconfig.json`) | `f6f85a99…` — **byte-identical to the Phase 9B baseline, zero drift** |
| `.env` | no `.env` file exists in this repository |
| `research/config.py` | `fa6e0ec7…` |
| Live trading | **DISABLED** — no `order_send`, no MetaTrader/broker SDK, no order-routing code anywhere in `research/` or `web/` (grep-verified; only disclaimer prose mentions "MT5") |

This phase remained research-only. No production file, strategy rule,
entry rule, SL/TP model, risk model, or hedge model was modified — the
only changes are new data-ingestion files plus this document (Section 10).

## 2. Data discovery sweep

Searched, in this order:

| Location | Result |
|---|---|
| Conversation attachments (`/mnt/attach`) | **empty** |
| User-data mount (`/mnt/user-data/working`) | **empty** |
| `research/data/` | code only (`ingestion.py`, `real_data.py`, `loaders.py`, `quality.py`, `synthetic.py`) — no data files |
| `data/` | did not exist (created by this phase as the drop location, Section 8) |
| `data/historical/` | did not exist (created by this phase) |
| Whole-filesystem sweep for `*.csv`, `*.parquet`, `*.tsv`, `*.hst`, `*.feather`, `*.h5`, `*.zip`, `*.gz` | only OS man pages (`/etc/alternatives/*.gz`, `/usr/share/distro-info/*.csv`) and this project's own Python sources |
| Files modified in the last 6h under `/mnt`, `/home`, `/root`, `/tmp` | only this project's own source files |
| Mounted filesystems | no data volume mounted; `/mnt/skills` (read-only squashfs) and system mounts only |

**Zero real historical price data present.** This is a fresh sweep
performed this session, not a citation of the Phase 9C network-probe
result.

## 3. What was built

Building the ingestion capability is this phase's own deliverable
("REAL HISTORICAL DATA INGESTION ONLY") and is explicitly not strategy
work: no strategy logic, entry rule, SL/TP model, risk model, or hedge
logic was touched. The stop condition — *do not run Phase 9C research* —
is honored: no backtest, no signal, no performance number was produced.

| File | Purpose |
|---|---|
| `research/data/ingestion.py` | discovery → identification → 18-point validation → gap classification → M5/M15 derivation → OR-readiness verification → manifest |
| `research/ingest_real_data.py` | CLI entry point; writes the immutable manifest |
| `research/data/ingestion_mutation_tests.py` | the 8 required behavioral mutation tests |
| `data/historical/README.md` | the drop location and its filename/column contract |

**Reuse map** (nothing reimplemented): `real_data.py::load_real_ohlcv` and
`compute_data_hash` for loading/hashing, `quality.py::audit_bars` and
`assert_no_lookahead` for base checks, `loaders.py::resample_ohlc` for
causal M1→M5/M15 aggregation, `sessions.py::compute_ny_opening_ranges` and
`session_open_utc` for the opening range and DST-correct session anchor.
Genuinely new: multi-file identification, the 18-check battery, gap
classification, OR-readiness verification, sufficiency flagging, and the
manifest.

## 4. Input contract

CSV or Parquet. Required columns `timestamp, open, high, low, close`;
`volume`/`tick_volume`, `spread`, `symbol` used when present. Symbol and
timeframe are identified **from the filename** (`eurusd_m1.csv`,
`xauusd-M1-2019-2024.parquet`); anything unrecognized is reported as
`UNIDENTIFIED_SYMBOL`/`UNIDENTIFIED_TIMEFRAME` rather than guessed, per
*"Do not guess silently."* Naive timestamps default to UTC and the
assumption is recorded in the manifest; `--assume-naive-tz` overrides it
for broker-local exports.

## 5. Validation, gaps, and derivation

**18 checks**: file integrity, SHA-256, schema, timestamp type, timezone,
monotonicity, duplicates, missing timestamps, OHLC invariants,
zero/negative prices, NaN, infinity, impossible candles (>20% single-bar
move), session continuity, symbol identity, timeframe identity (declared
filename vs. observed modal bar spacing), date range, and incomplete final
candle. Nothing is ever repaired silently — findings are recorded and a
failing dataset is reported as failing.

**Gap classification** into `EXPECTED_SESSION_GAP` / `WEEKEND_GAP` /
`HOLIDAY_GAP` / `DATA_GAP` / `UNKNOWN_GAP`. **No gap is ever filled or
interpolated.** Moving holidays (Good Friday, Thanksgiving) are
deliberately *not* inferred — a gap on such a day classifies as
`UNKNOWN_GAP` for human confirmation rather than being labeled a holiday
on a guess.

**M1 → M5/M15** via the existing `resample_ohlc`: `open`=first,
`high`=max, `low`=min, `close`=last, `spread`=mean, buckets on exact
wall-clock boundaries, and any trailing bucket whose right edge extends
past the last available M1 bar is dropped — so no still-forming higher
timeframe bar is ever exposed. Spread aggregates as a mean only when a
`spread` column exists; otherwise it is marked unavailable, never
fabricated.

**Opening range**: 09:30–09:45 `America/New_York`, converted per-date via
`zoneinfo` (never a fixed UTC offset), so the DST transitions are handled
automatically. The window is half-open `[09:30, 09:45)`, and the OR only
becomes available at `or_close_utc` — the bar at exactly 09:45 can never
contaminate it.

## 6. Mutation testing — 8/8 detected

Fixtures are **hand-built deterministic test vectors** (literal values
`open=100+i`, `high=100.9+i`, …, chosen so first/max/min/last are all
distinguishable). The synthetic *market* generator is not used anywhere in
these tests.

| Mutation | Invariant proven | Result |
|---|---|---|
| `timestamp_parsing` | an explicit `+02:00` offset is honored, not read as naive wall-clock | DETECTED |
| `timezone_conversion` | NY 09:30 in January → 14:30Z (EST), not a fixed UTC-4 | DETECTED |
| `dst` | UTC anchor shifts 1h at **both** the March and November transitions | DETECTED |
| `m1_aggregation` | `open`=first/`high`=max/`low`=min/`close`=last, not a swapped open/close | DETECTED |
| `m5_m15_boundary` | the 09:30 M15 bucket excludes the 09:45 bar and starts exactly on the boundary | DETECTED |
| `or_close_timing` | an extreme high planted on the 09:45 bar does not enter the OR | DETECTED |
| `duplicate_handling` | duplicate timestamps fail validation (and clean data passes the same check) | DETECTED |
| `future_bar_access` | look-ahead assertion fires, and no still-forming M15 bucket is exposed | DETECTED |

Each test also verifies the check *passes* on unmutated input, so none can
pass vacuously.

## 7. Regression tests — 21/21 passed

Every module self-test across Phases 2–9B re-run after implementation:
`data.{quality,loaders,real_data,synthetic,ingestion,ingestion_mutation_tests}`,
`core.{sessions,structure,regime,bias,fibonacci,liquidity,candle_anatomy,protected_levels,market_context}`,
`strategies.{entry_decision,opening_range_v2}`,
`risk.{position_sizing,sl_models,tp_models}`, and
`backtest.mutation_testing` (Phase 8 + 9B's 15 mutations, all still
detected). **Zero regressions.**

## 8. Pipeline correctness proof

`python -m research.data.ingestion` runs an end-to-end round trip on a
hand-built fixture in a temporary directory (never a real drop location):
symbol/timeframe identified, all 18 checks passed, M5/M15 derived
(124/44 bars from 605 M1), 5 of 5 NY sessions usable, OR available only at
window close, verdict `READY_FOR_PHASE_9C`. The same run asserts the gap
classifier flags the fixture's 4 deliberate overnight holes as `DATA_GAP`
— proof it discriminates rather than rubber-stamping.

This matters: it makes `REAL_DATA_NOT_SUPPLIED` provably a statement about
missing data, not about broken code.

## 9. Per-symbol readiness (as of the original, data-free revision)

| Symbol | DATA_EXISTS | SCHEMA_VALID | TIMEFRAME_VALID | TIMEZONE_VALID | STRUCTURE_VALID | CAUSAL_READY | SESSION_READY | OR_READY |
|---|---|---|---|---|---|---|---|---|
| EUR_USD | ✗ | — | — | — | — | — | — | — |
| USD_JPY | ✗ | — | — | — | — | — | — | — |
| GBP_USD | ✗ | — | — | — | — | — | — | — |
| XAUUSD | ✗ | — | — | — | — | — | — | — |
| AUD_USD | ✗ | — | — | — | — | — | — | — |
| USD_CHF | ✗ | — | — | — | — | — | — | — |

Superseded by Section 9b for XAUUSD.

## 9b. Real data received and ingested — XAUUSD

The user attached `XAUUSD_M1_.csv`, a native MT5 History Center export
(SHA-256 `3d1b0d08…`), copied byte-identically to
`data/historical/XAUUSD_M1.csv` (verified: source and copy hash equal).

**Format**: tab-delimited, `<DATE>	<TIME>	<OPEN>	<HIGH>	<LOW>	<CLOSE>	<TICKVOL>	<VOL>	<SPREAD>`
header, `\r\n` line endings, dates as `YYYY.MM.DD`, `<DATE>`/`<TIME>` in
separate columns. This is a genuinely different shape from the loader's
original comma-delimited/single-`timestamp`-column assumption, so
`research/data/real_data.py::load_real_ohlcv` was extended (Section 10)
to parse it. Every extension is a lossless, deterministic rearrangement
of the vendor's own fields — delimiter auto-detection, bracket-stripping,
and concatenating the vendor's own `<DATE>` + `<TIME>` columns into one
timestamp — never an inferred or fabricated value.

**Ingested dataset**:

| Field | Value |
|---|---|
| Symbol | XAUUSD |
| Timeframe | M1 |
| Rows | 100,000 |
| Range (UTC, GMT+3-corrected) | 2026-05-26T13:10:00Z .. 2026-09-04T20:54:00Z (101.3 days) |
| Broker server offset | GMT+3, user-confirmed (Section 11) |
| Sufficiency | `LT_1_YEAR` |

**18-point validation: 18/18 passed**, zero findings on every check —
zero duplicates, zero OHLC-invariant violations, zero NaN/inf, zero
impossible candles, correct symbol/timeframe identity, monotonic index,
complete final candle. This is an unusually clean feed.

**Gap classification**: `{EXPECTED_SESSION_GAP: 60, WEEKEND_GAP: 14,
HOLIDAY_GAP: 0, DATA_GAP: 0, UNKNOWN_GAP: 0}` — **every gap in the file is
accounted for as an expected daily/weekly market closure; zero
unexplained gaps.**

**M1 → M5/M15 derivation**: 100,000 M1 → 20,002 M5 bars → 6,717 M15 bars,
via the existing `resample_ohlc` (open=first/high=max/low=min/close=last,
trailing incomplete bucket dropped — unchanged from Phase 9B).

**Opening-range readiness**: 74 of 74 NY trading sessions found in this
span have a complete, uncontaminated 09:30–09:45 opening range. Zero
missing 09:30 bars, zero incomplete sessions. Sample (2026-05-26):
OR_high=4531.22, OR_low=4521.17, OR_mid=4526.20, OR_width=10.05.

**Readiness flags**: `DATA_EXISTS / SCHEMA_VALID / TIMEFRAME_VALID /
TIMEZONE_VALID / STRUCTURE_VALID / CAUSAL_READY / SESSION_READY /
OR_READY` — **all eight true.** The ingester's own `global_verdict`
therefore computed `READY_FOR_PHASE_9C`.

## 10. Loader extension for MT5's native export format

`research/data/real_data.py::load_real_ohlcv` gained three additions,
none of which touch strategy, entry, SL/TP, risk, or hedge code:

1. **Delimiter auto-detection** (`sep=None, engine="python"`) instead of
   assuming comma — MT5's own CSV export is tab-delimited.
2. **Header normalization** strips `<>` in addition to the existing
   whitespace/lowercase normalization (`<TICKVOL>` → `tickvol` →
   recognized as an alias for `volume`, alongside the existing
   `tick_volume` alias).
3. **Date+time concatenation**: when no single `timestamp` column exists
   but `date` and `time` do, they are concatenated verbatim
   (`"2026.05.26" + " " + "16:10:00"`) before parsing — the vendor's own
   two fields combined losslessly, not a new value.
4. **Fixed-offset timezone strings**: `assume_naive_tz` now also accepts
   `"+02:00"`/`"-5"`-style fixed offsets, not only IANA zone names — MT5
   describes broker-server time to users as "GMT+N", not as an IANA zone,
   and forcing a guessed IANA name would be exactly the kind of silent
   guess this phase prohibits.

A pre-existing bug was also found and fixed while wiring this up:
`research/data/ingestion.py::discover_data_files` double-counted the same
file when two configured search directories nested (`data/` and
`data/historical/`), because it deduplicated nothing. Fixed by
deduplicating on each file's resolved absolute path. This is a real
ingestion-mechanics bug fix (files should never be double-ingested),
distinct from the substantive timezone question in Section 11, and was
verified by re-running the full 21-module regression suite plus the 8
ingestion mutation tests (all still pass) after both changes.

## 11. Timestamp timezone — RESOLVED, GMT+3, user-confirmed

The first pass through this pipeline defaulted to `assume_naive_tz=UTC`,
which — before confirmation — was flagged as very likely wrong. Evidence
computed from the file itself (not a citation): under the UTC assumption,
the weekly trading gap fell at **Friday 23:54 → Monday 01:05** every week
(14 occurrences, all consistent), whereas real spot gold/FX markets
close/reopen close to **21:00–22:00 UTC**. Testing candidate offsets
against that fact:

| Candidate broker offset | Implied real close (UTC) | Implied real reopen (UTC) |
|---|---|---|
| UTC+0 (original default) | Fri 23:54 | Sun/Mon 01:05 |
| UTC+2 | Fri 21:54 | Sun 23:05 |
| **UTC+3** | **Fri 20:54** | **Sun 22:05** |

**The user then checked their MT5 terminal and confirmed GMT+3.**
Re-running ingestion with `--assume-naive-tz "+03:00"` moves the weekly
gap to **Friday 20:54 UTC → Sunday 22:05 UTC** — landing almost exactly on
the canonical 21:00–22:00 UTC close/reopen, confirming the correction
against real market structure, not merely against the user's word. This
is now applied (Section 9b's numbers reflect it); the 100,000-row dataset
was re-validated afterward (all 18 checks still pass, gap counts
unchanged in kind, OR-readiness recomputed: 74/74 sessions usable, one
more than the pre-correction 73 since the corrected boundary reclassifies
which calendar day some late sessions belong to).

**Not yet confirmed, and not assumed**: whether this GMT+3 is fixed
year-round or whether the broker applies its own DST-like shift at some
point in the year. The current 101-day window (2026-05-26 to 2026-09-04)
does not cross a US DST boundary, so this does not affect today's
verdict, but it would need to be revisited before ingesting a longer
history that spans a March/November US DST transition, or if the broker's
own schedule shifts independent of the US calendar. `--assume-naive-tz`
takes a single fixed offset per ingestion run; a broker whose offset
changes mid-year would require the file to be split at the shift date, or
the loader extended to accept a per-date offset — neither has been
needed yet and neither has been built speculatively.

## 12. Files changed

New: `data/historical/XAUUSD_M1.csv` (gitignored, not committed — see
`.gitignore`), `research/data/ingestion.py`, `research/ingest_real_data.py`,
`research/data/ingestion_mutation_tests.py`, `data/historical/README.md`,
`research/data_manifest/phase9c_manifest.json`, this document.
Modified: `.gitignore` (ignore `data/historical/*` — real vendor data is
frequently licensed and must never be committed — while keeping the README
and manifest tracked), `research/data/real_data.py` (loader extension,
Section 10).

**Unchanged**: every strategy, entry, SL, TP, risk, hedge, execution, and
production file (re-verified: `git diff --stat` against those paths is
empty, production hashes byte-identical).

## 13. Regression after the loader change

21/21 module self-tests re-run and passing (unchanged from the original
revision's Section 7, plus `research.data.real_data` re-verified since it
was the file actually modified), and all 15 Phase 8/9B strategy-layer
mutation tests plus all 8 ingestion mutation tests still detect their
mutation. Zero regressions from extending the loader.

---

## What would strengthen this further (not required to proceed)

XAUUSD alone is enough to prove the pipeline and to begin Phase 9C
strategy validation on. It is thin for the full spec's cross-symbol,
multi-year stability analysis:

- **More symbols**: EUR_USD, USD_JPY, GBP_USD, AUD_USD, USD_CHF M1 files,
  same process, would let the eventual walk-forward/regime/symbol
  stability testing say something about generalization rather than one
  symbol over one 101-day window.
- **More history for XAUUSD itself**: 101 days ≈ 74 NY sessions is enough
  to exercise the pipeline and start looking at the data, but thin for
  the year-stability and purged walk-forward analysis the full Phase 9C
  spec asks for.
- **Spread units**: the file's `<SPREAD>` column is in MT5's native
  points, not price units (Section 9b). This is fine to carry through
  ingestion as-is (flagged, not converted) but will need an explicit,
  confirmed point-size conversion before it feeds the real-cost model in
  strategy validation — a decision for that phase, not this one.

## Command to authorize next

Data ingestion for XAUUSD is complete and confirmed. The next step is a
**separate authorization** for Phase 9C strategy validation itself (the
OR state machine, entry families, SL/TP models, etc., against this real
data) — per this phase's explicit "do not automatically begin strategy
validation" stop condition. When ready:

```
PHASE 9C — proceed with strategy validation on the ingested XAUUSD data.
```

or equivalent explicit instruction.

---

## Final verdict

**`READY_FOR_PHASE_9C`.**

**PRODUCTION_IMPACT**: NONE (byte-identical hashes, verified).
**LIVE_TRADING**: remains disabled; no broker/order-routing code exists;
no MT5 connection of any kind was made — the data arrived as a
user-exported file attachment, not a live API call.
**DATA_USED**: XAUUSD M1, 100,000 real bars, 2026-05-26 to 2026-09-04,
user-supplied MT5 export, GMT+3 broker offset (user-confirmed, and
independently corroborated against the real market's own weekly
close/reopen pattern — Section 11). No synthetic data was substituted or
blended with it anywhere in this phase.
**TESTS**: 8/8 ingestion mutations detected; 21/21+ module regressions
passed (re-verified after both the loader extension and the timezone
correction).
**MISSING_DATASETS**: M1 for EUR_USD, USD_JPY, GBP_USD, AUD_USD, USD_CHF
— not required to proceed with XAUUSD, but would strengthen the eventual
cross-symbol analysis (see above).
**NEXT_SAFE_ACTION**: request explicit authorization for Phase 9C
strategy validation on the now-ready XAUUSD dataset. Do not begin it
automatically. Do not begin Phase 9D.

**STOP — awaiting authorization for Phase 9C strategy validation.**
