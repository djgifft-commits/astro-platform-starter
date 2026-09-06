# Phase 9B — 1UP/2DOWN Opening-Range Strategy Research + Multi-Timeframe Decision Engine

**Authorization**: explicit, scoped to Phase 9B only ("DO NOT enable live
trading. DO NOT connect to MT5. DO NOT modify production trading code. DO
NOT fabricate real-market results where real historical data is
unavailable."). All four constraints held throughout: live trading was
never enabled, no MT5/broker code was written, zero production files
(`src/`, `public/`, `astro.config.mjs`, `package.json`,
`package-lock.json`, `tsconfig.json`) changed, and every result below is
labeled synthetic-validation, never presented as real-market evidence.

---

## 0. Read this first — the central finding of Phase 9B

**No opening-range entry family reached `EDGE_ESTABLISHED` on synthetic
data.** Across the full 3-entry-family x 8-symbol matrix (24 cells, 300
days each), 21 of 24 cells had **negative** expectancy. The cells that
DID reach statistical significance in isolation (bootstrap CI excludes
zero, permutation p ≤ 0.05) were overwhelmingly the **negative**-expectancy
ones — AUDUSD, USDCHF, and NZDUSD breakout/retest survive
Benjamini-Hochberg correction across all 24 cells, and all five surviving
cells lose money (expectancy -0.31R to -0.74R). The most statistically
defensible finding in this entire research phase is that the 1UP/2DOWN
breakout and retest families, as built, have a **detectable negative
edge** on several pairs — not a positive one.

The one directionally interesting cell — XAUUSD reversal, n=30,
expectancy +0.58R, bootstrap CI excludes zero, permutation p=0.05 — does
**not** survive Benjamini-Hochberg correction across the 24 tested cells
and has too small a sample (n=30) to claim robustness. It is reported as
`TRADING_EDGE_UNPROVEN`, worth a dedicated, pre-registered follow-up on
more data, not as a discovered edge.

This matches Phase 8's own conclusion (Phase 7's one `EDGE_ESTABLISHED`
cell did not replicate under perturbation or a locked out-of-sample test)
and extends it: **every genuinely new Phase 9B mechanism tested — Fibonacci
depth, named candlestick patterns, the three entry families, every new
SL/TP model — either showed no information beyond what was already known,
or a negative one.** This is reported as the honest result of the
research, per the MASTER COMMAND's explicit instruction that discovering
"no edge" or "a negative pattern" is a valid and useful outcome, not a
failure of the phase.

---

## 1. Objective and scope

Turn the Phase 7 `OpeningRangeBreakout` strategy into a causally rigorous,
explicit-state-machine system: NY opening range (15-minute definition),
5-minute breakout/retest/reversal confirmation, 1-minute entry execution,
a directional bias hierarchy that never assumes direction from a boundary
break alone, and full replay/inspection of every decision. Test costs,
regimes, SL/TP models, risk levels, and portfolio-level gating. Visualize
every trade and explain every entry/rejection. No look-ahead, no forced
trades, no strategy relaxation after seeing results, no fabricated data.
Stop after Phase 9B for authorization before Phase 9C.

## 2. Data source and disclosure

**100% synthetic.** `research/data/synthetic.py`'s regime-switching,
multi-symbol, correlated FX price generator — the same engine used in
Phases 7-9A, unchanged. No MT5, broker, or real-market data connection
exists anywhere in this repository (re-verified in Section 29 below).
Every number in this report is an engine-validation result on labeled
synthetic data, never a claim about real market behavior. Per Phase 9A's
re-verification, the real-data network blocker still holds in this
environment (3 real-data hosts still 403 org-policy-denied); the
"real-data-first, STOP if unavailable" policy therefore correctly routed
this entire phase to the SYNTHETIC VALIDATION label.

## 3. Architecture and reuse map

Nothing below was reimplemented; everything routes through the existing
Phase 7/8 engine:

