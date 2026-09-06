# Phase 9A — Repository and Governance Audit

**No code was written or modified to produce this document.** Per the
Phase 9 instructions, this is audit-only; Phase 9B onward requires a
separate, explicit continuation.

---

## 1-3. HEAD / branch / git status

```
HEAD:    6818c76ff9f2c54b65a67c7b370fafe161989ed7
Branch:  claude/multi-strategy-hedge-backtest-sa7cer
Status:  clean (nothing to commit, up to date with origin)
```

Recent history:

```
6818c76 Add Phase 8 final report and safety audit
6044168 Fix Timestamp JSON-key bug in rolling hedge correlation report
8bc7859 Add Phase 8 real-data-ready engine upgrades and new research mechanics
2460a81 Add Phase 7 multi-strategy hedge backtest research sandbox
86266f5 chore(deps): update dependency astro to v5.17.1 (#422)   <- pre-existing template history
```

## 4-5. Production baseline / snapshot

SHA-256 of every file under `src/`, `public/`, `astro.config.mjs`,
`package.json`, `package-lock.json`, `tsconfig.json` (34 files) recorded
to `/tmp/phase9_prod_hashes.txt` and diffed against the pre-Phase-8
baseline recorded in Phase 8's own audit: **byte-identical, zero diff.**
`git diff --stat` against those same paths is empty. Production has not
moved since before Phase 7 began.

## 6-7. Live trading / broker execution

Searched `research/` and `web/` for `order_send`, `MetaTrader`, `mt5.`,
broker-execution, and live-trading patterns. The only two matches are
disclaimer text, not code:

- `research/run_experiments.py:6` — *"This script performs NO live
  trading, connects to no broker..."*
- `web/app.py:108` — UI banner text: *"SYNTHETIC DATA ONLY -- no
  MT5/broker connection, no live trading..."*

No `import MetaTrader5`, no `mt5.initialize`, no `mt5.order_send`, no
broker SDK, no order-routing code exists anywhere in this repository —
confirmed by direct grep, not assumed. **LIVE_TRADING = DISABLED**,
unchanged since before Phase 7 (there was never a live-trading capability
to disable in this repo — see Phase 8A Section 0).

## 8. Open positions / orders / deals

Not applicable by construction: no execution venue (real or simulated-
live) exists anywhere in this project. Every backtest is an offline,
one-shot simulation over an in-memory synthetic price series
(`research/backtest/engine.py::run_backtest`); nothing persists a
position across runs or connects to anything that could hold one.

## 9. Diagnostic log count

`0` — no `.log` files exist anywhere in the repository outside
`node_modules`/`.venv`/`.git`.

## 10. Research artifact hashing

All 58 research/web/audit source files (`.py` + `.md`, excluding
generated `results/`/`results_8/` JSON) hashed individually; the
combined hash of that file list is `c708d4b8b446f5b226b2e0c4602b8dfbfec7bc89e644d3d17cffaefffe79c78d`
(recorded to `/tmp/phase9_research_hashes.txt` for future drift
comparison). Generated result JSON in `research/results/` and
`research/results_8/` is gitignored and intentionally excluded from this
hash (it is reproducible output, not source).

## 11. Every Phase 8 file

From `git show --stat` on the three Phase 8 commits:

**New (Phase 8):**
```
audit/PHASE_8A_ARCHITECTURE_AUDIT.md
audit/PHASE_8B_EXTERNAL_RESEARCH.md
audit/PHASE_8_REAL_DATA_MULTI_STRATEGY_HEDGE_BACKTEST.md
audit/PHASE_8_SAFETY_REPORT.md
research/data/real_data.py
research/core/provenance.py
research/risk/hedge.py
research/backtest/ablation_matrix.py
research/backtest/bias_experiment.py
research/backtest/mutation_testing.py
research/backtest/negative_controls.py
research/backtest/no_trade_funnel.py
research/backtest/out_of_sample.py
research/backtest/robustness.py
research/backtest/strategy_selector.py
research/backtest/trend_only.py
research/run_experiments_phase8.py
```

**Modified (Phase 8, on top of Phase 7 originals):**
```
research/backtest/engine.py        (exit-side spread cost fix, spread_multiplier)
research/backtest/validation.py    (purged_embargoed_folds)
research/config.py                 (M30 timeframe)
research/core/bias.py              (4-state BULLISH/BEARISH/NEUTRAL/CONFLICTED)
research/core/feature_bar.py       (M30 wiring)
research/core/liquidity.py         (equal-highs/lows, liquidity_density)
research/core/regime.py            (EXPANSION/CONTRACTION, structure_state)
research/data/loaders.py           (M30)
research/risk/sl_models.py         (FIBONACCI_INVALIDATION, LIQUIDITY_BASED)
research/risk/tp_models.py         (OR_EXTENSION)
research/strategies/fib_pullback.py       (impulse price meta fields)
research/strategies/significant_move.py   (strength_override negative-control hook)
research/strategies/trend_pullback.py     (impulse price meta fields)
web/app.py                          (9 new [P8]-prefixed tabs)
research/README.md
.gitignore                          (research/results_8/)
```

