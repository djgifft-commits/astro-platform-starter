# Phase 9C-DATA — Real Historical Data Ingestion

**GLOBAL VERDICT: `REAL_DATA_NOT_SUPPLIED`.**

No real historical market data exists in this environment. The ingestion
pipeline this phase specifies has been built, tested, and is waiting; it
has never been run against real data because there is none to run against.
**No Phase 9C strategy validation was performed**, per this phase's own
stop condition.

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

## 9. Per-symbol readiness — all datasets missing

| Symbol | DATA_EXISTS | SCHEMA_VALID | TIMEFRAME_VALID | TIMEZONE_VALID | STRUCTURE_VALID | CAUSAL_READY | SESSION_READY | OR_READY |
|---|---|---|---|---|---|---|---|---|
| EUR_USD | ✗ | — | — | — | — | — | — | — |
| USD_JPY | ✗ | — | — | — | — | — | — | — |
| GBP_USD | ✗ | — | — | — | — | — | — | — |
| XAUUSD | ✗ | — | — | — | — | — | — | — |
| AUD_USD | ✗ | — | — | — | — | — | — | — |
| USD_CHF | ✗ | — | — | — | — | — | — | — |

Years available: **0**. M1 rows: **0**. M5 rows: **0**. M15 rows: **0**.
NY sessions available: **0**. Usable sessions: **0**. Sufficiency: **not
assessable**.

## 10. Files changed

New: `research/data/ingestion.py`, `research/ingest_real_data.py`,
`research/data/ingestion_mutation_tests.py`, `data/historical/README.md`,
`research/data_manifest/phase9c_manifest.json`, this document.
Modified: `.gitignore` (ignore `data/historical/*` — real vendor data is
frequently licensed and must never be committed — while keeping the README
and manifest tracked).

**Unchanged**: every strategy, entry, SL, TP, risk, hedge, execution, and
production file.

---

## What I need from you

Drop the files into `data/historical/` and run one command. Concretely:

1. **M1 (1-minute) OHLCV history** for at least one of `EURUSD`,
   `USDJPY`, `GBPUSD`, `XAUUSD`, `AUDUSD`, `USDCHF`. M1 is the important
   one — M5 and M15 are derived from it, and the strategy's 1-minute
   entry-trigger layer cannot be evaluated without it.
2. **Filenames that state symbol and timeframe** — e.g. `eurusd_m1.csv`,
   `xauusd_m1_2019_2024.parquet`. Unrecognized names are reported, not
   guessed.
3. **Columns** `timestamp, open, high, low, close` (plus `volume`/
   `spread` if you have them). A `spread` column materially improves the
   cost model — without it, cost sensitivity falls back to assumptions
   rather than your broker's real spreads.
4. **Tell me the timezone if timestamps have no UTC offset.** MT5 exports
   are typically broker-server time, not UTC. Getting this wrong shifts
   every bar and moves the opening range onto the wrong candles.
5. **As much history as you have.** 1 year ≈ 250 NY sessions, which is
   thin for per-regime/per-year stability testing; 3+ years across
   several symbols is what makes the walk-forward and
   multiple-testing-corrected analysis meaningful.

Typical sources you can export from yourself: MT5 (History Center →
Export), your broker's data export, or a purchased/licensed vendor
dataset. I cannot fetch any of these — the network probe in
`audit/PHASE_9C_REAL_DATA_VALIDATION.md` showed every historical-data host
is blocked by org policy at the gateway, and routing around that is not
something I will attempt.

## Command to authorize next

Once files are in `data/historical/`:

```bash
research/.venv/bin/python -m research.ingest_real_data
```

(or `--dir /path/to/data` if you put them elsewhere; add
`--assume-naive-tz <IANA zone>` if your timestamps carry no offset).

That prints a per-symbol readiness table and writes
`research/data_manifest/phase9c_manifest.json`. **If and only if it
reports `READY_FOR_PHASE_9C`** is the Phase 9C strategy validation
unblocked — and that remains a separate authorization.

---

## Final verdict

**`REAL_DATA_NOT_SUPPLIED`.**

**PRODUCTION_IMPACT**: NONE (byte-identical hashes, verified).
**LIVE_TRADING**: remains disabled; no broker/order-routing code exists.
**DATA_USED**: none — no real data exists, and no synthetic data was
substituted anywhere in this phase. The only fixtures are hand-built
deterministic test vectors used to prove ingestion mechanics, which
produce no research result.
**TESTS**: 8/8 ingestion mutations detected; 21/21 module regressions
passed.
**MISSING_DATASETS**: M1 for all 6 preferred symbols (M5/M15 derivable
from M1, so M1 alone unblocks a symbol).
**NEXT_SAFE_ACTION**: supply M1 files to `data/historical/` and run the
ingestion command above. Do not begin Phase 9C strategy validation. Do
not begin Phase 9D.

**STOP.**
