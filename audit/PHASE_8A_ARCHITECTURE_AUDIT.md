# Phase 8A — Pre-Flight / Architecture Audit

**Scope**: inspect the Phase 7 branch (`claude/multi-strategy-hedge-backtest-sa7cer`)
before any Phase 8 change. No code was modified while writing this document.

## 0. Repository / production context (carried forward from Phase 7, re-verified)

`djgifft-commits/astro-platform-starter` is the Netlify Astro Platform
Starter template. It has **no MT5 integration, no broker connection, no
production trading code, and no live-execution path of any kind** —
re-confirmed by `git status`/`git diff` showing the Phase 7 work is the
only non-template content in the repo, and by a fresh filesystem search
(see Section 3) finding zero MT5/broker artifacts anywhere in this
container. There is therefore no "production execution code" or
"production risk configuration" this phase could touch even by accident;
the forbidden-files list in Section 6 is drawn entirely from the Astro
site itself plus the Phase 7 research code, which this phase extends
rather than replaces.

## 1. Current architecture (Phase 7 deliverable, module-by-module)

```
research/
  config.py            symbol/pip/spread constants, DATA DISCLOSURE banner
  data/
    synthetic.py         SYNTHETIC regime-switching multi-symbol OHLC generator
    loaders.py            causal M1->M5/M15/H1/H4/D1 resampling (forming-bar safe)
    quality.py             gap/duplicate/OHLC-integrity/DST audit + causality asserts
  core/
    sessions.py           timezone-aware sessions, NY 09:30 opening range (DST-correct)
    atr.py                  Wilder ATR / normalized ATR
    candle_anatomy.py        OHLC geometry + 19-pattern deterministic recognizer
    structure.py              causal fractal swings, HH/HL/LH/LL, BOS/CHOCH
    regime.py                  10-state causal regime classifier (slope-z + ATR pctile)
    bias.py                     multi-timeframe (D1..M5) weighted structural bias
    fibonacci.py                  causal impulse detector + retracement engine
                                    (Fib levels tested against non-Fib CONTROL_LEVELS)
    liquidity.py                   ESTIMATED_STOP_LIQUIDITY pools + sweep detector
                                     (ICEBERG_DATA_UNAVAILABLE, never claimed)
    feature_bar.py                  per-symbol causal feature-bar assembly (the "engine")
  strategies/
    base.py                EntryState lifecycle, Signal/RejectedCandidate, run_checklist
    opening_range.py         Strategy A: continuation/retest/failed_breakout/sweep_reversal
    trend_pullback.py         Strategy D
    fib_pullback.py            Strategy E (parameterized by level)
    structure_continuation.py   Strategy B
    structure_reversal.py        Strategy C
    significant_move.py           Strategy F (STRONG/MODERATE/WEAK move classifier)
  risk/
    sl_models.py           FIXED_ATR, STRUCTURE_INVALIDATION, SWING_EXTREME,
                             OR_OPPOSITE_BOUNDARY, VOLATILITY_ADAPTIVE
    tp_models.py             FIXED_1/1.5/2/3R, ATR_TARGET, STRUCTURE_TARGET
    exit_models.py             FIXED, STRUCTURE, TRAILING_ATR, TRAILING_SWING,
                                 BREAKEVEN_1R, PARTIAL_1R_RUNNER, TIME_BASED, SESSION_CLOSE
    position_sizing.py           fixed-fractional & vol-adjusted lots, Kelly (diagnostic-only),
                                   RiskLimits/RiskGuardState
    portfolio.py                   hedge cases A-G, exposure netting, realized correlation
  backtest/
    engine.py                event-driven backtest: Strategy.scan -> SL/TP -> simulate_trade
    metrics.py                 expectancy/PF/Sharpe/Sortino/drawdown/MAE/MFE
    validation.py                 walk-forward folds, bootstrap CI, permutation control,
                                    Benjamini-Hochberg FDR, verdict labeler
    ablation.py                     baseline -> +bias -> +structure incremental test
  run_experiments.py       orchestrator: 8 symbols x 12 strategy configs x
                             SL/TP/exit/risk/hedge/ablation sweeps -> research/results/*.json
web/app.py                Dash/Plotly terminal: 12 tabs incl. candle replay + trade inspector
audit/
  RESEARCH_CARDS.md         Phase 0 external research (18 cards)
  PHASE_7_MULTI_STRATEGY_HEDGE_BACKTEST.md   Phase 7 findings report
  SAFETY_REPORT.md            Phase 7 governance record
```

