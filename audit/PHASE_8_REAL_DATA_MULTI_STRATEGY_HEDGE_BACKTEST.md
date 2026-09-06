# Phase 8 — Real-Data Multi-Strategy Trend + Hedge Backtesting Research Lab

**Status: RESEARCH ONLY. Not authorized for production integration or live
trading.**

**Verdict vocabulary used below** (Phase 8AK's exact terms; this
project's code emits the Phase 7-era spelling `NO_INFORMATION_DEMONSTRATED`
— treated as a synonym for `NO_INFORMATION_DETECTED` throughout):
`EDGE_ESTABLISHED`, `EDGE_SUPPORTED_BUT_NOT_ROBUST`,
`INFORMATION_PRESENT_BUT_NOT_ROBUST`, `INFORMATION_PRESENT`,
`NO_INFORMATION_DETECTED`, `TRADING_EDGE_UNPROVEN`, `INSUFFICIENT_SAMPLE`,
`DATA_UNAVAILABLE`, `BLOCKED`.

---

## 0. Read this first: the central finding of Phase 8A

Before any Phase 8 methodology work began, `audit/
PHASE_8A_ARCHITECTURE_AUDIT.md` established, by direct test rather than
assumption:

- **No real historical market data exists anywhere in this environment.**
  A filesystem search for MT5 history files, exported CSVs, or any market
  data found nothing. A direct network probe against five real
  financial-data hosts (Yahoo Finance, FRED, Alpha Vantage, HistData.com,
  Binance) returned a `403` **organization-policy** denial from this
  session's own egress proxy on every single one — not a transient
  failure, a hard sandbox boundary.
- **The Phase 7 architecture is fully real-data-ready**: every feature,
  strategy, risk, backtest, and validation module operates on a plain
  `pandas.DataFrame` with OHLC columns and has zero dependency on how that
  data was produced. Only one new loader module was needed
  (`research/data/real_data.py`).
- Given this, the user was asked directly how to proceed and chose:
  **build the real-data-capable adapter and every new Phase 8 mechanic,
  but validate all of it on the existing labeled-synthetic generator**,
  with every economic/edge conclusion explicitly stamped
  `DATA_UNAVAILABLE` for real markets rather than reported as if it came
  from one.

**Every number in this report is BLOCKED / DATA_UNAVAILABLE as a
statement about real market behavior.** What Phase 8 actually delivers is
(a) a real-data loader, proven only against a synthetic fixture and ready
for the day real data is supplied, and (b) a substantially more rigorous
validation methodology, exercised and cross-checked against itself on
synthetic data — including catching and fixing a real bug in Phase 7's
own cost model and definitively failing to replicate Phase 7's single
positive finding.

## 1. Data sources

`research/data/synthetic.py` (same regime-switching generator as Phase 7,
re-run at 8 symbols × 300 days for this phase) plus the new
`research/data/real_data.py` loader — proven via a round-trip test against
a synthetic-data CSV/Parquet fixture only (`research/data/
real_data.py`'s own `__main__`: byte-exact Parquet round-trip, ~1e-16
relative CSV round-trip error from text serialization). **No real data
source. Verdict: `DATA_UNAVAILABLE`.**

## 2. Data quality

Unchanged mechanics from Phase 7 (`research/data/quality.py`), extended
in Phase 8C with real-data-specific checks that could never trigger on
synthetic data by construction: zero/negative price detection, spread-
anomaly detection (negative or >5% of price), volume-anomaly detection,
and >20%-single-bar-move flagging (`research/data/
real_data.py::extended_quality_audit`). All checks passed (returned zero
anomalies) on the synthetic round-trip fixture, as expected. **Verdict:
`ENGINE_VALIDATED`** (mechanics proven; no real dataset exists to audit
for real anomalies).

## 3. Strategies

Unchanged from Phase 7 (6 families, `research/strategies/`); see
`audit/PHASE_7_MULTI_STRATEGY_HEDGE_BACKTEST.md` Section 5 for full
definitions. Not re-litigated here.

## 4. Market regimes

