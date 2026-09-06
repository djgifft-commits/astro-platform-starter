# Real historical data drop location (Phase 9C)

Put real historical OHLCV files **in this directory**, then run:

```bash
research/.venv/bin/python -m research.ingest_real_data
```

Everything in this directory except this README is gitignored — real
vendor/broker data is frequently licensed and is never committed to the
repository. Source files are read only; ingestion never modifies them.

## Filename contract

The ingester identifies symbol and timeframe **from the filename** and
refuses to guess. Include both:

```
eurusd_m1.csv          usdjpy_m1_2019_2024.parquet
gbpusd_M1.csv          xauusd-m1.csv
```

Recognized symbols: `EURUSD`, `USDJPY`, `GBPUSD`, `XAUUSD`, `AUDUSD`,
`USDCHF` (underscore/hyphen/slash spellings all accepted; `gold` maps to
XAUUSD). Recognized timeframes: `M1`/`1m`/`1min`, `M5`/`5m`, `M15`/`15m`.

A file whose symbol or timeframe cannot be identified is reported as
`UNIDENTIFIED_SYMBOL` / `UNIDENTIFIED_TIMEFRAME` — never silently assigned
a guessed identity.

## Column contract

CSV or Parquet. Required columns:

```
timestamp, open, high, low, close
```

Optional and used when present: `volume` (or `tick_volume`), `spread`,
`symbol`.

Timestamps may be ISO-8601 (with or without a UTC offset) or epoch
seconds. **If your timestamps carry no offset, they are assumed UTC** — if
they are actually broker-local, pass the real zone explicitly:

```bash
research/.venv/bin/python -m research.ingest_real_data --assume-naive-tz Europe/Helsinki
```

Getting this wrong shifts every bar and moves the New York opening range
onto the wrong candles, so state it rather than letting it default.

## Timeframe requirement

**M1 is what matters.** M5 and M15 are derived from M1 deterministically
and causally (`open`=first, `high`=max, `low`=min, `close`=last, trailing
incomplete bucket dropped). Supplying M5/M15 directly is accepted but not
required, and M1 is strongly preferred — the 1-minute entry-trigger layer
of the strategy cannot be evaluated without it.

## History requirement

More is better; the ingester reports a sufficiency bucket (`LT_1_YEAR`,
`1_TO_2_YEARS`, `2_TO_3_YEARS`, `3_PLUS_YEARS`) but deliberately does not
declare statistical sufficiency on its own. Roughly: 1 year of M1 gives
~250 New York sessions, which is a thin sample for per-regime and
per-year stability testing; 3+ years across several symbols is what makes
the Phase 9C walk-forward and multiple-testing-corrected analysis
meaningful.

## What ingestion does

Validates (18 checks: schema, timezone, monotonicity, duplicates, OHLC
invariants, NaN/inf, impossible candles, symbol/timeframe identity,
incomplete final candle, …), classifies every gap
(`WEEKEND_GAP`/`HOLIDAY_GAP`/`DATA_GAP`/`UNKNOWN_GAP` — never fills any of
them), derives M5/M15, verifies the 09:30–09:45 America/New_York opening
range is complete per session, and writes an immutable manifest to
`research/data_manifest/phase9c_manifest.json`.

It performs no strategy testing, connects to no broker, and generates no
synthetic data.