| Component | Reused from | New in Phase 9B |
|---|---|---|
| Market structure (swings, BOS/CHOCH) | `core/structure.py` | `core/protected_levels.py` — internal/external layering via different `confirm_bars` on the same swing algorithm |
| Regime / trend / volatility | `core/regime.py` | none (read as-is) |
| HTF directional bias | `core/bias.py` | none (read as-is) |
| Fibonacci retracement | `core/fibonacci.py` | depth-bin classification + nested information test |
| Liquidity pools/sweeps | `core/liquidity.py` | none (read as-is) |
| Candle anatomy / named patterns | `core/candle_anatomy.py` | primitive-vs-pattern ablation test |
| Sessions / NY opening range | `core/sessions.py` | Sydney session added; OR construction reused as-is |
| Validation (bootstrap/permutation/BH-FDR/walk-forward) | `backtest/validation.py` | none (read as-is) |
| Cost modeling | `backtest/engine.py` | 2 new SL models, 2 new TP models wired in |
| Risk limits / guard state | `risk/position_sizing.py` | `backtest/portfolio_gating.py` — position-overlap/correlation orchestration (composes, does not duplicate, the existing checker) |

Genuinely new: `core/market_context.py` (MARKET_CONTEXT),
`strategies/entry_decision.py` (ENTRY_DECISION), `core/protected_levels.py`,
`strategies/opening_range_v2.py` (the state machine itself),
`backtest/{regime_gating,no_trade_funnel_v2,portfolio_gating,
fibonacci_depth_experiment,candle_pattern_ablation}.py`, and
`backtest/out_of_sample_phase9b.py`.

## 4. OR state machine

`ORState` enum, all 12 states as specified: `OR_CREATED`, `OR_ACTIVE`,
`OR_BROKEN_UP`, `OR_BROKEN_DOWN`, `OR_RETEST`, `OR_REVERSAL`,
`OR_INVALIDATED`, `OR_EXPIRED`, `ENTRY_CANDIDATE`, `ENTRY_CONFIRMED`,
`TRADE_BLOCKED`, `TRADE_EXECUTED`. Every NY session day gets a full
`ORStateEvent` history (state, timestamp, detail) retained for replay —
see Section 28 (Decision Inspector). Example, an actual executed day from
the sample (`decision_inspector_sample.json`, EURUSD breakout,
2024-01-01):

```
14:30  OR_CREATED     OR window opened
14:45  OR_ACTIVE      OR_high=1.08668 OR_low=1.08607
14:50  OR_BROKEN_DOWN M5 close 1.08598 < OR_low
14:50  ENTRY_CANDIDATE bias=BEARISH
14:59  ENTRY_CONFIRMED M1 bearish_engulfing
14:59  TRADE_EXECUTED entry_price=1.08606
```

## 5. Multi-timeframe architecture and causality proof

Three genuinely separate stages: M15-equivalent (the 15-minute OR window
itself), M5 breakout/retest/reversal *confirmation*, M1 entry *execution*
strictly after the M5 confirmation timestamp — the one behavior change
from Phase 7 (which entered directly on the M5 confirmation bar). Proven
causal three ways: (1) `window_after()`'s `searchsorted(..., side="right")`
guarantees the M1 search window starts strictly after the confirmation
timestamp — covered by mutation test `wrong_m1_entry_timing`; (2) the
example above shows OR_BROKEN_DOWN (M5, confirmed at :50) followed by
ENTRY_CONFIRMED (M1, at :59, on the M1 grid, not the M5 grid); (3) an
explicit verification pass over all 179 breakout/retest/reversal signals
generated during development confirmed zero timestamp-order violations
and that every entry timestamp lands exactly on the M1 grid.

## 6. MARKET_CONTEXT object

`core/market_context.py`'s `MarketContext` dataclass carries exactly the
fields specified: symbol, session, timestamp, timeframe, htf_bias +
bias_confidence, market_regime, trend_state, volatility_state,
swing_structure (external) + internal_structure, protected_high/low,
last_bos_or_choch, liquidity_state, or_state/or_high/or_low/or_width/
price_location_vs_or, atr, spread, cost_assumption. Pure aggregation via
`row_asof()` — no new computation. Verified during development to
correctly surface genuine cross-source disagreement (a sample showed
`htf_bias=LONG` simultaneous with `market_regime=STRONG_DOWNTREND`) rather
than silently picking one — the object does not paper over conflicts.

## 7. Directional bias hierarchy