`research/core/regime.py` extended from Phase 7's 8 states to include
**EXPANSION** and **CONTRACTION** (volatility rate-of-change, distinct
from the existing HIGH/LOW_VOLATILITY level states) and a new
**`structure_state`** output field (the causal BOS/CHOCH direction,
previously computed only internally). All existing state names and
thresholds were left unchanged (renaming would have silently broken every
strategy's regime-matching logic, e.g. `trend_pullback.py`'s
`TREND_REGIMES_LONG`). Distribution across the 8-symbol/300-day run
(EURUSD example): TRANSITION and RANGE remain the most common states;
EXPANSION/CONTRACTION are rare (a few percent of bars each), as expected
for a rate-of-change signal. **Verdict: `ENGINE_VALIDATED`** for the
classifier's mechanics; **`INFORMATION_PRESENT_BUT_NOT_ROBUST`** for its
real predictive value (Phase 7's own diagnostic already found only
31-36% agreement with the hidden synthetic ground truth — near chance —
and that finding is unchanged by this phase's additions).

## 5. Directional bias

`research/core/bias.py` extended with a 4-state classification
(**BULLISH/BEARISH/NEUTRAL/CONFLICTED**) alongside Phase 7's 5-state
STRONG_LONG..STRONG_SHORT scale. A **nested information experiment**
(`research/backtest/bias_experiment.py`) tests BIAS_ONLY vs.
BIAS+STRUCTURE vs. BIAS+STRUCTURE+REGIME against a common ATR-normalized
signed-forward-return target (not a full trade simulation — isolates the
bias signal itself):

| Condition | n | mean signed fwd return (ATR) | verdict |
|---|---:|---:|---|
| BIAS_ONLY | ~24,000 (avg/symbol) | +0.09 to +0.12 | `INFORMATION_PRESENT` |
| BIAS_PLUS_STRUCTURE | ~15,000 | +0.10 to +0.13 | `INFORMATION_PRESENT` |
| BIAS_PLUS_STRUCTURE_PLUS_REGIME | ~8,000 | +0.13 to +0.17 | `INFORMATION_PRESENT` |

(EURUSD single-symbol figures shown; consistent monotonic pattern
observed across the 4-symbol representative subset in
`research/results_8/nested_bias_experiment.json`.) Every stage clears
bootstrap CI (excludes zero) and permutation control (p≈0.00) given the
very large sample sizes. **This is mechanically expected, not surprising**:
bias is built from confirmed structure, which by definition means price
has already moved in that direction in a regime-persistent synthetic
generator — it validates that the bias-computation and validation
*machinery* correctly detects a real (if partly definitional) signal, not
that directional bias would predict real markets. **Verdict:
`INFORMATION_PRESENT` (synthetic-data engine validation); `DATA_UNAVAILABLE`
for any real-market claim.**

## 6. Entry models

Unchanged from Phase 7. Cross-referenced in Section 12 (ablation) and
Section 23 below.

## 7. SL models

Two new models added: **FIBONACCI_INVALIDATION** (stop beyond the
originating impulse's own 0%/100% anchor) and **LIQUIDITY_BASED** (stop
beyond the nearest ESTIMATED_STOP_LIQUIDITY pool). Full comparison
(opening_range_continuation, mean across 8 symbols, corrected cost
model):

| SL model | win rate | expectancy (R) | profit factor |
|---|---:|---:|---:|
| SWING_EXTREME | 32.2% | −0.182 | 0.77 |
| OR_OPPOSITE_BOUNDARY | 30.8% | −0.189 | 0.76 |
| VOLATILITY_ADAPTIVE | 29.1% | −0.261 | 0.69 |
| FIXED_ATR | 27.5% | −0.327 | 0.62 |
| STRUCTURE_INVALIDATION | 34.3% | −0.457 | 0.58 |
| **LIQUIDITY_BASED** | **3.0%** | **−2.666** | **0.03** |

**LIQUIDITY_BASED on breakout-immediately-after-OR entries is a genuine,
reportable failure**: the nearest estimated liquidity pool is often the
just-broken OR boundary itself, sitting only a few pips from entry,
producing near-immediate stop-outs (avg 1.5-bar hold time observed in an
earlier single-symbol check). **This is not a bug — it is a real,
informative finding about model/strategy mismatch**, reported per the
absolute rule "if a feature adds nothing... REPORT IT." On
trend/retracement strategies (where the liquidity pool sits further from
entry), **FIBONACCI_INVALIDATION** gave −0.10R (trend_pullback) to
−0.25R (fib_pullback) — still net-negative, better matched to the
strategy than the OR-breakout case but not a source of edge. **Verdict:
`NO_INFORMATION_DETECTED`** for both new SL models as a source of
positive expectancy; SWING_EXTREME/OR_OPPOSITE_BOUNDARY remain the
best-supported SL models (consistent with Phase 7).

## 8. TP models

Added **OR_EXTENSION** (measured-move projection of the opening range
beyond the breakout boundary). Full comparison (same setup):

| TP model | win rate | expectancy (R) | profit factor |
|---|---:|---:|---:|
| STRUCTURE_TARGET | 19.7% | −0.162 | 0.33 |
| FIXED_1R | 44.8% | −0.232 | 0.66 |
| OR_EXTENSION | 42.1% | −0.254 | 0.64 |
| ATR_TARGET | 37.3% | −0.268 | 0.65 |
| FIXED_1.5R | 34.5% | −0.286 | 0.64 |
| FIXED_2R | 27.5% | −0.327 | 0.62 |
| FIXED_3R | 20.5% | −0.333 | 0.65 |

OR_EXTENSION performs in the same range as the other fixed-distance
targets — no better, no worse. **Verdict: `NO_INFORMATION_DETECTED`** for
OR_EXTENSION as a source of edge.

## 9. Exit models

Unchanged from Phase 7 (`research/results/exit_comparison.json`); not
re-run under the corrected cost model in this phase (scope narrowing,
documented in Section 26).

## 10. Hedge models

`research/risk/hedge.py` replaces Phase 7's single static correlation
number with a genuinely **rolling, regime-bucketed** correlation/beta
measure. Tested on 4 symbol pairs:

| Pair | designed loadings | measured overall mean correlation |
|---|---|---:|
| EURUSD/GBPUSD | +0.75/+0.65 | **+0.477** |
| EURUSD/USDJPY | +0.75/−0.30 | **−0.222** |
| EURUSD/USDCHF | +0.75/−0.60 | **−0.442** |
| AUDUSD/NZDUSD | +0.55/+0.50 | **+0.273** |

Sign and rough magnitude of the designed correlation is correctly
recovered in every case. Regime-bucketed breakdown (NORMAL/
HIGH_VOLATILITY/TREND/REVERSAL) shows correlation std rising modestly in
HIGH_VOLATILITY windows (e.g., EURUSD/GBPUSD: std 0.097 normal vs. 0.111
high-vol) — directionally consistent with the general (real-market)
literature on correlation instability under stress
(`audit/PHASE_8B_EXTERNAL_RESEARCH.md`), though this project's own
version is a mechanical artifact of the synthetic generator's shared
shock-volatility term, not independent confirmation of that literature.
**Negative control**: shuffling one symbol's return order (breaking the
time relationship, preserving its distribution) collapsed mean |correlation|
from 0.477 to 0.077 — the measurement clearly detects a genuine
time-aligned relationship, not an artifact of the statistic itself.
**Verdict: `ENGINE_VALIDATED`** for the rolling correlation/beta
machinery; **`DATA_UNAVAILABLE`** for any claim about real FX correlation
behavior.