## 2. Reusable components (consume real data with ZERO modification)

These modules operate purely on a `pandas.DataFrame` with a tz-aware
`DatetimeIndex` and `open/high/low/close(/spread)` columns — they have no
dependency on how that DataFrame was produced, so real historical data in
the same shape flows through unchanged:

- `research/data/loaders.py` (resampling)
- `research/data/quality.py` (audit)
- `research/core/atr.py`, `candle_anatomy.py`, `structure.py`, `regime.py`,
  `bias.py`, `fibonacci.py`, `liquidity.py`, `sessions.py`,
  `feature_bar.py`
- All of `research/strategies/*.py`
- All of `research/risk/*.py`
- All of `research/backtest/*.py`
- `web/app.py` (reads only the JSON artifacts in `research/results/`,
  agnostic to how they were generated)

This is not incidental — `research/core/feature_bar.py`'s
`SymbolEngineData` was deliberately built as the single interface every
downstream module consumes, specifically so a data-source swap would not
require touching strategy/risk/backtest/validation logic (this was stated
as the intended design in the Phase 7 report's Section 26).

## 3. Synthetic-only component

- `research/data/synthetic.py` is the **only** module that is
  synthetic-specific. It has no real-data equivalent yet (see Section 4).
- `research/run_experiments.py` currently calls
  `generate_multi_symbol_dataset` directly — this orchestrator, not the
  engine underneath it, is what needs a real-data adapter substituted in
  (Section 5).

## 4. Real-data gap: **no real data source exists or is reachable in this environment**

This is the central finding of this audit, checked directly rather than
assumed:

- **Local filesystem**: searched for `*.hst` (MT5 native history files),
  any path containing `MT5`/`mt5`, `histdata`, `dukascopy`, and any
  `*.csv` outside `node_modules`/the Python venv, across the whole
  container (`find / -maxdepth 6 ...` and a `/mnt/user-data` check for
  user-supplied files). **Result: nothing found.** No MT5 terminal, no
  exported history, no CSV/parquet market data anywhere in this session.
- **Network**: this session's outbound proxy was tested directly against
  five real financial-data hosts (Yahoo Finance `query1.finance.yahoo.com`,
  FRED `fred.stlouisfed.org`, Alpha Vantage, HistData.com, Binance data).
  **Every single one returned a `403` "CONNECT tunnel failed" —
  `connect_rejected: organization policy` from the proxy itself,** not a
  transient failure. The proxy's own allowlist (`__agentproxy/status`)
  confirms only package registries (pypi.org, npm, crates.io, Go proxy)
  bypass the proxy; no financial-data host is reachable from here under
  any circumstance available to this session.
- **MT5 itself**: MetaTrader 5 requires either a native Windows install or
  Wine; this is a headless Linux container with no display server and no
  such binary present. There is no path to running an MT5 terminal here
  even if a broker login were supplied.

**Conclusion: Phase 8C's real-data requirement cannot be met from inside
this environment, by any means available to this session.** This is not
a permissions question this session can route around (per the standing
instruction never to disable TLS verification or bypass the proxy) — it
is a hard boundary of the sandbox. See the note to the user at the end of
this document for the only two ways forward.

## 5. Components that would require a new adapter (if real data becomes available)

If the user supplies real historical OHLCV data (e.g., an uploaded
CSV/parquet export from their own MT5 terminal or broker), exactly one
new module is needed:

- **`research/data/real_data.py`** (to be built in Phase 8C): a loader
  that reads a user-supplied file (CSV/parquet) into the same
  `timestamp, open, high, low, close, volume/tick_volume, spread, symbol,
  timeframe` schema `research/data/synthetic.py` already produces (minus
  the hidden `ground_truth_regime` column, which is a synthetic-only
  diagnostic and has no real-data counterpart), normalizes timestamps to
  UTC, and runs the existing `research/data/quality.py` audit against it.
  **No other module needs to change** — this is the direct payoff of the
  Section 2 interface design.
- **`research/run_experiments.py`** would need a data-source flag (real
  file path vs. synthetic generator) so the two are never silently mixed
  in one results directory, per the absolute rule "do not mix synthetic
  and real results." The cleanest implementation: real-data runs write to
  a separate `research/results_real/` directory with its own manifest
  declaring the source file's hash and provenance, never overwriting or
  merging with `research/results/` (synthetic).

## 6. Files proposed for modification (Phase 8, once/if real data exists)

```
research/data/real_data.py          NEW
research/run_experiments_real.py    NEW (or a --source flag on the existing orchestrator)
audit/PHASE_8B_EXTERNAL_RESEARCH.md NEW
audit/PHASE_8_REAL_DATA_MULTI_STRATEGY_HEDGE_BACKTEST.md   NEW (final report, once real
                                                              experiments exist to report)
```

No existing Phase 7 file requires modification to support real data —
per Section 2, the entire feature/strategy/risk/backtest/validation stack
is already source-agnostic.

## 7. Files forbidden from modification

Everything outside `research/`, `web/`, `audit/` — i.e., the actual Astro
site:

```
src/**
public/**
astro.config.mjs
package.json
package-lock.json
tsconfig.json
.vscode/**
netlify/**
```

There is no MT5 EA, no broker order-routing code, and no "production risk
configuration" anywhere in this repository to forbid touching beyond
those paths — reconfirmed by the Section 3 filesystem search. `git diff`
and hash comparisons against these paths were already clean at the end of
Phase 7 (`audit/SAFETY_REPORT.md`) and are re-verified at the end of this
phase's work (see the governance section of this audit's companion
report once written).