`classify_bias_hierarchy()` votes across 5 independent sources (HTF bias,
external structure, internal structure, regime trend, liquidity-implied
direction) and returns BULLISH/BEARISH/NEUTRAL/CONFLICTED — **never**
assumed from the OR boundary break itself. CONFLICTED requires ≥2
conflicting votes with ≥1 agreeing; mutation test
`wrong_strategy_selection_bias_hierarchy` confirms a naive "just trust
htf_bias" implementation would be caught (constructed case: htf_bias
agrees, 3 other sources disagree → correctly CONFLICTED, not BULLISH).
In the no-trade funnel (Section 21), `bias_valid` is consistently the
single largest rejection stage across all three families and all 8
symbols — this hierarchy is doing real, frequent gating work, not a rubber
stamp.

## 8. Entry families

Three, each a distinct code path in `OpeningRangeStateMachine`:

- **Breakout**: M5 close beyond the OR boundary → bias-hierarchy check →
  M1 continuation-candle trigger.
- **Retest**: post-breakout pullback to the boundary (within an
  ATR-scaled buffer, tracked via a causal running extreme) that resumes
  in the breakout direction → same bias + M1 trigger gate. Reports
  Fibonacci depth bin as information, never as a gate (Section 13).
- **Reversal**: a liquidity sweep of the OR boundary followed by a close
  back through OR_mid → same bias + M1 trigger gate.

Result summary (300 days, 8 symbols — full detail in `or_v2_matrix.json`):
breakout and retest execute far more often (36-44% of candidates) than
reversal (13%, gated hard by the `liquidity_event` funnel stage — see
Section 21). None of the three families is unambiguously best: breakout/
retest are the most *frequently* significant, and in the negative
direction; reversal is rarer but produced the one (unconfirmed) positive
signal (XAUUSD, Section 0).

## 9. ENTRY_DECISION object

`strategies/entry_decision.py`'s `EntryDecision` dataclass: decision,
score, reasons, failed_conditions, market_context, entry_type, direction,
confirmation_timestamp, entry_timestamp, confidence, risk_state,
blocking_code — separating CONTEXT / CONFIRMATION / TRIGGER explicitly, as
specified. `from_signal()`/`from_rejected()` convert the strategy layer's
existing `Signal`/`RejectedCandidate` without adding new decision logic.
This is the object the Decision Inspector (Section 28) renders directly.

## 10. Candlestick intelligence: primitives vs. named patterns

Tested whether any of the 20 named patterns in `core/candle_anatomy.py`
add information beyond the primitive close-vs-open direction they are
built from, using the same matched-population, ATR-normalized
forward-return methodology as Phase 8's bias experiment. Baseline is
deliberately un-gated on body strength (an earlier draft's body-strength
gate structurally excluded every small-body pattern — doji, hammer,
pin_bar — from ever being tested; caught and fixed before results were
taken, since that would have made those patterns untestable, not
"uninformative").

**Result: 3 of 80 pattern x symbol combinations (EURUSD 0/20, GBPUSD
0/20, USDJPY 2/20, XAUUSD 1/20) showed `INFORMATION_PRESENT`** — a rate
(~3.75%) consistent with chance under a 5% per-test false-positive rate
and no true effect, especially since no cross-symbol multiple-testing
correction was applied to this specific ablation. **Verdict:
`NO_INFORMATION_DEMONSTRATED`** for named candlestick patterns as a class,
on this synthetic data — the primitive anatomy carries what little signal
exists.

## 11. Market condition classification / regime gating

`backtest/regime_gating.py`'s `gate_trade()` returns exactly
TRADE_ALLOWED / TRADE_BLOCKED_REGIME / _DIRECTION / _STRUCTURE /
_VOLATILITY, checked in a fixed order so every candidate gets exactly one
reason. Ranging markets are **never** silently discarded — every regime
bucket's raw stats are reported (`regime_breakdown_ungated` in
`regime_gating.json`) alongside the gated comparison. Finding: regime
breakdown is noisy and inconsistent across symbols (e.g. EURUSD RANGE
expectancy -0.21R, GBPUSD RANGE expectancy +0.43R — opposite signs on the
same regime label across two symbols), and none of the three gate
configurations (UNGATED / DIRECTION_AGREEMENT_REQUIRED /
STRONG_TREND_REQUIRED) reliably converts the aggregate negative
expectancy into a positive one. Regime gating is not shown to rescue this
strategy.

## 12. Significant-move reuse

`strategies/significant_move.py` and its STRONG_MOVE/MODERATE_MOVE
classification (Phase 7) were read, not reimplemented, wherever OR v2
needed a displacement-strength signal; no new significant-move detection
logic was written in Phase 9B.