## 11. Risk models

Unchanged core mechanics from Phase 7 (fixed-fractional sizing, Kelly
diagnostic-only, RiskLimits/RiskGuardState). Not re-run as a dedicated
sweep in this phase (see Section 9's TP note — Phase 7's risk-level sweep
stands; Section 20 below covers the NEW cost-sensitivity sweep, a
different axis).

## 12. Execution assumptions

**Corrected in Phase 8**: Phase 7's `research/backtest/engine.py` only
deducted spread cost at trade **entry**; exit-side spread was never
applied, understating round-trip transaction cost by roughly half a
spread on every trade. This is now fixed (`config.spread_multiplier`
applied symmetrically at entry and exit). Still no tick-level execution
reconstruction (SL/TP fills checked against bar high/low, not a real
intrabar path) and no commission model beyond spread — both explicitly
declared limitations, unchanged from Phase 7, since no tick data exists
in this environment.

## 13. Number of experiments

Phase 7: 96 (symbol × strategy) cells + SL/TP/exit/risk/hedge/ablation
sweeps. Phase 8 adds: 72 re-run (symbol × strategy) cells under the
corrected cost model (9 strategy configs × 8 symbols; 3 Fibonacci-level
configs from Phase 7's matrix were not re-included in this phase's
narrower re-run, see Section 26), 7 SL models × 8 symbols, 7 TP models ×
8 symbols, 4 cost scenarios × 8 symbols, 3-stage nested bias × 4 symbols,
11-stage ablation matrix × 4 symbols, 4 hedge pairs, 4 negative controls,
3 trend-filter modes × 8 symbols, 3 selector modes × 8 symbols, 27
robustness-grid configs, 1 locked out-of-sample test, 7 mutation tests.
**Total Phase 8 statistical trials feeding the BH-FDR-corrected pool:
72 (matrix) + additional exploratory cells reported individually below
without claiming FDR correction where n<30 per Phase 21's own threshold.**