## 12. Existing strategy/feature/backtesting components (current full map)

```
research/
  config.py                 constants, timeframes (incl. M30), DATA DISCLOSURE
  data/
    synthetic.py              SYNTHETIC_DATA generator (8-state regime, correlated)
    loaders.py                  causal resampling M1->M5/M15/M30/H1/H4/D1
    quality.py                   gap/duplicate/OHLC/DST audit + causality asserts
    real_data.py                  real CSV/parquet loader (unused with real data so far)
  core/
    sessions.py                tz-aware sessions + NY opening range (DST-correct)
    atr.py                       Wilder ATR
    candle_anatomy.py              OHLC geometry + 19-pattern recognizer
    structure.py                    causal swings, HH/HL/LH/LL, BOS/CHOCH
    regime.py                        10-state causal classifier + structure_state
    bias.py                           5-state + 4-state MTF directional bias
    fibonacci.py                       impulse + retracement engine w/ control levels
    liquidity.py                        ESTIMATED_STOP_LIQUIDITY pools/sweeps/equal-hi-lo
    feature_bar.py                       per-symbol causal feature-bar assembly ("the engine")
    provenance.py                         feature causal-timestamp auditing
  strategies/                6 families: opening_range (4 variants), trend_pullback,
                               fib_pullback, structure_continuation, structure_reversal,
                               significant_move (3 strength tiers)
  risk/
    sl_models.py                7 models (5 Phase7 + 2 Phase8)
    tp_models.py                 7 models (6 Phase7 + 1 Phase8)
    exit_models.py                 8 models
    position_sizing.py              fixed-fractional/vol-adjusted, Kelly diagnostic-only
    portfolio.py                      static-correlation hedge cases A-G
    hedge.py                           rolling correlation/beta, regime-bucketed
  backtest/
    engine.py                  event-driven backtest (corrected cost model)
    metrics.py                   expectancy/PF/Sharpe/Sortino/drawdown/MAE/MFE
    validation.py                 walk-forward, purged/embargoed folds, bootstrap,
                                    permutation, BH-FDR, verdict labeler
    ablation.py                     Phase7 2-flag ablation
    ablation_matrix.py                Phase8 11-stage generalized ablation
    bias_experiment.py                nested BIAS/+STRUCTURE/+REGIME test
    trend_only.py                      ALL/TREND/STRONG_TREND comparison
    negative_controls.py                permutation controls (structure/strength/hedge)
    strategy_selector.py                 regime-conditional router vs random/always-on
    no_trade_funnel.py                    candidate funnel + rejection reasons
    robustness.py                          parameter-perturbation grid
    out_of_sample.py                        locked final test (seed 424242)
    mutation_testing.py                      7 intentional-bug detection tests
  run_experiments.py          Phase 7 orchestrator -> research/results/
  run_experiments_phase8.py    Phase 8 orchestrator -> research/results_8/
web/app.py                    Dash/Plotly terminal, 21 tabs (12 Phase7 + 9 [P8])
audit/                        7 reports (Phase 0/7/8A/8B/8/8-safety + this one)
```

## 13. Duplicated implementations found

- **`_regime_at_entry`** is defined nearly identically in both
  `research/backtest/trend_only.py` and `research/backtest/
  strategy_selector.py` (each a 3-line wrapper around
  `row_asof(ctx.feature_bars, ts)["regime_regime"]`). Minor; a Phase 9
  cleanup could hoist this into `research/strategies/base.py` alongside
  `row_asof`/`window_after`, but it is not causing any correctness risk
  today.