## 8. Timestamp / timezone / DST assumptions carried into Phase 8

Already implemented and verified in Phase 7, reusable as-is:

- All internal timestamps are tz-aware UTC (`research/config.py::UTC`).
- Session classification (`research/core/sessions.py`) converts UTC to
  `America/New_York`, `Europe/London`, `Asia/Tokyo` via `zoneinfo` **per
  timestamp**, not a fixed offset — verified to produce exactly 2 US DST
  transition dates/year in Phase 7's own test.
- NY opening range uses `session_open_utc(date, "09:30", NY_TZ)`, i.e., a
  local-time anchor converted per calendar day — never a hardcoded UTC
  offset.
- Sydney is the one session named in Phase 8's list that Phase 7's
  `sessions.py` does not yet classify (only Asia/Tokyo, London, New York,
  and their overlap). **Gap, to be closed in Phase 8D** if a Sydney
  session distinction proves necessary for any strategy — not otherwise
  assumed to matter.

## 9. Data-quality risks (from Phase 7, applicable to any future real dataset)

`research/data/quality.py::audit_bars` already checks: duplicate
timestamps, non-monotonic index, OHLC integrity violations (high/low
outside open/close/range), missing-bar count against an expected
calendar, and tz-awareness. **Real data would additionally need**: zero/
negative price checks, spread-anomaly checks (e.g., spread <= 0 or
absurdly wide), volume-anomaly checks, and a real weekend/holiday
calendar (the synthetic generator's simplified "every weekday is a full
24h trading day" assumption is not exactly correct for real FX, which has
a Friday-evening/Sunday-evening rollover gap) — none of this exists yet
and is listed as a Phase 8C build item, not implemented today.

## 10. Look-ahead / survivorship risks

- **Look-ahead**: Phase 7 found and fixed one real look-ahead bug (the
  retracement engine's `structure_preserved`/`max_depth_fraction` fields
  originally used a fixed future window instead of stopping at the actual
  decision point — see `audit/PHASE_7_MULTI_STRATEGY_HEDGE_BACKTEST.md`
  Section 4). The fix and its causal-invariant tests carry forward
  unchanged. Every other causal boundary (swing confirmation, resampling,
  regime/bias truncation-invariance, DST) has an inline assertion-based
  test that ran and passed during Phase 7.
- **Survivorship**: not applicable to the synthetic generator (it does not
  drop or select symbols/instruments based on later performance). It
  *would* become a real risk with real historical data if, e.g., only
  currently-listed instruments were used for a multi-year backtest
  (survivorship bias in which pairs "still exist"). This is a real-data-
  only risk with no mitigation implemented yet (there is nothing to
  mitigate against synthetic data) — flagged for Phase 8C's real-data
  loader to document per-dataset, not fixed here.

## 11. Execution-model limitations

