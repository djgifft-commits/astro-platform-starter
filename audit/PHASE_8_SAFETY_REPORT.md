# Phase 8AJ — Governance / Safety Report

## Pre-Phase-8 baseline

- git HEAD before Phase 8: `2460a816086f02a5a49d85f3c7ef22347888169d`
  (`Add Phase 7 multi-strategy hedge backtest research sandbox`)
- SHA-256 hashes of every file under `src/`, `public/`, `astro.config.mjs`,
  `package.json`, `package-lock.json`, `tsconfig.json` recorded before any
  Phase 8 change.

## Post-Phase-8 verification

```
git diff --stat -- src astro.config.mjs package.json package-lock.json tsconfig.json public
  -> EMPTY

sha256sum comparison of every production file, pre- vs. post-Phase-8
  -> IDENTICAL, byte-for-byte
```

**PRODUCTION_IMPACT = NONE.**

## What changed in Phase 8

Only paths under `research/`, `web/`, `audit/` — same governance boundary
as Phase 7. New files:

```
audit/PHASE_8A_ARCHITECTURE_AUDIT.md
audit/PHASE_8B_EXTERNAL_RESEARCH.md
audit/PHASE_8_REAL_DATA_MULTI_STRATEGY_HEDGE_BACKTEST.md
audit/PHASE_8_SAFETY_REPORT.md
research/data/real_data.py
research/core/provenance.py
research/risk/hedge.py
research/backtest/{bias_experiment,ablation_matrix,trend_only,negative_controls,
                    strategy_selector,no_trade_funnel,robustness,out_of_sample,
                    mutation_testing}.py
research/run_experiments_phase8.py
```

Modified (all under `research/` or `web/`):
`research/backtest/engine.py` (exit-side spread cost fix, spread_multiplier),
`research/backtest/validation.py` (purged/embargoed folds),
`research/config.py` (M30 timeframe), `research/core/bias.py` (4-state
bias), `research/core/feature_bar.py` (M30 wiring), `research/core/
liquidity.py` (equal-highs/lows, density), `research/core/regime.py`
(EXPANSION/CONTRACTION, structure_state), `research/data/loaders.py` (M30),
`research/risk/sl_models.py` (2 new SL models), `research/risk/
tp_models.py` (OR_EXTENSION), `research/strategies/{fib_pullback,
significant_move,trend_pullback}.py` (meta fields for new SL models,
negative-control hook), `web/app.py` (9 new Phase 8 tabs).

`.gitignore`: added `research/results_8/` (Phase 8 generated artifacts),
same treatment as Phase 7's `research/results/`.

A temporary one-off continuation script
(`research/run_experiments_phase8_resume.py`, used only to recover from a
mid-run JSON-serialization crash without re-running already-completed
steps) was deleted after use, per its own docstring declaring it "not a
permanent module."

## Live trading / execution state

Unchanged from Phase 7: **LIVE_TRADING = DISABLED**. No execution venue,
broker connection, or order-routing code exists anywhere in this
repository, in Phase 7 or Phase 8. `research/data/real_data.py` (the new
real-data loader) reads a local CSV/parquet file path and nothing else —
it makes no network calls and was only ever run against a synthetic
fixture in this session (see audit/PHASE_8A_ARCHITECTURE_AUDIT.md Section
4 for why no real data exists here).

## Mutation testing

`research/backtest/mutation_testing.py` intentionally introduces 7 of the
mutations named in Phase 8AI (future-bar access, forming-bar inclusion,
wrong DST/timezone handling, wrong swing confirmation, wrong spread
direction, train/test contamination, disabled cost) against in-memory
copies only — no file on disk is ever mutated, so "restore byte-
identically" is satisfied trivially. All 7 were **DETECTED** on the final
run (`research/results_8/mutation_tests.json`); one test (train/test
contamination) initially had a bug in the TEST's own constructed scenario
(the injected "overlapping" trade didn't actually straddle a fold
boundary), found and fixed during this session, after which it correctly
detected the mutation.

## Commits

- `2460a81` — Phase 7 (baseline for this phase)
- `8bc7859` — Phase 8 new mechanics + real-data-loader + engine fixes
- `6044168` — Timestamp JSON-key bugfix in the hedge correlation report

All pushed to `claude/multi-strategy-hedge-backtest-sa7cer`.

## STOP

Per Phase 8AJ/8AK and the MASTER COMMAND's absolute rules: this phase
remains research/backtesting-only. No production integration or live-
trading step has been taken. Any future extension to real market data
requires the user to supply it (see audit/PHASE_8A_ARCHITECTURE_AUDIT.md)
and requires fresh human authorization before any production wiring.