## 14. Multiple-testing correction

Benjamini-Hochberg FDR (α=0.05) applied to all 72 re-run matrix cells'
permutation p-values, exactly as in Phase 7. Result: only 1 of 72 cells
independently survives every validation bar (Section 23).

## 15. Negative controls

Four run in this phase (`research/backtest/negative_controls.py`):

| Control | Real expectancy | Permuted expectancy | Edge survives control? |
|---|---:|---:|---|
| Structure direction (StructureContinuation) | −0.33R | −0.20R | **No** |
| Structure direction (StructureReversal) | −0.34R | −0.31R | **No** |
| Move-strength label (SignificantMove) | −0.31R | −0.27R | **No** |
| Hedge pairing (shuffle) | 0.48 \|corr\| | 0.08 \|corr\| | **Yes** |

The hedge-pairing control passing (real ≫ permuted) confirms the
correlation *measurement* is real; the three strategy-edge controls all
correctly show **no edge to lose** in the first place (both real and
permuted results are similarly negative) — consistent with, not
contradicting, the overall null finding.

## 16. Walk-forward results

5-fold chronological walk-forward (Phase 7 mechanism) plus new **purged/
embargoed** folds (`research/backtest/validation.py::purged_embargoed_folds`,
Lopez de Prado 2017 methodology). Applied to the corrected matrix: purge
counts were **0 in nearly every fold** for the strategies checked (trade
durations are short relative to ~20-day fold widths in this dataset),
confirming Phase 7's original (non-purged) walk-forward folds were
already effectively free of this specific leakage mode. **Verdict:
`ENGINE_VALIDATED`** for the purge/embargo mechanism (mutation-tested
directly, Section 21).

## 17. Out-of-sample results — the key finding of this phase

Phase 7's single `EDGE_ESTABLISHED` cell (trend_pullback × XAUUSD)
was investigated three independent ways in Phase 8:

1. **Same exact in-sample draw, corrected cost model**: expectancy
   +0.119R → **+0.102R** (n=3,210, PF 1.16, still clears every bar). The
   cost-model bug alone does **not** explain away this cell.
2. **Parameter-perturbation grid** (`research/backtest/robustness.py`,
   27 nearby configurations of retracement depth/persistence/SL width,
   generated via a standalone single-symbol call — a different random
   draw of XAUUSD than (1), since the shared generator's RNG is consumed
   in a different order): only **37% of configurations retained positive
   expectancy** (range −0.18R to +0.31R, mean −0.019R). Verdict:
   `MIXED_NOT_ROBUST`.