## 13. Fibonacci retracement depth — information content after structure is known

Nested test: does the *exact* retracement depth (23.6/38.2/50/61.8/78.6%
and the continuous bins between) add information about continuation
probability, beyond already knowing the impulse's structure was
preserved? Structure-only baseline (all structure-preserved touches,
pooled): n=38,103-41,796 per symbol (4 representative symbols), mean
displacement +0.05 to +0.14 ATR (CI excludes zero — structure preservation
itself IS informative, consistent with Phase 8's finding). **Every one of
the 5 populated depth buckets, on every symbol, was NOT distinguishable
from the structure-only pool.** Verdict:
**`NO_INFORMATION_DEMONSTRATED`** — depth adds nothing once structure
preservation is already known. "Which Fibonacci level" is not doing real
work distinct from the structural fact already captured elsewhere. This
directly satisfies the MASTER COMMAND's instruction not to assume 23.6% is
"strong" or "weak" without testing it — it was tested, and found to carry
no additional information.

## 14. Stop-loss models

Seven total across Phase 8+9B: FIXED_ATR, STRUCTURE_INVALIDATION,
SWING_EXTREME, OR_OPPOSITE_BOUNDARY, VOLATILITY_ADAPTIVE,
FIBONACCI_INVALIDATION, LIQUIDITY-based, plus the new
**BREAKOUT_CANDLE** (stop just beyond the M5 breakout candle's own
opposite extreme). Comparison on the breakout family, 8 symbols
(`sl_tp_v2_comparison.json`): BREAKOUT_CANDLE underperformed FIXED_ATR on
7 of 8 symbols (worse expectancy, e.g. EURUSD -0.295R vs -0.132R), and
outperformed only on XAUUSD (+0.088R vs -0.050R) — not a consistent
improvement. Mutation test `wrong_sl_model_side` confirms the model is at
least implemented correctly (LONG stop below entry, SHORT stop above) —
its underperformance is a genuine finding about the model choice, not a
placement bug.

## 15. Take-profit models

New in Phase 9B: **OR_OPPOSITE_BOUNDARY_TARGET** and **LIQUIDITY_TARGET**,
alongside the existing FIXED_R family (now spanning 0.5R-4R) and
structure/trailing targets. **OR_OPPOSITE_BOUNDARY_TARGET is
catastrophic** — profit factor 0.00 on every single symbol tested,
expectancy -1.40R to -1.80R. Diagnosed during development (not after
seeing this run's numbers) as a genuine conceptual mismatch: for a LONG
breakout above OR_high expecting continuation, OR_low sits in the
*adverse* direction, not a profit target — this concept only fits a
mean-reversion/range-fade strategy, which none of the three OR v2 entry
families are. Per the "never silently fix after seeing bad results" rule,
this is reported as-is rather than patched: **this TP model is
structurally mismatched to continuation/retest/reversal entries** and
should not be offered for them. LIQUIDITY_TARGET is not catastrophic but
also not an improvement (expectancy -0.08R to -0.41R vs FIXED_2R's -0.04R
to -0.61R — mixed, mostly slightly worse). Mutation test
`wrong_tp_model_direction` confirms LIQUIDITY_TARGET's directional logic
itself is correct (LONG target above entry, SHORT below) — the
OR_OPPOSITE_BOUNDARY_TARGET finding is a model-choice problem, not an
implementation bug.

## 16. Risk and portfolio gating

Risk levels 0.25%-1.50% supported via the existing
`fixed_fractional_lots`/`volatility_adjusted_lots` (Phase 8, reused
as-is). New in Phase 9B: `backtest/portfolio_gating.py`,
`simulate_portfolio_gating()` processes trades chronologically across
symbols and applies the existing `check_risk_limits()` (never
reimplemented) plus a correlation check against explicitly-supplied
correlated pairs. **A caught-and-fixed bug**: the original implementation
reset `consecutive_losses` only on an executed win, so once
`MAX_CONSECUTIVE_LOSSES` tripped, a blocked candidate could never be
scored as a win/loss again — the account was **permanently** locked out
for the rest of the backtest (252/257 candidates blocked in the first
failing test run). Fixed by resetting the counter on day-change, matching
the existing daily-PnL reset convention already in the same loop (a
same-day circuit breaker, not a permanent kill switch — this is a genuine
implementation bug fix, not a result-driven parameter change). After the
fix, three hedge pairs were tested (`portfolio_gating.json`): execution
rates ranged 16.5%-52.9%, with `BLOCKED_RISK` (mostly `MAX_OPEN_POSITIONS`
under a deliberately tight limit of 3) dominating on the two pairs with
fewer executed trades. `BLOCKED_CORRELATION` fired on 9-33 candidates per
pair, confirming the correlation gate is live, not a no-op. Mutation test
`wrong_position_overlap_logic` confirms a 3rd concurrently-open position
under `max_open_positions=2` is correctly blocked.

## 17. Hedge engine evaluation

Phase 8's rolling correlation/beta hedge engine (`risk/hedge.py`) was read
and reused for the correlated-pair inputs to portfolio gating (Section
16); no new hedge-effectiveness computation was built in Phase 9B, per
the reuse map (Section 3) — Phase 8's own finding (designed synthetic
correlation is recoverable, regime-dependent) stands unchanged.

## 18. Execution modeling

Reuses the existing `backtest/engine.py::run_backtest` path (spread cost
deducted at both entry and exit, `BacktestConfig.spread_multiplier` for
sensitivity sweeps) — no new execution-modeling capability was invented.
No slippage-beyond-spread, partial-fill, or latency model exists in this
codebase; this is reported as unavailable rather than fabricated, per the
MASTER COMMAND's explicit instruction on this point.

## 19. Data quality and causality validation

The full Phase 2/8 causality suite (`data/quality.py`) applies unchanged.
Phase 9B added three OR-specific causality proofs: (1) `compute_
ny_opening_ranges` provably excludes the bar exactly at the OR close
boundary (mutation test `wrong_or_boundary`); (2) the NY session UTC
anchor correctly shifts by exactly 1 hour across the March 2024
spring-forward DST transition, ruling out a hardcoded-offset bug
(`wrong_session_dst_boundary`); (3) `compute_protected_levels`' causality
was verified via a dedicated truncated-recompute test (recomputing on a
truncated DataFrame reproduces byte-identical historical values) during
development, showing 0 mismatches.

## 20. Backtest design

`walk_forward_folds` (5 folds) and `purged_embargoed_folds` (5 folds,
1-hour embargo) applied to every one of the 24 OR v2 matrix cells — full
per-fold expectancy in `or_v2_matrix.json`. The locked out-of-sample test
(Section 25) additionally provides a genuine held-out, never-touched-until-
reported final check on a fresh seed.

## 21. No-trade funnel (13-stage)

Exact stage sequence: session → regime → bias → structure → liquidity →
breakout → M5 confirmation → M1 trigger → SL → RR → risk → position
overlap → EXECUTE (`no_trade_funnel_v2.py`, `FUNNEL_STAGES`). Dominant
bottleneck by family (8-symbol average, `no_trade_funnel_v2.json`):

- **Breakout**: `bias_valid` (~53-55% of all candidates) is overwhelmingly
  the largest rejection stage — the bias hierarchy is doing most of the
  gating work, well ahead of `m1_trigger` (~3%).
- **Retest**: `bias_valid` (~45%) again dominates, with `range_breakout`
  (no qualifying retest found, ~14-17%) second.
- **Reversal**: `liquidity_event` (no sweep detected, ~48%) is the
  dominant bottleneck, ahead of `bias_valid` (~24-29%) — reversal's low
  execution rate (13%) is explained primarily by how rarely a qualifying
  liquidity sweep occurs, not by the bias check.

Nothing is silently discarded — every rejected candidate's stage is
recorded and reported, ranging markets included.

## 22. Statistical validation

Every one of the 24 OR v2 matrix cells received: bootstrap mean-R
confidence interval (500 resamples), permutation negative control (500
permutations), Benjamini-Hochberg correction across all 24 cells jointly
(not per-symbol), 5-fold walk-forward, and 5-fold purged+embargoed
cross-validation. Result distribution: 14/24 `NO_INFORMATION_DEMONSTRATED`,
5/24 `INFORMATION_PRESENT_BUT_NOT_ROBUST` (all negative-expectancy, BH-FDR
survivors), 4/24 `INFORMATION_PRESENT` (significant in isolation, does not
survive BH-FDR — 3 negative, 1 positive/XAUUSD-reversal), 1/24
`INSUFFICIENT_SAMPLE`. **Zero cells reached `EDGE_ESTABLISHED`.**

## 23. Cost sensitivity

COST_NEUTRAL / BASE_COST / ADVERSE_COST / STRESS_COST (0x/1x/2x/5x spread)
on the breakout family, all 8 symbols. EURUSD: -0.024R → -0.132R → -0.321R
→ -0.876R. XAUUSD: -0.032R → -0.050R → -0.094R → -0.149R. **Costs make an
already-negative result worse, but are not the primary cause of the
negative expectancy** — even at COST_NEUTRAL, EURUSD's breakout family is
still slightly negative. This rules out "it's just spread" as an
explanation for Section 0's central finding.

## 24. Robustness (parameter perturbation)

A 2x2x3 grid (require_bias_agreement x {FIXED_ATR, BREAKOUT_CANDLE} SL x
{FIXED_1R, FIXED_2R, FIXED_3R} TP) on EURUSD breakout, the only
configuration space genuinely available to perturb for this strategy
(unlike TrendPullback, OR v2 exposes no continuous depth/persistence
parameters). **0 of 12 configurations showed positive expectancy** — a
consistently negative result across the entire tested grid, not a lucky
single configuration. This is a *stronger*, more useful finding than
"not robust": the negative result itself is robust to these parameter
choices.

## 25. Out-of-sample locked test

`backtest/out_of_sample_phase9b.py`: OpeningRangeStateMachine(breakout),
default parameters, frozen BacktestConfig, EURUSD, **seed 918273645** —
verified grep-unique across the entire codebase before use (distinct from
`RANDOM_SEED=20240906`, Phase 8's `424242`, and a mutation test's `7`).
Run exactly once, reported as-is: **n=124, expectancy +0.019R, bootstrap
CI [-0.238, +0.265] (includes zero), permutation p=0.886.** No
information — consistent with, not contradicting, Section 0's finding
that this configuration does not have a demonstrated edge.

## 26. What did and did not work — ranked

**Demonstrated to matter**: market-structure/BOS-CHOCH-derived directional
bias (part of the bias hierarchy, consistent with Phase 8's ablation
matrix finding), and the bias hierarchy itself as a filter (dominant
funnel stage everywhere).
**Demonstrated NOT to add information**: Fibonacci retracement depth
beyond known structure (Section 13), named candlestick patterns beyond
primitive anatomy (Section 10), BREAKOUT_CANDLE SL vs FIXED_ATR (Section
14, inconsistent), regime gating as a rescue mechanism (Section 11).
**Demonstrated to be actively harmful**: OR_OPPOSITE_BOUNDARY_TARGET TP
model for continuation-style entries (Section 15).
**Unproven, worth follow-up**: reversal-family entries generally, and
XAUUSD reversal specifically (Section 0) — directionally interesting,
statistically underpowered (n=30) and not multiple-testing-corrected.

## 27. Mutation testing

15 mutations total (7 carried over from Phase 8, 8 new Phase 9B
invariants), **all 15 detected**:

| New Phase 9B mutation | Invariant checked |
|---|---|
| `wrong_or_boundary` | OR close boundary is exclusive, not inclusive |
| `wrong_session_dst_boundary` | NY UTC anchor shifts across DST, isn't hardcoded |
| `wrong_m5_confirmation_direction` | signal direction agrees with its own OR_BROKEN_UP/DOWN state |
| `wrong_m1_entry_timing` | M1 search window excludes the M5 confirmation bar itself |
| `wrong_sl_model_side` | BREAKOUT_CANDLE stop on the protective side for both directions |
| `wrong_tp_model_direction` | LIQUIDITY_TARGET on the favorable side for both directions |
| `wrong_position_overlap_logic` | a 3rd position beyond `max_open_positions` is blocked |
| `wrong_strategy_selection_bias_hierarchy` | CONFLICTED wins over a naive single-source bias read |

Every mutation follows the established (construct baseline → apply
mutation → assert detection → nothing touches disk) pattern; each was
also verified to correctly *pass* on the unmutated code, ruling out
vacuously-true tests.

## 28. Web terminal — Decision Inspector

`web/app.py` gained 8 new `[P9B]`-prefixed tabs, loaded alongside (never
merged into) the existing Phase 7/8 tabs, reading `research/results_9b/`.
The centerpiece is the **Decision Inspector**: select an entry family,
then a specific NY session day, to see (1) the complete OR state-machine
history for that day with timestamps, and (2) every `EntryDecision`
recorded that day, rendering WHY it entered or was blocked (reasons
passed / failed conditions / blocking code), what each timeframe knew at
that instant (the full `MARKET_CONTEXT` snapshot — HTF bias, regime,
external/internal structure, protected levels, liquidity state, OR state,
ATR/spread), and the exact confirmation vs. entry timestamps. The sample
(`decision_inspector_sample.json`) carries 40 days per family (EURUSD),
capped for file size, explicitly documented as a sample for inspection,
not a performance claim (`or_v2_matrix.json` is the performance source of
truth). The other 7 tabs surface the OR v2 matrix, 13-stage funnel,
regime gating, Fibonacci/candle ablation, SL/TP v2 + cost sensitivity,
portfolio gating, and robustness/OOS/mutation results respectively.

## 29. Governance

Re-verified before this report was written:

- **HEAD/branch**: `d19382a`/`411a0a8` on
  `claude/multi-strategy-hedge-backtest-sa7cer` (both pushed).
- **Production files** (`src/`, `public/`, `astro.config.mjs`,
  `package.json`, `package-lock.json`, `tsconfig.json`): `git diff --stat`
  against the pre-Phase-7 commit is **empty** — byte-identical, zero
  drift, same result as every prior phase's check.
- **Live trading / broker code**: `grep -rni "order_send|metatrader|mt5"`
  across `research/` and `web/` matches only disclaimer/documentation
  text (`config.py`, `README.md`, `synthetic.py`, `real_data.py`
  docstrings, the web terminal's own banner) — zero executable
  broker-integration code, unchanged from every prior phase.
- **Real-data blocker**: still holds (Phase 9A's most recent probe);
  Phase 9B correctly ran entirely on labeled synthetic data as a result.
- **Mutation suite**: 15/15 detected (Section 27).

---

## Final verdict (Phase 8AK-format vocabulary)

- **Opening-range breakout family (all symbols)**: `NO_INFORMATION_
  DEMONSTRATED` on 6/8 symbols; `INFORMATION_PRESENT_BUT_NOT_ROBUST`
  (negative-direction, BH-FDR-surviving) on AUDUSD/USDCHF/NZDUSD.
- **Opening-range retest family (all symbols)**: `NO_INFORMATION_
  DEMONSTRATED` on 5/8 symbols; `INFORMATION_PRESENT` (negative-direction,
  does not survive BH-FDR) on GBPUSD/AUDUSD/XAUUSD; `INFORMATION_PRESENT_
  BUT_NOT_ROBUST` (negative, BH-FDR-surviving) on USDCHF/NZDUSD.
- **Opening-range reversal family (all symbols)**: `NO_INFORMATION_
  DEMONSTRATED` on 6/8 symbols; `INSUFFICIENT_SAMPLE` on NZDUSD;
  `INFORMATION_PRESENT` (positive-direction, does not survive BH-FDR,
  n=30) on XAUUSD only.
- **Fibonacci retracement depth (as information beyond structure)**:
  `NO_INFORMATION_DEMONSTRATED`.
- **Named candlestick patterns (beyond primitive anatomy)**:
  `NO_INFORMATION_DEMONSTRATED`.
- **OR_OPPOSITE_BOUNDARY_TARGET TP model for continuation entries**:
  actively harmful, not merely unproven — do not offer for these entry
  families.
- **Locked out-of-sample test (breakout, EURUSD, fresh seed)**:
  `TRADING_EDGE_UNPROVEN` (p=0.886, CI includes zero).

**Overall Phase 9B verdict: `TRADING_EDGE_UNPROVEN`.** No entry family,
SL model, TP model, or auxiliary signal (Fibonacci depth, candle
patterns, regime gating) produced a robust, multiple-testing-corrected,
positive-expectancy result on synthetic data. The most statistically
defensible result of the entire phase is a *negative* one (breakout/retest
on AUDUSD/USDCHF/NZDUSD). This is reported as the honest finding of a
rigorous research process, not a shortfall of the implementation — every
mechanism specified in the Phase 9B authorization was built, wired
end-to-end, causally verified, and tested; it simply did not find a
tradeable edge on this synthetic data.

**STOP after Phase 9B, per the authorization's explicit instruction. Do
not proceed to Phase 9C without further authorization.**