- **`main()`, `dump()`, `json_default()`, `strategy_configs()`,
  `regime_breakdown()`** are duplicated between `research/
  run_experiments.py` (Phase 7) and `research/run_experiments_phase8.py`
  (Phase 8). This is **intentional**, not accidental: Phase 8A's own
  governance rule ("do not mix synthetic and real results... never
  silently overwrites") is why each phase's orchestrator writes to its
  own `results*/` directory with its own copy of these helpers rather
  than sharing mutable state. **Recommendation for Phase 9**: if Phase 9
  adds a third orchestrator (`run_experiments_phase9.py`), extract
  `dump()`/`json_default()` into a shared `research/backtest/
  reporting.py` utility rather than copy-pasting a third time — the
  serialization helpers have no reason to differ between phases, only
  the experiment list does.
- No duplicate ATR, regime, structure, or Fibonacci implementations exist
  — every module that could plausibly be re-derived (e.g., a new
  strategy needing ATR) imports the single existing implementation.
  Verified by grepping for duplicate top-level `def`/`class` names across
  `research/` (only the two cases above recurred).

## 14. Functions already at "production parity" (i.e., reusable as-is by Phase 9 with zero rework)

Every module in `research/data/`, `research/core/`, `research/
strategies/`, `research/risk/`, and `research/backtest/` operates on a
plain `pandas.DataFrame` with a tz-aware `DatetimeIndex` and OHLC(+spread)
columns, with no dependency on the synthetic generator specifically. This
was a deliberate Phase 7 design choice, re-confirmed as still true in
Phase 8A Section 2, and remains true today — nothing in Phase 8 broke
that property. Concretely, **all of the following can be pointed at real
data with zero code change**, the day real data exists:

- Resampling/quality (`data/loaders.py`, `data/quality.py`)
- Sessions/opening range (`core/sessions.py`) — already handles Phase 9's
  exact "1UP RANGE / 2DOWN RANGE" opening-range-breakout setup (NY 09:30
  local, first 15-minute candle, DST-correct)
- ATR, candle anatomy, structure, regime, bias, Fibonacci, liquidity
  (`core/*.py`)
- All 6 strategy families (`strategies/*.py`)
- All SL/TP/exit models and position sizing (`risk/*.py`)
- The backtest engine, metrics, and the entire validation pipeline
  (walk-forward, purge/embargo, bootstrap, permutation, BH-FDR,
  mutation-tested) (`backtest/*.py`)
- The web terminal (`web/app.py`) — reads only JSON artifacts, agnostic
  to their provenance

The **only** genuinely new work Phase 9 needs before it can run against
real data is the data acquisition itself (still `BLOCKED` per Section 15
below) and the specific new instrumentation Phase 9 asks for that Phase 8
does not yet have (see next section).

## 15. What Phase 9 can reuse vs. what is genuinely new

**Reuse as-is (no rebuild needed):** essentially everything listed in
Section 14. In particular, Phase 9K's "1UP RANGE / 2DOWN RANGE" opening-
range breakout with Breakout/Retest/Reversal entry families is **already
fully implemented** as `research/strategies/opening_range.py`'s
`continuation`/`retest`/`sweep_reversal`/`failed_breakout` variants,
built in Phase 7 and exercised again in Phase 8 — Phase 9M/9K should
extend and re-validate this, not re-write it.

**Genuinely new, not yet built anywhere in Phase 7/8:**

- A `MARKET_CONTEXT` composite object bundling trend/volatility/liquidity/
  session/structure/bias into one structure (Phase 9E) — today these
  exist as separate DataFrame columns on `feature_bars`, never assembled
  into a single named object.
- An explicit `ENTRY_DECISION` object with `score`/`reasons`/
  `rejected_reasons` fields (Phase 9L) — today's `Signal`/
  `RejectedCandidate` dataclasses (`strategies/base.py`) carry equivalent
  information but not in this exact shape.
- Position-overlap/portfolio-constraint gating with explicit
  `BLOCKED_POSITION_OVERLAP` / `BLOCKED_RISK` / `BLOCKED_CORRELATION` /
  `BLOCKED_SESSION` outcome codes (Phase 9S) — `research/risk/
  position_sizing.py`'s `RiskLimits`/`check_risk_limits` covers the
  underlying limit checks but returns a flat violation list, not a
  per-candidate causal decision trace integrated into the funnel.
- Protected highs/lows and internal-vs-external structure distinction
  (Phase 9D) — `core/structure.py` has swing highs/lows and BOS/CHOCH,
  but not the internal/external/protected vocabulary Phase 9 names
  specifically.
- The data-source abstraction with the exact metadata schema Phase 9B
  specifies (provider, server_timezone, acquisition_timestamp,
  data_version, etc.) — `research/data/real_data.py` has a subset
  (source_path, data_hash, provenance) but not the full field list.
- Sydney session classification — `core/sessions.py` currently covers
  Asia (Tokyo)/London/New York/overlap only, a gap already flagged in
  Phase 8A Section 8, still open.

## Verdict

No unexpected production drift exists. No governance violation found.
The repository is in a clean, fully-understood, reproducible state, and
the architecture remains real-data-ready. Phase 9 should build the
genuinely-new items in Section 15 and explicitly re-validate (not
re-implement) everything in Section 14, and should resolve the Section
13 orchestrator-helper duplication before adding a third near-identical
`run_experiments_phase9.py` if that pattern continues.

---

**VERDICT**: CLEAN — no drift, no violation, architecture unchanged and
still real-data-ready.
**FILES_CHANGED**: none (audit-only; this document is the only new file).
**PRODUCTION_IMPACT**: NONE (byte-identical hashes, verified).
**DATA_USED**: none (no experiment run in this phase step).
**TESTS**: none run in this phase step (governance/static audit only).
**MUTATION**: not applicable to an audit-only step; Phase 8's 7 mutation
tests remain in the codebase and were not re-run here (no code changed to
warrant it).
**CAUSALITY**: not applicable (no new experiment).
**LEAKAGE**: not applicable (no new experiment).
**RESULTS**: see Sections 1-15 above.
**LIMITATIONS**: real historical data remains unobtainable in this
environment (re-verified by a fresh network probe against 3 real-data
hosts, all still `403` org-policy-denied, and a fresh filesystem search
for any newly-supplied data file — none found). This blocks any Phase 9B
"real data gate" from ever opening inside this session; the gate's logic
can and should still be built (per Phase 8's own precedent), but it will
have nothing to admit until the user supplies data directly.
**NEXT_SAFE_ACTION**: await explicit authorization to proceed to Phase
9B. Do not begin building the data-source abstraction, calendar engine,
or any strategy code until that authorization is given, per this phase's
own instruction to stop here.