`research/risk/exit_models.py::simulate_trade` fills at the exact
`entry_price` passed in (spread-adjusted by `research/backtest/
engine.py::run_backtest`, half-spread against the trader at entry) and
walks forward bar-by-bar for SL/TP/exit checks. Known, documented
limitations carried from Phase 7:

- **No tick-level execution reconstruction** — SL/TP fills are checked
  against bar high/low, not an intrabar path, so a bar that touches both
  SL and TP is not disambiguated by real tick order (Phase 8V explicitly
  calls this out as a required declared limitation, not a bug to silently
  fix without tick data).
- **No commission model** (spread only).
- **No slippage model** beyond the synthetic spread itself.
- These gaps matter more once real (not synthetic) economic conclusions
  are being drawn, which is exactly the case this audit is flagging as
  currently blocked (Section 4).

## 12. Hedge-model limitations

`research/risk/portfolio.py`'s correlation is computed once from the
already-realized trade-outcome series (`_realized_correlation`), not as a
*rolling* correlation/beta computed causally bar-by-bar as Phase 8S now
requires ("correlation must be measured dynamically... never assume
correlation is permanent"). This is a real, identified gap: Phase 7's
hedge engine measures a single static correlation number per case, not a
time-varying one. **Phase 8S will need a new rolling-correlation/beta
module** (`research/risk/hedge.py` or an extension of `portfolio.py`) —
this is buildable against either synthetic or real data as pure
mechanics, independent of the Section 4 real-data blocker.

## 13. Verdict

| Question | Answer |
|---|---|
| Can the Phase 7 architecture support causal real-data replay if given real data? | **YES** — the entire feature/strategy/risk/backtest/validation stack is already source-agnostic (Section 2); only a new loader module is needed. |
| Does real historical data exist anywhere in this environment right now? | **NO** — verified by filesystem search and direct network tests against 5 real data hosts, all rejected by this session's egress policy (Section 4). |
| Can this session obtain real data through any means available to it? | **NO** — this is a sandbox network-policy boundary, not a bug to route around. |

Per Phase 8A's own instruction — **"STOP if the architecture cannot
support causal real-data replay"** — the architecture is not the blocker;
data access is. This is the more favorable of the two possible findings,
and it is reported honestly rather than worked around by quietly
continuing on synthetic data under a "Phase 8" label. **This document
stops here and hands the decision to the user** (see the accompanying
question): either (a) they supply real historical OHLCV data (a CSV/
parquet export from their own MT5/broker terminal, uploaded into this
session), which the Phase 8C loader will be built to accept in a
documented schema, or (b) Phase 8 proceeds only as far as its own rules
allow without real data — building/testing the real-data-capable
*adapter* and the new Phase 8 mechanics (rolling hedge correlation, entry
families 8N, SL/TP/exit staged experiments, walk-forward/purging
machinery, mutation tests) validated with synthetic data **explicitly
under Phase 8C's own "synthetic ONLY for infrastructure/unit tests"
carve-out**, with every economic/edge conclusion downstream of that
labeled `DATA_UNAVAILABLE` or `BLOCKED` rather than reported as if it
came from real markets.

---

**VERDICT**: BLOCKED (real-data acquisition), not blocked (architecture).
**INPUT**: Phase 7 codebase (11 core modules, 6 strategies, 5 risk
sub-systems, validation pipeline), this container's filesystem and
network egress policy.
**METHOD**: static code/interface review (Section 2) + direct empirical
tests (filesystem search, 5-host network probe) for Section 4.
**RESULT**: architecture is real-data-ready; no real data is obtainable
in this session.
**CAUSALITY**: N/A at this stage (no new experiment run).
**LEAKAGE**: none introduced; Phase 7's one known-and-fixed leak
(Section 10) carries forward fixed.
**NEGATIVE_CONTROL**: N/A at this stage.
**MUTATION**: N/A at this stage.
**ROBUSTNESS**: N/A at this stage.
**ECONOMIC_VALUE**: N/A at this stage.
**PRODUCTION_IMPACT**: NONE (no file outside `audit/` was written in this
phase step).
**LIVE_STATUS**: DISABLED (unchanged; no live-trading capability exists
in this repository).
**NEXT_SAFE_ACTION**: ask the user how to proceed (real data upload vs.
adapter-only build under the synthetic-infrastructure carve-out) before
writing any Phase 8C loader against a specific file format, and before
running any experiment whose results could be mistaken for a real-market
finding.
