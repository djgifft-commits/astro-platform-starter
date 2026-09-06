# Phase 9C — Real-Data 1UP/2DOWN Strategy Validation

**Authorization**: explicit — "Proceed with Phase 9C strategy validation
on the ingested data," following `audit/PHASE_9C_DATA_INGESTION.md`'s
`READY_FOR_PHASE_9C` verdict for XAUUSD M1. Live trading was never
enabled, no MT5/broker connection was made, no production file changed,
no entry/SL/TP/risk/hedge rule was modified, and no synthetic data is
blended into any number below.

---

## 0. Read this first — the central finding of Phase 9C

**With 74 real NY sessions on one symbol over one quarter, the sample is
too small to establish an edge, and this document does not claim one.**
Every entry family's trade count (breakout=29, retest=22, reversal=11)
falls at or below this project's own pre-existing `MIN_SAMPLE_FOR_ANY_
VERDICT=30` threshold — a bar set in Phase 8, before this real data
existed, not lowered or raised to fit what arrived. Every cell in the
core matrix is therefore labeled `INSUFFICIENT_SAMPLE` by the same
validation code Phase 8/9B used on synthetic data, regardless of how the
point estimates look.

Those point estimates ARE reported in full, because burying an
interesting-looking number would be its own kind of dishonesty: breakout
shows +0.54R expectancy (bootstrap CI [0.02, 1.06], excludes zero;
permutation p=0.085), retest +0.08R (CI includes zero; p=0.88), reversal
+0.90R (CI [0.08, 1.71], excludes zero; p=0.118, n=11). All three point
estimates are directionally positive on this real data — a genuine
contrast with Phase 9B's mostly-negative synthetic result — but none
clears this project's own significance bar (p≤0.05 AND n≥30), and none
survives being asked "would this look different with more data": a
chronological locked-OOS test on breakout shows the held-out segment
(n=8) still positive (+0.49R) but with a CI that now includes zero and
p=0.512.

**Overall verdict: `TRADING_EDGE_UNPROVEN`.** Not `EDGE_ESTABLISHED` (no
cell reaches the robustness bar), not `TRADING_EDGE_UNPROVEN`-as-euphemism-
for-negative (the direction is consistently positive here, unlike the
synthetic result) — genuinely unproven, in the literal sense: the data
so far doesn't disconfirm an edge, doesn't confirm one, and there isn't
enough of it to tell. The honest next step is more real data on this and
other symbols, not a stronger claim from the same 74 sessions.

## 1. Sample size, stated before any result (per this phase's own rule)

| Entry family | Candidates | Executed | Execution rate |
|---|---|---|---|
| Breakout | 74 | 29 | 39.2% |
| Retest | 74 | 22 | 29.7% |
| Reversal | 74 | 11 | 14.9% |

74 NY sessions, one symbol (XAUUSD), 2026-05-26 to 2026-09-04 (~101 days).
This is enough to run every mechanism end-to-end and to see real,
non-degenerate numbers — it is not enough to make a confident claim about
whether an edge exists. Per the explicit instruction ("If real data is
available but sample size is inadequate, report TRADING_EDGE_UNPROVEN
rather than forcing a conclusion"), that constraint shapes every section
below, not just the final verdict.

## 2. Data used

XAUUSD M1, 100,000 bars, user-supplied MT5 export, GMT+3 broker offset
(user-confirmed and independently corroborated against the real market's
own weekly close/reopen structure — `audit/PHASE_9C_DATA_INGESTION.md`
Section 11). Spread converted from MT5's native points to price units via
`PIP_SIZE["XAUUSD"]=0.01` (an existing project constant, consistent with
the file's own uniform 2-decimal quoting). No commission or slippage
model exists in this project's execution engine — reported as
**unavailable**, not simulated (see Section 12).

## 3. Reuse map (nothing rebuilt)

Every mechanism is the exact Phase 7/8/9B code, pointed at real data
instead of synthetic: `strategies/opening_range_v2.py` (state machine,
unchanged), `backtest/engine.py::run_backtest` (the one and only execution
engine), `core/{structure,regime,bias,fibonacci,liquidity,candle_anatomy,
sessions,protected_levels}.py`, `backtest/{regime_gating,no_trade_funnel_
v2,portfolio_gating,fibonacci_depth_experiment,candle_pattern_ablation}
.py`, `backtest/validation.py`'s bootstrap/permutation/BH-FDR/walk-forward/
purge-embargo. Genuinely new for Phase 9C: `data/ingestion.py` (prior
phase), `backtest/or_ablation_9c.py` (the A–G comparison, Section 9,
explicitly flagged as pending in Phase 9B's own report), the real-spread
unit conversion and the chronological lock/OOS split (both in
`run_phase9c_validation.py`), and 4 new mutation tests (Section 15).

## 4. Opening-range validation on this real span

Already established in `audit/PHASE_9C_DATA_INGESTION.md`: 74/74 sessions
have a complete, uncontaminated 09:30–09:45 window, zero missing 09:30
bars. This 101-day span (May–September) does not cross a US DST boundary,
so DST-transition-day behavior is untested by this specific dataset
(Phase 9B's synthetic tests, which do cross DST, and the ingestion
mutation tests, Section 15, remain the coverage for that mechanism).
Holidays/early closes: none fell in this span in a way the ingestion
gap-classifier didn't already fully account for (0 `DATA_GAP`/
`UNKNOWN_GAP` — every gap is `EXPECTED_SESSION_GAP` or `WEEKEND_GAP`).

## 5. Market structure — does it add information beyond OR itself?

Answered by the A–G ablation (Section 9): B (OR+STRUCTURE, n=38) shows a
much larger point estimate than A (OR ONLY, n=73: −0.039 ATR) — structure
conditioning moves the mean to +0.64 ATR — but neither cell reaches
statistical distinguishability at this sample size (verdict
`NO_INFORMATION_DEMONSTRATED` for both, per the same bootstrap+permutation
gate used throughout this project). Directionally suggestive, not
demonstrated.

## 6. Directional bias — does it improve results?

The bias hierarchy (`classify_bias_hierarchy`, unchanged from Phase 9B)
is the dominant rejection stage in the no-trade funnel for both breakout
(38 of 74 candidates, 51%) and retest (31 of 74, 42%) — it is doing real,
frequent work, not a rubber stamp. Whether that work *improves* outcomes
specifically can't be cleanly separated from "OR + structure" at this
sample size (bias sources include external/internal structure and regime
trend as three of five votes); Section 9's B vs. A comparison is the
closest available answer, and it is directionally positive but
unconfirmed.

## 7. Entry families — which works best?

By raw point estimate: reversal (+0.90R, n=11) > breakout (+0.54R, n=29)
> retest (+0.08R, n=22). By execution frequency (how often the bot
actually gets a trade): breakout (39%) > retest (30%) > reversal (15%).
**Neither ranking is a "winner"** — reversal's larger point estimate rides
on the smallest, least reliable sample (n=11, walk-forward not even
computed for it — below the n≥15 threshold this run used for fold
dispersion to be meaningful at all), and retest's near-zero expectancy
with mixed walk-forward folds (+1.13R, −0.16R, −0.64R across three
~7-trade folds) does not look like the same phenomenon breakout's more
consistent folds show (+1.32R, +0.32R, +0.08R — all positive, though
still thin). If forced to rank by "least likely to be pure noise":
breakout, on consistency of direction across folds, not on point estimate
size.

## 8. Candlestick patterns — do they add information?

**0 of 20 named patterns showed information beyond primitive anatomy**
(`candle_pattern_ablation_real.json`, same matched-population methodology
as Phase 9B). This replicates the synthetic finding exactly.

## 9. OR-specific ablation: A (OR only) through G (full model)

New for Phase 9C (`research/backtest/or_ablation_9c.py`), reusing Phase
9B's per-feature masks, never rebuilding them:

| Stage | n | Mean signed return (ATR) | Verdict |
|---|---|---|---|
| A: OR ONLY | 73 | −0.039 | NO_INFORMATION_DEMONSTRATED |
| B: OR + STRUCTURE | 38 | +0.641 | NO_INFORMATION_DEMONSTRATED |
| C: OR+STRUCTURE + SIGNIFICANT MOVE | 21 | +0.536 | NO_INFORMATION_DEMONSTRATED |
| D: OR+STRUCTURE + LIQUIDITY | 22 | +0.466 | NO_INFORMATION_DEMONSTRATED |
| E: OR+STRUCTURE + FIBONACCI | 24 | +0.464 | NO_INFORMATION_DEMONSTRATED |
| F: OR+STRUCTURE + CANDLE ANATOMY | 7 | +2.050 | NO_INFORMATION_DEMONSTRATED |
| G: FULL MODEL (real trades, R-multiple) | 29 | +0.540R | NO_INFORMATION_DEMONSTRATED |

**Not one stage reaches statistical distinguishability from zero at this
sample size** (bootstrap CI excludes zero AND permutation p≤0.05, jointly
— the same bar as everywhere else in this project). G is explicitly
**not** assumed superior, per the instruction — and on the numbers here it
isn't obviously superior to B, C, D, or E either; F's much larger point
estimate rides on n=7, the smallest cell in the table, and is the least
trustworthy number in this section, not the best one. **Minimum feature
set that survives OOS testing: none of them survive at this sample size** —
this is the honest answer Phase 9C's own question ("determine the minimum
feature set") gets from 74 sessions, not a discovered minimal-but-
sufficient combination.

## 10. Fibonacci — does 23.6% matter after structure is known?

**No.** Structure-only baseline (n=8,909 retracement touches): mean
displacement −0.057 ATR, CI includes zero. **Zero of the 5 populated depth
buckets were distinguishable from that baseline** (`n_buckets_
distinguishable_from_baseline: 0`). The buckets show a visually monotonic
decline from 23.6–38.2% (+0.086) to >78.6% (−0.355), which is
*interesting to look at* and *not statistically confirmed* — exactly the
distinction this project's methodology exists to enforce. This replicates
Phase 9B's synthetic finding.

## 11. Significant-move strength — does it add information?

Reused from `strategies/significant_move.py` (Phase 7) via the A–G
ablation's `_strength_mask` (Section 9, stage C): point estimate +0.536
ATR on n=21, not statistically distinguishable. No dedicated
significant-move-only cell beyond what Section 9 already reports; not
rebuilt separately.

## 12. Regime — which one works? Does the strategy need strong trends?

Every regime bucket for the breakout family has n≤8 (`regime_gating_
real.json`) — genuinely too sparse to say anything about "which regime
works." One finding IS clean, though: **`STRONG_TREND_REQUIRED` gating
blocks all 29 breakout candidates (n=0 survives)** — no bar in this
101-day window was ever classified `STRONG_UPTREND`/`STRONG_DOWNTREND` at
a breakout's entry time. Whatever this strategy is capturing on this real
data, **it is not capturing it via strong trending conditions** — directly
answering primary question 9 ("does the strategy actually require strong
trends?") with a clean no, at least for this quarter. Ranging markets were
not discarded from any table here — every regime bucket's raw stats are
in the dumped JSON, n=0-8 each.

## 13. SL/TP/exit — which survives costs? (descriptive only — no config was selected from this data)

`sl_tp_descriptive_real.json`, breakout family, n=29 for every row:

| Model | Type | Expectancy (R) | Profit factor |
|---|---|---|---|
| FIXED_ATR (locked default) | SL | +0.540 | 2.11 |
| BREAKOUT_CANDLE | SL | +0.844 | 3.20 |
| FIXED_0.5R | TP | +0.282 | 3.02 |
| FIXED_1R | TP | +0.437 | 2.57 |
| FIXED_2R (locked default) | TP | +0.540 | 2.11 |
| FIXED_3R | TP | +0.919 | 2.76 |
| FIXED_4R | TP | +1.057 | 2.78 |
| OR_OPPOSITE_BOUNDARY_TARGET | TP | **−1.925** | **0.00** |
| LIQUIDITY_TARGET | TP | +0.055 | 2.59 |

**`OR_OPPOSITE_BOUNDARY_TARGET` is catastrophic on real data too** (0.00
profit factor), replicating Phase 9B's synthetic finding exactly and
confirming it as a genuine conceptual mismatch (targets the adverse
direction for a continuation entry), not a synthetic-data artifact.
BREAKOUT_CANDLE SL and larger fixed-R targets both show higher point
estimates than the locked default here — **this is reported, not acted
on**: per "do not select the winner using the complete dataset," the
`LOCKED_CONFIG` (FIXED_ATR/FIXED_2R, frozen since Phase 8) was never
changed based on this table, and the numbers above are exploratory
context, not a re-tuned strategy. At n=29, "FIXED_4R looks better than
FIXED_2R" is exactly the kind of single-dataset pattern that would not
survive being tested on a second symbol or a second quarter — which
Phase 9C does not yet have.

## 14. Cost, risk, and portfolio behavior

**Cost sensitivity** (`cost_sensitivity_real.json`): COST_NEUTRAL +0.552R
→ BASE +0.540R → ADVERSE +0.529R → STRESS +0.494R. Real spread on this
symbol/broker (≈$0.23–0.45 per round trip on gold trading in the
thousands) is small relative to this strategy's R-multiples — cost barely
moves the result, a genuinely different picture from Phase 9B's synthetic
cost-sensitivity finding (where cost mattered more), and worth noting as
a real-vs-synthetic divergence rather than smoothing over it.

**Commission and slippage: unavailable, not modeled.** This project's
execution engine (`backtest/engine.py`) has only ever modeled spread —
building a commission/slippage model now, under real-data pressure, would
be exactly the kind of invented capability the MASTER COMMAND prohibits
("If a capability does not exist, report it as unavailable instead of
inventing it"). Reported here as a real, named gap for a future phase, not
quietly worked around.

**Risk-level sweep** (0.25/0.50/0.75/1.00%, `risk_level_sweep_real.json`):
final equity rises monotonically with risk level ($10,397 → $10,805 →
$11,223 → $11,653 on a $10,000 start). **This is not evidence that higher
risk is better or safer** — every one of the 29 candidates executed at
every risk level tested (`execution_rate: 1.0` throughout); nothing was
ever blocked by a drawdown or daily-loss circuit breaker, so the sweep is
mechanically multiplying the outcome of one historical path, not
demonstrating risk-adjusted robustness. A real risk-level comparison needs
enough trades and enough adverse stretches for the circuit breakers to
actually engage sometimes; this dataset doesn't have that yet.

**Position overlap** (`cross_family_overlap_real.json`): running all three
entry families on XAUUSD simultaneously, zero of 62 combined candidates
were blocked by a same-symbol position-overlap or risk limit in this
window — the three families' setups did not happen to coincide in time
often enough, at the (deliberately loose, max_open_positions=3) limits
tested, to produce a conflict. This is reported as an observation about
this specific 101-day window, not a general claim that overlap can't
happen.

**Hedge effectiveness: not assessable.** Requires a correlation pair
(≥2 symbols); only XAUUSD was ingested. Reported as not assessable, not
skipped silently, not answered with the synthetic Phase 8 hedge-engine
finding presented as if it were real-data evidence.

## 15. Robustness and mutation testing

**Chronological locked OOS split** (breakout, 70/30, 1-day embargo,
`LOCKED_CONFIG` frozen since Phase 8/9B and never adjusted based on either
half): exploration segment n=20, +0.638R (CI [0.04, 1.24], excludes zero,
p=0.1); locked test segment n=8, +0.489R (CI [−0.64, 1.61], **includes
zero**, p=0.512). Both point the same direction; only the exploration
segment reaches even marginal significance, and n=8 in the locked segment
is too small to confirm anything on its own. A 3-way TRAIN/VALIDATION/
TEST split was deliberately not used — with only 29 total trades, a
3-way split would leave single-digit folds throughout, adding noise
without adding a genuine held-out validation stage; this deviation from
"prefer TRAIN/VALIDATION/TEST" is stated here, not silent.

**Symbol stability and year stability: not assessable.** One symbol, one
quarter. Reported as not assessable rather than inferred from the
synthetic 8-symbol result.

**Mutation testing: 19/19 strategy-layer invariants detected** on this
real-data run (`mutation_tests_real.json`) — the same 15 from Phase 8/9B
plus 4 new ones added for Phase 9C: `bos_choch_direction` (a structure
event's BOS/CHOCH label correctly reflects continuation vs. reversal of
the prevailing bias — not covered before), `fibonacci_anchor_causality`
(a retracement touch is never found at or before its own impulse's end
bar), `fib_236_classification` (exact boundary correctness at
23.6/38.2/61.8/78.6%), and `portfolio_gross_exposure` (the
`MAX_GROSS_EXPOSURE` limit is enforced independently of the open-position-
count path already covered). Combined with the 8 ingestion mutations from
the previous phase, this project now carries 27 mutation tests, all
passing.

## 16. No-trade funnel (13-stage, real data)

| Family | Top rejection stage | Second |
|---|---|---|
| Breakout | `bias_valid` (38/74, 51%) | `m1_trigger` (7/74, 9%) |
| Retest | `bias_valid` (31/74, 42%) | `range_breakout` (14/74, 19%) |
| Reversal | `liquidity_event` (40/74, 54%) | `bias_valid` (13/74, 18%) |

This exactly replicates Phase 9B's synthetic finding on which stage
dominates for which family. Nothing is silently discarded — every
rejected candidate's stage is in the dumped JSON, including days with no
liquidity sweep at all (reversal's dominant bottleneck).

## 17. Answering the 17 primary questions directly

1. **Does 1UP/2DOWN work on real data?** Unproven. Directionally positive
   on all three families, not statistically confirmed at n=11-29.
2. **Which entry works best?** Not determinable with confidence; breakout
   is the most internally consistent across walk-forward folds.
3. **Does market structure improve OR?** Directionally yes (A vs. B in
   Section 9), not demonstrated.
4. **Does 23.6% retracement matter?** No evidence found (Section 10).
5. **Does Fibonacci add information after structure?** No (Section 10).
6. **Do candle patterns add information?** No, 0/20 (Section 8).
7. **Does significant-move strength add information?** Not demonstrated
   (Section 11).
8. **Which regime works?** Not assessable — every bucket n≤8 (Section 12).
9. **Does the strategy require strong trends?** No — 0 breakout
   candidates occurred in a strong-trend regime this quarter (Section 12).
10. **Does directional bias improve results?** Suggestively (it's the
    dominant funnel gate), not isolable from structure at this n.
11. **Which SL survives costs?** Not selected from this data (Section 13)
    — the locked FIXED_ATR default was never changed.
12. **Which TP survives costs?** Same — not selected. OR_OPPOSITE_
    BOUNDARY_TARGET is confirmed harmful, real data included.
13. **Which exit survives costs?** Only FIXED (time/SL/TP) was tested;
    trailing-structure/time-based exits exist in the codebase but were not
    re-run here (out of scope for this pass, not unavailable).
14. **Which risk level survives drawdown?** Not assessable — no risk
    level tested ever triggered a drawdown/loss circuit breaker (Section
    14).
15. **Does the hedge engine improve portfolio outcomes?** Not assessable
    — needs ≥2 symbols (Section 14).
16. **How many candidates are rejected before execution?** 45 of 74
    (61%) breakout, 52/74 (70%) retest, 63/74 (85%) reversal (Section 16).
17. **When should the bot do nothing?** When bias is CONFLICTED/disagrees
    (the dominant gate for breakout/retest) or no liquidity sweep occurs
    (the dominant gate for reversal) — the funnel answers this directly
    and specifically per family (Section 16).

## 18. Governance

- **HEAD/branch**: this commit, `claude/multi-strategy-hedge-backtest-sa7cer`.
- **Production files**: byte-identical to the pre-Phase-7 baseline,
  re-verified after this phase's changes (`git diff --stat` against
  `src/`, `public/`, `astro.config.mjs`, `package.json`,
  `package-lock.json`, `tsconfig.json` is empty).
- **Live trading**: remains disabled. No MT5 connection of any kind was
  made in this phase or any prior one — the data arrived once, as a
  user-exported file attachment. No `order_send`/broker/order-routing code
  exists anywhere in this repository.
- **Strategy/entry/SL/TP/risk/hedge files**: none modified this phase
  (`git diff --stat` against `research/strategies`, `research/risk`,
  `research/core` is empty; the only `research/backtest/` change is the
  new mutation tests, which read existing modules rather than altering
  them).
- **Regression**: 13 module self-tests re-run clean after every change
  this phase (real_data, ingestion ×2, or_ablation_9c, sessions,
  opening_range_v2, regime_gating, no_trade_funnel_v2,
  fibonacci_depth_experiment, candle_pattern_ablation, portfolio_gating,
  out_of_sample_phase9b, mutation_testing).
- **Real data file**: `data/historical/XAUUSD_M1.csv` remains gitignored,
  never committed, per the existing licensed-data policy.

## 19. What would change this verdict

More real data — more history for XAUUSD (crossing regime and, ideally,
a full year including a DST transition), and/or additional symbols, so
that: (a) trade counts clear the n≥30 significance bar and n≥100 robust
bar this project already uses, (b) a genuine 3-way TRAIN/VALIDATION/TEST
split becomes meaningful, (c) symbol-stability and year-stability, both
currently not-assessable, become answerable, and (d) the A–G ablation
(Section 9) gets enough samples per cell to actually distinguish
`NO_INFORMATION_DEMONSTRATED` from `INFORMATION_PRESENT` rather than
defaulting to the former on every cell by insufficient power. Nothing in
this report recommends changing the strategy, the SL/TP defaults, or the
risk model based on 74 sessions — the recommended action is more data, not
more tuning.

---

## Final verdict

Per the Phase 9C verdict vocabulary (`EDGE_ESTABLISHED` /
`INFORMATION_SUPPORTED` / `INFORMATION_PRESENT_BUT_NOT_ROBUST` /
`TRADING_EDGE_UNPROVEN` / `DATA_UNAVAILABLE` / `BLOCKED` — `INFORMATION_
SUPPORTED` here maps to what this project's existing validation code
internally labels `INFORMATION_PRESENT`; noted once to avoid confusion
with the dumped JSON's own field names):

- **1UP/2DOWN overall, all three entry families**: **`TRADING_EDGE_
  UNPROVEN`**. Every core-matrix cell is `INSUFFICIENT_SAMPLE` (n<30);
  the locked OOS test's held-out segment CI includes zero.
- **Market structure / significant move / liquidity / Fibonacci / candle
  anatomy as OR-conditioning features (A–G ablation)**: **`TRADING_EDGE_
  UNPROVEN`** for every stage — none reaches distinguishability from
  zero at this sample size.
- **Fibonacci 23.6% depth specifically**: **`TRADING_EDGE_UNPROVEN`**
  leaning toward no-information (0/5 buckets distinguishable), consistent
  with the synthetic Phase 9B finding.
- **Named candlestick patterns**: **`TRADING_EDGE_UNPROVEN`** leaning
  toward no-information (0/20), consistent with Phase 9B.
- **OR_OPPOSITE_BOUNDARY_TARGET TP model**: not unproven — **confirmed
  harmful** for continuation-style entries, on both synthetic and now real
  data (0.00 profit factor).
- **Hedge effectiveness, symbol stability, year stability**: **`DATA_
  UNAVAILABLE`** for this specific sub-question (not the whole phase) —
  each genuinely requires data this ingestion has not yet received (a
  second symbol, or a longer span), not a capability gap in the code.

**No `EDGE_ESTABLISHED` claim is made anywhere in this report.**
Profitability alone (the positive point estimates in Sections 0, 7, 13)
was never used to declare one, per the explicit instruction — every
positive number here is paired with the sample-size and significance
context that keeps it from being overclaimed.

**Do not proceed to Phase 9D automatically. This report is the complete
Phase 9C deliverable; further work (a second symbol, more history, a
dedicated pre-registered follow-up test on the breakout family
specifically) requires separate authorization.**

**STOP.**