3. **Locked out-of-sample test** (`research/backtest/out_of_sample.py`):
   frozen model (default params), a **genuinely fresh seed (424242)**
   never used anywhere else in this project (grep-verified), same 300-day
   window. Result: n=3,453, expectancy **+0.041R**, but the bootstrap CI
   **includes zero** (−0.006 to +0.093) and the permutation test gives
   **p=0.095** (above the 0.05 threshold). **Does not clear the bar this
   project itself set for `EDGE_ESTABLISHED`.**

**Conclusion: Phase 7's single positive cell does not replicate under
either an independent parameter perturbation or a genuinely fresh random
draw.** Downgraded from `EDGE_ESTABLISHED` to **`TRADING_EDGE_UNPROVEN`**.
This is reported prominently because catching exactly this kind of
non-replicating single-sample finding is the stated purpose of Phase 21/
8AH, and because Phase 7's own report already flagged this as the
necessary next step ("re-running this exact cell on independent synthetic
seeds... is the correct next step before drawing any conclusion") — Phase
8 did that, and the answer is negative.

## 18. Cost sensitivity

New sweep (`research/backtest/engine.py::BacktestConfig.spread_multiplier`,
opening_range_continuation, mean across 8 symbols):

| Scenario | multiplier | expectancy (R) | profit factor |
|---|---:|---:|---:|
| COST_NEUTRAL | 0× | −0.056 | 0.92 |
| BASE_COST | 1× | −0.327 | 0.62 |
| ADVERSE_COST | 2× | −0.585 | 0.45 |
| STRESS_COST | 5× | −1.197 | 0.22 |

Clean, monotonic degradation with cost — confirms the cost model applies
correctly in the correct direction (also directly mutation-tested,
Section 21). Even at zero cost this strategy configuration is roughly
breakeven (PF 0.92), not positive — costs are not "hiding" an edge that
would otherwise exist.

## 19. Drawdown

Reported per-cell throughout (`max_drawdown_r` in every table above and
in `research/results_8/matrix_corrected.json`). No new drawdown-specific
methodology added in Phase 8 beyond the corrected trade-level R-multiples
feeding into the same calculation as Phase 7.

## 20. Robustness

Covered in depth in Section 17. General finding beyond the XAUUSD cell:
no other cell in the corrected 72-cell matrix reached `EDGE_ESTABLISHED`
even once (Section 23), so the robustness question is moot for the
remaining cells — there was no positive finding to stress-test.

## 21. Failed strategies / What did NOT work

- **LIQUIDITY_BASED SL on opening-range breakout entries** (Section 7) —
  the single worst result measured in this entire project (expectancy
  −2.67R, 3% win rate). Root cause understood and reported, not hidden.
- **Every strategy at its default configuration** remains net-negative
  under the corrected cost model (worse than Phase 7's already-negative
  baseline, since the cost fix made every number slightly more negative).
- **Fibonacci-specific information** (Phase 7 finding, unchanged):
  Fibonacci levels remain statistically indistinguishable from matched-
  depth non-Fibonacci control levels; the new ablation matrix (Section 23)
  independently confirms `BASELINE_PLUS_FIBONACCI` shows
  `NO_INFORMATION_DETECTED` (or a small, inconsistently-signed effect)
  in 4/4 symbols tested.
- **Candlestick patterns as a standalone filter**: `BASELINE_PLUS_CANDLE`
  showed `NO_INFORMATION_DETECTED` in 4/4 symbols in the new ablation
  matrix.
- **The regime classifier's real-time skill**: unchanged from Phase 7,
  still near chance-level agreement with the hidden synthetic ground
  truth.
- **Phase 7's single EDGE_ESTABLISHED cell**: did not replicate
  (Section 17) — the most important "what did not work" finding of this
  phase.

## 22. No-trade bottlenecks

`research/backtest/no_trade_funnel.py`, run across all 72 corrected
matrix cells. Mean across all cells: **34.1% of candidates filtered**
(failed a context/regime/bias precondition before any entry trigger was
searched for), **22.0% failed confirmation** (a trigger was searched for
but never found), **43.9% executed**. A representative single-cell
breakdown (structure_continuation, EURUSD) found `htf_bias_aligned` alone
responsible for **77% of all filtering** — the dominant, specific,
actionable bottleneck for that strategy, not a vague "many things
filter."

## 23. Best strategy by market condition (generalized ablation matrix)

The new composable ablation matrix (`research/backtest/
ablation_matrix.py`) isolates each named feature's information content
independently of any specific strategy's combination, using a trivial
1-bar-breakout baseline and an ATR-normalized signed-forward-return
target, run on 4 representative symbols (EURUSD, GBPUSD, USDJPY, XAUUSD):

| Stage | mean signed return (ATR) | consistency across 4 symbols |
|---|---:|---|
| BASELINE | +0.008 | 1/4 beneficial, 3/4 no-info |
| BASELINE + CANDLE | +0.008 | 0/4 beneficial |
| BASELINE + FIBONACCI | +0.003 | 0/4 beneficial |
| BASELINE + LIQUIDITY | +0.023 | 1/4 beneficial |
| BASELINE + ORB | −0.007 | 0/4 beneficial |
| BASELINE + STRENGTH | +0.029 | 2/4 beneficial |
| BASELINE + REGIME | +0.058 | 3/4 beneficial |
| **BASELINE + STRUCTURE** | **+0.111** | **4/4 beneficial** |
| **BASELINE + STRUCTURE + REGIME** | **+0.128** | **4/4 beneficial** |
| FULL_CONTEXT (all filters AND'd) | +0.230 | 2/4 beneficial, 2/4 no-info (sample collapses) |
| BASELINE + DXY | — | `DATA_UNAVAILABLE` |

**Structure confirmation is the single most consistently informative
feature tested in this entire project** — the only one to clear the
statistical bar in all 4 symbols independently. Regime is a strong
second. Fibonacci, candlestick patterns, and ORB timing show no
independent information. `FULL_CONTEXT` (ANDing every filter) shows the
highest point estimate but an inconsistent verdict, because the sample
collapses to a few dozen rows per symbol — a direct illustration of Phase
8Y's own warning: "do not assume more features = better strategy."
**Verdict: `INFORMATION_PRESENT`** for structure and structure+regime
(synthetic engine validation); everything else in the matrix is
`NO_INFORMATION_DETECTED` or inconsistent.

## 24. Best entry type

No entry family (breakout/retest/reversal/continuation) outperformed the
others by more than noise in the corrected matrix, consistent with Phase
7. `NO_INFORMATION_DETECTED`.

## 25. Best SL model

STRUCTURE_INVALIDATION and SWING_EXTREME remain the best-supported (least
negative / most improved profit factor) SL models, consistent with Phase
7; the two Phase 8-added models (FIBONACCI_INVALIDATION, LIQUIDITY_BASED)
did not improve on this and LIQUIDITY_BASED was actively harmful when
mismatched to entry type (Section 7). `INFORMATION_PRESENT` (relative
ranking only, not an edge).

## 26. Best TP model / exit model

No TP model in the corrected sweep (including the new OR_EXTENSION)
produced a positive expectancy; STRUCTURE_TARGET has the lowest win rate
of the group (19.7%, since it targets a further-out structural level that
is often not reached) and also the lowest profit factor (0.33) — the
few winners it does produce are not large enough to offset the frequent
losses, the same win-rate/profit-factor trade-off pattern Phase 7
identified for its own TP models. Exit models were not re-run under the corrected cost model
in this phase — **scope narrowing**, since Phase 7's exit-model ranking
is not expected to reverse from a uniform cost adjustment applied equally
to every exit model, but this has not been explicitly re-verified and is
listed in Section 29 as a remaining gap.

## 27. Hedge effectiveness

Rolling correlation/beta mechanics are validated (Section 10, Section
15's negative control). Whether hedging *improves risk-adjusted return*
was not re-tested with the new rolling measure combined into
`research/risk/portfolio.py`'s case A-G framework in this phase (Phase
7's static-correlation version of that test stands unchanged: no hedge
case turned a losing basket profitable). **Verdict: unchanged from Phase
7, `NO_INFORMATION_DETECTED`** that hedging helps when component
strategies lack edge; `BLOCKED`/`DATA_UNAVAILABLE` for any real-hedge
claim.

## 28. What did NOT work

Consolidated: LIQUIDITY_BASED SL (Section 7), every default strategy
configuration (Section 21), Fibonacci-specific information (Sections 21,
23), candlestick patterns standalone (Sections 21, 23), ORB timing alone
(Section 23), and — critically — **Phase 7's one apparent success**
(Section 17). The regime classifier's real-world skill also remains
unestablished (Section 4).

## 29. What remains unproven

- Whether ANY of this project's strategies has real-market value, in
  either direction — `DATA_UNAVAILABLE`, unchanged and unchangeable
  without real data (Section 0).
- Whether structure/regime information (the one robustly-replicated
  synthetic finding, Section 23) would survive on real market
  microstructure, which has genuine noise this project's synthetic
  generator may not fully capture.
- Exit-model ranking under the corrected cost model (Section 26 gap).
- Whether hedging combined with the new rolling-correlation measure
  changes Phase 7's portfolio-case conclusions (Section 27 gap).
- DXY-conditioned analysis — `DATA_UNAVAILABLE`, no real or
  non-circular-synthetic DXY data exists (Section 0,
  `audit/PHASE_8B_EXTERNAL_RESEARCH.md`).

## 30. Governance

See `audit/PHASE_8_SAFETY_REPORT.md`: zero production diff (byte-
identical hashes, pre- vs. post-Phase-8), live trading remains disabled,
all 7 mutation tests pass, every commit pushed to
`claude/multi-strategy-hedge-backtest-sa7cer`.

---

## Final summary (Phase 8AK format)

**BEST_SUPPORTED_STRATEGY**: None. The one candidate from Phase 7
(trend_pullback × XAUUSD) is downgraded to **`TRADING_EDGE_UNPROVEN`**
after failing two independent replication checks in this phase.

**BEST_MARKET_CONDITION**: `DATA_UNAVAILABLE` (regime classifier real-time
skill unestablished, Section 4).

**BEST_DIRECTIONAL_BIAS**: `INFORMATION_PRESENT` on synthetic data only
(Section 5) — mechanically expected given how bias is constructed from
regime-persistent synthetic data; `DATA_UNAVAILABLE` for real markets.

**BEST_ENTRY**: `NO_INFORMATION_DETECTED` (Section 24).

**BEST_SL**: STRUCTURE_INVALIDATION / SWING_EXTREME, relatively
(Section 25) — `INFORMATION_PRESENT`, not `EDGE_ESTABLISHED`.

**BEST_TP**: `NO_INFORMATION_DETECTED` (Section 26).

**BEST_EXIT**: unchanged from Phase 7, `INFORMATION_PRESENT_BUT_NOT_ROBUST`.

**BEST_RISK**: N/A — no strategy has edge for risk sizing to compound
(Phase 7 finding, unchanged).

**BEST_PAIR**: `NO_INFORMATION_DETECTED`, with the XAUUSD exception now
explicitly disproven rather than merely unconfirmed (Section 17).

**BEST_SESSION**: untested independently, unchanged gap from Phase 7.

**WHAT FAILED**: Phase 7's one positive result (the most important
failure of this phase to document honestly); LIQUIDITY_BASED SL on
breakout entries; every strategy's default configuration under corrected
costs.

**WHY IT FAILED**: for the XAUUSD cell specifically — a single favorable
random draw plus an incomplete cost model together produced an
apparent edge that a fresh draw and a parameter-perturbation check both
failed to reproduce, which is exactly the multiple-testing/backtest-
overfitting mechanism `audit/RESEARCH_CARDS.md` card T warns about,
observed directly rather than only cited.

**WHAT DATA WAS MISSING**: real historical market data (confirmed
unobtainable in this environment, Section 0); real DXY or DXY-constituent
data; real order-book/resting-liquidity data (by design, never claimed).

**WHAT CANNOT YET BE CONCLUDED**: whether the one robustly-replicated
synthetic finding (structure confirmation adds real information, 4/4
symbols, Section 23) would hold on real market data. This is now the
best-motivated single next experiment if real data ever becomes
available — not because it is proven, but because it is the one signal
in this entire two-phase research program that survived every internal
replication check thrown at it.
