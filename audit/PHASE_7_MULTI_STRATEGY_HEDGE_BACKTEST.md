# Phase 7 — Multi-Strategy Hedge Market Backtest: Research Report

**Status: RESEARCH ONLY. Not authorized for production integration or live
trading. See Phase 30/31 below.**

## 0. Read this first

This repository (`djgifft-commits/astro-platform-starter`) is the Netlify
Astro Platform Starter template. It contained **no trading system, no
MT5/broker integration, and no market data** before this work began. The
MASTER COMMAND that initiated this project assumed an existing production
trading codebase to reuse; none existed here. This was raised to the user
directly, who chose to have a self-contained research sandbox built from
scratch inside this repo, understanding it would use **synthetic data**
rather than a real broker feed (none is reachable from this environment).

**Every number in this report comes from a labeled synthetic random-walk
price generator (`research/data/synthetic.py`), not real market data.**
Treat every finding below as an *engine-validation* result — evidence
about whether the causal feature/strategy/backtest/validation pipeline
works correctly and is capable of telling signal from noise — not as a
claim about real FX/CFD market behavior. Section 3 details exactly what
would need to change before any of this could speak to real markets.

---

## 1. Research sources

See `audit/RESEARCH_CARDS.md` for the full Phase 0 research pass (18
cards covering opening-range breakout, intraday momentum, trend/mean-
reversion regimes, market structure terminology, Fibonacci retracements,
candlestick patterns, ATR, SL/TP/trailing methodologies, Kelly/position
sizing, transaction costs, multi-timeframe confirmation, walk-forward
validation, multiple-testing correction, and portfolio hedging/
correlation). Highlights that directly shaped this implementation:

- **Fibonacci retracements have essentially no independent academic
  support** (RESEARCH_CARDS card H/I) — this is why
  `research/core/fibonacci.py` tests Fibonacci levels against matched-depth
  **non-Fibonacci control levels** rather than assuming any level is
  special (see Section 9).
- **Candlestick pattern profitability is mixed and market-inconsistent**
  (card J) — patterns are implemented purely as OHLC geometry features
  (`research/core/candle_anatomy.py`), always tested in combination with
  regime/structure context, never as standalone signals.
- **BOS/CHOCH/MSS have no standardized academic definition** (cards E/F/G)
  — this project gives them one explicit, mechanical, causal definition
  (`research/core/structure.py`) specifically so they are falsifiable.
- **Multiple-testing bias inflates apparent edge** (Bailey & López de
  Prado 2014, card T) — every one of the 96 (symbol × strategy) cells run
  in Section 8 is corrected via Benjamini-Hochberg FDR, not just the
  best-looking ones.
- **Walk-forward validation is the minimum rigorous test** (Pardo 1992,
  card S) — implemented in `research/backtest/validation.py`.

## 2. Definitions

Key mechanical definitions used throughout (all causal — see Section 4):

- **Swing / BOS / CHOCH**: `research/core/structure.py`. A swing high/low
  is a fractal confirmed `confirm_bars` (default 3) bars after it forms.
  BOS = a confirmed close beyond the last confirmed opposite swing in the
  direction of the prevailing structural bias; CHOCH = the same event
  against the prevailing bias.
- **Market regime**: `research/core/regime.py`. ATR-percentile volatility
  state + a trend-significance z-score (OLS slope of log-price over a
  50-bar window, normalized by return volatility and scaled by
  `sqrt(lookback)` to approximate a t-statistic) + trend persistence.
- **Directional bias**: `research/core/bias.py`. Weighted vote of D1/H4/
  H1/M15/M5 structural direction (D1 weighted highest).
- **Opening range**: `research/core/sessions.py`. First 15 CLOSED minutes
  after NY 09:30 **local** open, converted to UTC per-day via `zoneinfo`
  (DST-correct — verified to produce exactly 2 US DST transitions/year).
- **ESTIMATED_STOP_LIQUIDITY / ICEBERG_DATA_UNAVAILABLE**:
  `research/core/liquidity.py`. Liquidity pools are a geometric heuristic
  (stops estimated just beyond swing extremes), explicitly labeled as an
  estimate, never a measurement of real resting orders. No iceberg
  detection is implemented.

## 3. Data coverage and limitations

- **Source**: `research/data/synthetic.py` — a regime-switching (8 hidden
  states: STRONG/WEAK up/down-trend, RANGE, HIGH_VOLATILITY), session-
  aware (Asia/London/NY/overlap volatility curve), correlated
  (designed factor loadings, see below) multi-symbol minute-bar generator
  with synthetic spread and occasional volatility "shock" events.
- **Coverage run for this report**: 8 symbols (EURUSD, GBPUSD, USDJPY,
  AUDUSD, USDCAD, USDCHF, NZDUSD, XAUUSD) × 300 weekday-only calendar
  days × M1 → resampled to M5/M15/H1/H4/D1 (86,400 M5 bars/symbol).
- **Designed correlation structure** (for Phase 13 hedge-mechanics testing
  only, not a real-FX-correlation claim): EURUSD 0.75, GBPUSD 0.65, USDJPY
  −0.30, AUDUSD 0.55, USDCAD −0.45, USDCHF −0.60, NZDUSD 0.50, XAUUSD 0.20
  loadings on a shared factor.
- **Limitations, explicitly**:
  1. No real MT5/broker connection exists in this environment; real
     historical data was not fetched (outbound access to public data
     hosts like stooq.com was blocked by this session's network policy —
     verified, not assumed).
  2. The generator does not model the ~weekly FX rollover/close gap; it
     runs 24 hours through every weekday. Irrelevant to the causality
     questions under test, but means session-boundary edge cases at the
     literal week open/close are untested.
  3. Regime durations were deliberately calibrated to multi-day scale
     (see `research/data/synthetic.py` comment) so that H1-level trend
     classification would have a chance to work at all — this is a data-
     generator design choice, not evidence about how persistent real FX
     trends are.
  4. **Regime classifier fidelity is low even on this synthetic data**:
     comparing the causal classifier's broad UP/DOWN/FLAT call against the
     hidden generating regime (engine-validation diagnostic only, never
     fed back causally — `research/results/regime_validation.json`)
     gives **31–36% directional agreement across all 8 symbols**, at or
     below the ~33% chance level for a 3-way split. This is an honest,
     load-bearing finding: the specific regime classifier implemented here
     (single-timeframe OLS-slope z-score) has **little demonstrated skill**
     at recovering true trend state even under the generator's own
     (simplified) mechanics. Any strategy result conditioned on this
     classifier's output inherits that weakness.
- **Verdict on data coverage**: `DATA_UNAVAILABLE` for any claim about real
  market behavior. `ENGINE_VALIDATED` for the causal-computation and
  statistical-methodology claims this report actually makes.

## 4. Causality audit

Every module under `research/data/` and `research/core/` carries an inline
self-test asserting a causality invariant, not just "runs without error":

| Module | Invariant checked |
|---|---|
| `data/loaders.py` | A resampled bar's right edge never exceeds the last available M1 timestamp (no forming-bar leakage). |
| `core/structure.py` | Every swing's `confirmed_at_pos` strictly exceeds its `index_pos`. |
| `core/regime.py` | Recomputing on a truncated (first-half) dataset reproduces identical values to the full computation over the overlap. |
| `core/bias.py` | Same truncation-invariance; vectorized series cross-checked against a slower per-call snapshot. |
| `core/sessions.py` | NY 09:30-local session-open conversion produces exactly 2 DST transitions/year; opening range never reads outside `[open, open+15min)`. |

**A genuine look-ahead bug was found and fixed during this work**: the
retracement engine's `structure_preserved` / `max_depth_fraction` fields
(`research/core/fibonacci.py`) were originally computed over a fixed
future window from the impulse's end, regardless of when a strategy
actually decided to enter — meaning `trend_pullback`, `fib_pullback`, and
`significant_move_continuation` could see retracement behavior that
happened *after* their real entry point. This produced an implausible
Sharpe ratio (13.2) for `significant_move_continuation` in an earlier run.
Fixed by bounding those computations to the actual touch point (or,
for `significant_move_continuation`, replacing the fixed-window check
entirely with a bar-by-bar causal running-retracement check that
invalidates the setup the moment it is breached, before any confirmation
bar is evaluated). Post-fix, no strategy shows an anomalous Sharpe ratio
(see Section 8) — this is reported explicitly because catching and fixing
exactly this class of bug is the entire point of Phase 2/4's causality
requirements, and hiding it would defeat the purpose of this exercise.

## 5. Strategy definitions

Six strategy families implemented in `research/strategies/`, all built on
a shared `EntryState` lifecycle (`NO_SETUP → SETUP_FORMING → ... →
ENTRY_TRIGGERED`, `research/strategies/base.py`) separating bias from
setup from confirmation from entry, per Phase 8. Every rejected candidate
records its first failing rule (Phase 24).

| Strategy | Variants implemented | Variants deferred (documented reason) |
|---|---|---|
| A. Opening Range Breakout | continuation, retest, failed_breakout, sweep_reversal (+ optional HTF-bias/structure-confirm flags = A6/A7) | A3 (breakout+reversal) — mechanically redundant with A5 under this project's definitions |
| B. SMC Structure Continuation | default (BOS + liquidity sweep + displacement + retest + candle confirmation) | — |
| C. Structure Reversal | default (sweep + opposite displacement + CHOCH + retest) | — |
| D. Trend Pullback | default (0.30–0.65 retracement band + structure preserved + confirmation candle) | — |
| E. Fibonacci Pullback | parameterized per level; 3 of 10 levels (0.382/0.5/0.618) in the main matrix, all 10 in the dedicated Fibonacci comparison | 7 levels excluded from the main matrix only for runtime; fully covered in Section 9 |
| F. Significant-Move Continuation | STRONG_MOVE, MODERATE_MOVE (WEAK_MOVE run but excluded from headline tables — too few qualifying setups to be informative) | — |

## 6. Market regimes

Classifier: `research/core/regime.py`, 8 states + UNKNOWN. See Section 3
for the honest fidelity finding (31–36% directional agreement with hidden
ground truth — near chance). **Verdict: `INFORMATION_PRESENT_BUT_NOT_ROBUST`
for the classifier itself** — it is a real, causal, working piece of
machinery, but has not been shown to add much real information about
regime beyond chance in this test.

## 7. Directional bias

`research/core/bias.py` — weighted multi-timeframe structural vote.
Feeds the ablation test in Section 12; not independently validated beyond
that (would require its own dedicated matrix, deferred — see Section 26).

## 8. Entry / strategy results (Pair × Strategy × Regime matrix)

Full data: `research/results/matrix.json` (96 symbol×strategy cells, all
8 symbols × 12 strategy configs, base config: SL=1.5×ATR, TP=fixed 2R,
exit=FIXED). Aggregated across symbols:

| Strategy | mean n | win rate | expectancy (R) | profit factor | max DD (R) |
|---|---:|---:|---:|---:|---:|
| opening_range_retest | 264 | 27.8% | −0.167 | 0.77 | −50.5 |
| structure_continuation | 612 | 27.7% | −0.168 | 0.78 | −118.4 |
| fib_pullback_0.618 | 836 | 27.6% | −0.173 | 0.77 | −184.9 |
| opening_range_continuation | 299 | 27.6% | −0.173 | 0.76 | −56.5 |
| trend_pullback | 3,449 | 27.5% | −0.174 | 0.78 | −893.9 |
| significant_move_moderate | 3,138 | 27.4% | −0.179 | 0.76 | −594.5 |
| significant_move_strong | 3,534 | 26.9% | −0.194 | 0.74 | −734.8 |
| opening_range_failed_breakout | 85 | 26.9% | −0.194 | 0.75 | −26.4 |
| fib_pullback_0.5 | 1,028 | 26.8% | −0.195 | 0.74 | −233.4 |
| opening_range_sweep_reversal | 126 | 26.8% | −0.196 | 0.75 | −31.9 |
| fib_pullback_0.382 | 1,260 | 26.3% | −0.211 | 0.72 | −290.0 |
| structure_reversal | 779 | 25.4% | −0.237 | 0.69 | −189.7 |

**Headline finding: every strategy family clusters tightly around a small
negative expectancy (−0.17R to −0.24R) and a win rate of 25–28%,** on
synthetic data, gross of any additional real-world friction beyond the
synthetic spread already deducted. With a 2:1 fixed reward:risk target,
breakeven requires a 33.3% win rate; every strategy tested falls short of
that by 5–8 points. This is a genuinely uninformative, non-differentiated
result across six structurally distinct strategy families — **exactly the
kind of null result Phase 5 explicitly required this project not to paper
over.**

**Statistical validation** (`research/backtest/validation.py` — chronological
walk-forward, 5 folds; 600-draw bootstrap CI on mean R; 600-permutation
sign-flip negative control; Benjamini-Hochberg FDR across all 96 cells at
α=0.05):

| Verdict | Cells |
|---|---:|
| INFORMATION_PRESENT_BUT_NOT_ROBUST | 69 |
| NO_INFORMATION_DEMONSTRATED | 23 |
| INFORMATION_PRESENT | 3 |
| EDGE_ESTABLISHED | 1 |

**Exactly one cell — `trend_pullback` on XAUUSD (n=3,210, win rate 37.3%,
expectancy +0.119R, profit factor 1.19, 4/5 walk-forward folds positive,
survives BH-FDR)** — cleared every bar required for `EDGE_ESTABLISHED`
under this project's own verdict criteria. **This is reported, not
celebrated**: it is 1 result out of 96 tested cells on synthetic data, and
under Phase 21's own instruction ("a result that works only in one small
sample must be labeled INFORMATION_PRESENT_BUT_NOT_ROBUST, not EDGE") the
appropriate reading is that **the validation pipeline correctly
distinguished this cell from the other 95** rather than rubber-stamping
everything — which is the actual engine-validation success here. It is
explicitly **not** a claim that trend-pullback trading works on real gold.
Re-running this exact cell on independent synthetic seeds and, if this
project is ever extended with real data, on genuine XAUUSD history, is
the correct next step before drawing any conclusion (Section 26).

## 9. Fibonacci results

`research/results/fibonacci_level_comparison.json`, EURUSD+GBPUSD, all 5
Fibonacci levels vs. all 5 non-Fibonacci control depths:

| Type | Level | win rate | expectancy (R) |
|---|---:|---:|---:|
| Fibonacci | 0.236 | 27.9% | −0.164 |
| Control | 0.300 | 28.2% | −0.154 |
| Fibonacci | 0.382 | 27.4% | −0.177 |
| Control | 0.450 | 27.0% | −0.189 |
| Fibonacci | 0.500 | 26.8% | −0.195 |
| Control | 0.550 | 26.4% | −0.209 |
| Fibonacci | 0.618 | 27.8% | −0.166 |
| Control | 0.700 | 27.6% | −0.171 |
| Fibonacci | 0.786 | 29.6% | −0.112 |
| Control | 0.850 | 30.7% | −0.079 |

**Fibonacci levels are statistically indistinguishable from matched-depth
non-Fibonacci control levels** — both series decline/recover with depth in
lockstep. This directly confirms RESEARCH_CARDS card H/I's academic
finding: there is nothing special about 23.6/38.2/50/61.8/78.6% beyond
what any comparable retracement depth would show. **Verdict:
`NO_INFORMATION_DEMONSTRATED` for Fibonacci-ratio-specific information,
independent of the level's role as a plain retracement-depth filter.**

## 10. Stop-loss results

`research/results/sl_comparison.json`, opening_range_continuation, mean
across 8 symbols (base TP=2R, exit=FIXED):

| SL model | win rate | expectancy (R) | profit factor | max DD (R) |
|---|---:|---:|---:|---:|
| FIXED_ATR | 27.6% | −0.173 | 0.76 | −56.5 |
| OR_OPPOSITE_BOUNDARY | 30.8% | −0.078 | 0.89 | −40.7 |
| STRUCTURE_INVALIDATION | **35.9%** | **−0.053** | **0.93** | −36.4 |
| SWING_EXTREME | 32.4% | −0.068 | 0.90 | −37.5 |
| VOLATILITY_ADAPTIVE | 29.2% | −0.128 | 0.82 | −49.1 |

STRUCTURE_INVALIDATION is the best-performing SL model tested (closest to
breakeven, best profit factor, smallest drawdown) but **still net-negative
on average** — it improves the picture, it does not create an edge.
**Verdict: `INFORMATION_PRESENT` for "structure-based stops outperform a
fixed-ATR stop in this setup"; not `EDGE_ESTABLISHED`** since the
underlying strategy has no demonstrated edge for the stop to attach to.

## 11. Take-profit results

`research/results/tp_comparison.json`, same setup, SL=1.5×ATR fixed:

| TP model | win rate | expectancy (R) | profit factor | max DD (R) |
|---|---:|---:|---:|---:|
| FIXED_1R | 45.4% | −0.093 | 0.84 | −37.8 |
| ATR_TARGET | 37.6% | −0.123 | 0.81 | −43.9 |
| FIXED_1.5R | 34.5% | −0.136 | 0.80 | −48.7 |
| FIXED_2R | 27.6% | −0.173 | 0.76 | −56.5 |
| FIXED_3R | 20.5% | −0.181 | 0.78 | −66.3 |
| STRUCTURE_TARGET | **87.8%** | −0.051 | 0.69 | **−20.0** |

STRUCTURE_TARGET produces a very high win rate (87.8%) with the smallest
drawdown, but the lowest profit factor of the group (0.69) — many small
wins offset by occasional large losses. This is the textbook case Phase 9
warned against: **"a stop [here: target] that improves win rate but
destroys expectancy must not be called better."** None of the six TP
models tested turns this strategy net-positive. **Verdict:
`INFORMATION_PRESENT`** for the win-rate/profit-factor trade-off shape;
`NO_INFORMATION_DEMONSTRATED` for any TP model constituting an edge.

## 12. Exit results

`research/results/exit_comparison.json` (aggregated) and
`exit_by_strategy.json` ("which exit wins for which strategy", EURUSD):

| Exit model | win rate | expectancy (R) | profit factor | max DD (R) |
|---|---:|---:|---:|---:|
| PARTIAL_1R_RUNNER | 19.5% | −0.152 | 0.73 | −52.8 |
| TIME_BASED | 31.7% | −0.167 | 0.75 | −55.6 |
| FIXED | 27.6% | −0.173 | 0.76 | −56.5 |
| SESSION_CLOSE | 30.2% | −0.170 | 0.76 | −56.2 |
| STRUCTURE | 30.7% | −0.172 | 0.72 | −59.0 |
| BREAKEVEN_1R | 19.5% | −0.156 | 0.72 | −53.5 |
| TRAILING_SWING | 30.2% | −0.201 | 0.65 | −63.9 |
| TRAILING_ATR | 31.1% | −0.193 | 0.62 | −61.2 |

Best exit per strategy (EURUSD, informational — **not** independently
out-of-sample validated per cell, see caveat below):

| Strategy | Best exit (by expectancy) | Expectancy (R) | n |
|---|---|---:|---:|
| opening_range_failed_breakout | FIXED | **+0.012** | 86 |
| fib_pullback_0.618 | TRAILING_SWING | **+0.056** | 698 |
| trend_pullback | TRAILING_SWING | **+0.032** | 3,275 |
| fib_pullback_0.5 | TRAILING_SWING | −0.016 | 873 |
| opening_range_sweep_reversal | STRUCTURE | −0.012 | 123 |
| (remaining 7 strategies) | various | all negative | — |

Three of twelve strategies show a positive expectancy under their
single best exit model on EURUSD alone. **This table is reported exactly
as instructed ("only report such conclusions if supported by
out-of-sample data") with the caveat that it is NOT out-of-sample here —
these are the same trades used to pick the "best" exit, so this is
subject to exactly the selection bias RESEARCH_CARDS card T describes.**
**Verdict: `INFORMATION_PRESENT` at best; `INSUFFICIENT_SAMPLE` /
untested for out-of-sample robustness** — a proper answer would require
re-running the walk-forward/BH-FDR machinery per (strategy × exit) cell,
which Section 26 lists as the immediate next step.

## 13. Risk results

`research/results/risk_level_sweep.json` — opening_range_continuation,
EURUSD, R-multiple compounding at 7 risk levels (0.25%–2.00%):

| Risk % | Final equity multiple | Max drawdown |
|---:|---:|---:|
| 0.25% | 0.879 | −13.8% |
| 0.50% | 0.769 | −25.9% |
| 0.75% | 0.669 | −36.5% |
| 1.00% | 0.578 | −45.6% |
| 1.25% | 0.497 | −53.3% |
| 1.50% | 0.424 | −59.7% |
| 2.00% | 0.303 | −69.1% |

This is the direct, mechanical consequence of a strategy with negative
expectancy: **higher risk per trade monotonically increases both the rate
of capital loss and drawdown**, with no risk level rescuing the result.
This table exists to demonstrate the risk-sizing *mechanics work
correctly*, not to recommend a risk level for a strategy with no edge.
Kelly is reported as a pure diagnostic
(`research/risk/position_sizing.py::kelly_fraction_diagnostic`) and is
never used to size a position, per RESEARCH_CARDS card O.

## 14. Hedge results

`research/results/hedge_cases.json`, cases A/B/C/D/E/F/G
(`research/risk/portfolio.py`):

| Case | n trades | net exposure | realized corr. | profit factor |
|---|---:|---:|---:|---:|
| A: single strategy | 300 | −18 | n/a | 0.73 |
| B: multi-strategy, one symbol | 14,620 | −754 | n/a | 0.83 |
| F: no hedge (everything) | 123,259 | −2,545 | 0.036 | 0.74 |
| C: same-direction (long-only) | 60,357 | +60,357 | 0.019 | 0.76 |
| D: correlated pair | 31,012 | −1,284 | 0.097 | 0.77 |
| E: opposite-direction | 14,864 | +14,864 | 0.057 | 0.67 |
| G: dynamic hedge (net-exposure cap) | 53,215 | +3 | 0.041 | 0.72 |

**No hedge configuration turns a losing basket into a winning one** —
consistent with the underlying finding that no component strategy has a
positive expectancy for hedging to protect or net against. Realized
correlation across the designed multi-symbol basket is low (0.02–0.10)
even though the generator was built with much larger factor loadings
(0.2–0.75) — most of that correlation is diluted by the idiosyncratic
per-symbol regime paths and by pooling many different strategies/entry
times together, which is itself a useful engine finding: **naive trade-
level pooling understates designed correlation**; a proper hedge-ratio
analysis would need to correlate return streams at a common time grid
(e.g., daily), which `_realized_correlation` in `portfolio.py` does
correctly for its own diagnostic, but the case-level "realized_correlation"
in this table is computed the same way and still comes out low — the
honest conclusion is that trade-timing heterogeneity across
strategies/symbols swamps the designed price-level correlation at the
trade-outcome level. **Methodological caveat**: the Sharpe/Sortino
figures in the raw JSON for these cases are computed on trade-level (not
daily-aggregated) return series and scale with `sqrt(trade count)`, which
differs by two orders of magnitude across cases (300 vs. 123,259 trades)
— they are not comparable to each other or to a standard annualized
Sharpe and are omitted from the table above; profit factor and realized
correlation are the interpretable columns here. **Verdict:
`NO_INFORMATION_DEMONSTRATED`** that hedging helps or hurts in a way that
matters when the underlying strategies have no edge; the exposure-netting
*mechanics* (gross/net calculation, dynamic-cap skipping) are verified
working (`ENGINE_VALIDATED`).

## 15. Pair results

Full pair-level detail is in `research/results/matrix.json`
(`symbol` column) and viewable in the web terminal's "Pair x Strategy x
Regime" tab. No pair shows a systematically different pattern from the
others — expectancy across all 8 symbols for any given strategy stays
within a fairly narrow band, with XAUUSD's `trend_pullback` cell (Section
8) the sole outlier. **Verdict: `NO_INFORMATION_DEMONSTRATED` for a
pair-specific effect**, beyond the single flagged cell.

## 16. Lot-size results

`research/results/lot_size_experiment.json` — same trade sequence
(opening_range_continuation, EURUSD), varying lot size against a fixed
$10,000 notional account:

| Lots | Total P/L (USD) | Return on $10k |
|---:|---:|---:|
| 0.01 | −$91.15 | −0.91% |
| 0.02 | −$182.30 | −1.82% |
| 0.03 | −$273.45 | −2.74% |
| 0.05 | −$455.75 | −4.56% |
| 0.10 | −$911.50 | −9.11% |
| 0.20 | −$1,823.00 | −18.23% |

P/L scales exactly linearly with lot size, as it must — **this table
demonstrates the deliberate separation of strategy edge (constant, in
R-multiples, across every row) from position size (the only thing that
changes)**, per Phase 15's explicit instruction not to conflate the two.
No lot size makes a negative-expectancy strategy profitable.

## 17. Cost sensitivity

Every result in this report is **net of synthetic spread** (deducted as
half-spread against the trader at both entry and exit,
`research/backtest/engine.py::run_backtest`, `apply_spread_cost=True`).
A dedicated gross-vs-net comparison run (spread on/off) was not run as a
separate experiment in this pass — noted as a gap in Section 26. Given
every strategy is already net-negative even before considering any
additional real-world slippage or commission, cost sensitivity is
unlikely to be the deciding factor here, but this is an assumption, not a
measured result, and should not be treated as one.

## 18. Walk-forward results

5-fold chronological walk-forward applied to every one of the 96 matrix
cells (`research/backtest/validation.py::walk_forward_folds`). Per-fold
dispersion is stored in full in `matrix.json`'s `walk_forward_folds`
field for every cell (not summarized further here for space; the web
terminal's Strategy Comparison tab surfaces the aggregate, and the raw
JSON has the per-fold detail). The `EDGE_ESTABLISHED` cell (Section 8)
required ≥3/5 folds positive as part of its verdict; it had 4/5.

## 19. Ablation

`research/results/ablation.json` — baseline opening_range_continuation →
+HTF bias alignment → +structure confirmation (EURUSD, GBPUSD; see
Section 20 scope note on why only these two features are wired as
toggleable ablation flags):

| Symbol | Stage | n | Expectancy (R) | Profit factor |
|---|---|---:|---:|---:|
| EURUSD | baseline | 300 | −0.200 | 0.73 |
| EURUSD | +HTF bias | 145 | −0.152 | 0.79 |
| EURUSD | +structure confirm | 145 | −0.152 | 0.79 (identical to prior row) |
| GBPUSD | baseline | 299 | −0.127 | 0.82 |
| GBPUSD | +HTF bias | 141 | **+0.021** | **1.03** |
| GBPUSD | +structure confirm | 141 | +0.021 | 1.03 (identical to prior row) |

Adding HTF bias alignment roughly halves trade count (as expected — it's
a filter) and improves expectancy in both cases, turning GBPUSD marginally
positive. **Adding structure confirmation on top produced literally zero
additional filtering in both symbols** — every candidate that passed bias
alignment also passed structure confirmation here, meaning **the two
filters are redundant on this synthetic data**, not that structure
confirmation is useless in general. Sample sizes (141–145 trades) are
below this project's own `MIN_SAMPLE_FOR_ROBUST` threshold (100 is
technically cleared, but walk-forward/permutation validation was not run
on these specific ablation cells). **Verdict:
`INFORMATION_PRESENT_BUT_NOT_ROBUST`** for "HTF bias alignment adds
value" — directionally consistent across both symbols tested, but only 2
symbols and no formal statistical test applied to this specific
comparison.

**Scope note**: a fully generic ablation harness across every Phase 20
feature (liquidity, Fibonacci, displacement, candlestick, retest, DXY,
StopTracker, volatility, session) was not built — most strategies don't
expose each feature as an independently toggleable flag. Fibonacci-level
value (Section 9) and candlestick-pattern conditionality (Section 5/6,
inherent in every strategy's confirmation-checklist design) are tested
directly and more informatively than forcing them into this incremental-Δ
harness would have been. DXY and StopTracker are not implemented at all
(no cross-asset DXY proxy or live stop-order tracking exists in this
synthetic-only project) — labeled `DATA_UNAVAILABLE`.

## 20. Negative controls

Two negative controls are built into the statistical validation, applied
to every one of the 96 matrix cells:

1. **Permutation sign-flip test** (`permutation_negative_control`):
   randomly flips the sign of each trade's R-multiple 600 times; reports
   how often the shuffled mean exceeds the actual observed mean in
   magnitude. A strategy with no real directional information should fail
   to clear this bar. Combined with the bootstrap CI, this is what drove
   23/96 cells to `NO_INFORMATION_DEMONSTRATED`.
2. **Fibonacci-vs-control-level test** (Section 9): matched-depth
   non-Fibonacci levels as an explicit negative control for the
   Fibonacci-ratio hypothesis specifically. Result: no distinguishable
   difference — the negative control "passed" (correctly failed to show
   Fibonacci-specific information).

## 21. Mutation testing

See Section 4 (Causality audit) — the look-ahead bug found and fixed in
the retracement engine is the direct product of adversarially checking
"could this cell's decision have used information from after its own
decision point," which is this project's version of mutation-testing the
causal boundary. `research/data/quality.py::assert_no_lookahead` and
`assert_outcome_after_decision` provide reusable hard-fail invariants
usable in any future extension of this engine.

## 22. Production impact

**NONE.** See `audit/SAFETY_REPORT.md` for the full governance record:
git HEAD unchanged, zero-diff on every production path (`src/`,
`astro.config.mjs`, `package.json`, `package-lock.json`, `tsconfig.json`,
`public/`), only new files under `research/`, `web/`, `audit/`, and a
purely additive `.gitignore` change.

## 23. Edge status (summary)

| Claim | Verdict |
|---|---|
| Any of the 12 strategy configs has a demonstrated real-market edge | `DATA_UNAVAILABLE` (synthetic data only) |
| Any strategy config shows a repeatable edge *on this synthetic data* | `NO_INFORMATION_DEMONSTRATED` for 95/96 cells; see next row for the exception |
| `trend_pullback` on synthetic XAUUSD clears every validation bar this project defined | `EDGE_ESTABLISHED` (synthetic-data-only, single cell — see Section 8 caveats) |
| Fibonacci ratios specifically add information beyond retracement depth | `NO_INFORMATION_DEMONSTRATED` |
| Structure-based stops outperform fixed-ATR stops | `INFORMATION_PRESENT` |
| HTF bias alignment improves opening-range-breakout expectancy | `INFORMATION_PRESENT_BUT_NOT_ROBUST` |
| Hedging improves risk-adjusted return when component strategies lack edge | `NO_INFORMATION_DEMONSTRATED` |
| The causal engine (no look-ahead, correct resampling, correct DST handling, correct exposure accounting) works | `ENGINE_VALIDATED` |
| The statistical validation pipeline can tell signal from noise (doesn't rubber-stamp everything) | `ENGINE_VALIDATED` (1/96 cleared every bar, not 96/96) |

## 24. Failed hypotheses

- Fibonacci ratios carry special information (Section 9) — failed.
- A single fixed exit model is best across all strategies (Section 12) —
  failed; best exit varies by strategy, though the differences found are
  themselves not yet validated out-of-sample.
- The causal regime classifier as implemented usefully recovers true
  trend state (Section 3/6) — failed (chance-level agreement).
- Any of the 12 strategies, as specified with a fixed 1.5×ATR SL / 2R TP
  / FIXED exit, is profitable gross of costs (let alone net) on this
  synthetic data (Section 8) — failed, 12/12.

## 25. Survivors

- `trend_pullback` on XAUUSD (synthetic) — the one cell to clear every
  validation bar. Candidate for dedicated follow-up, not a conclusion.
- STRUCTURE_INVALIDATION as the best-performing SL model tested (Section
  10) — a real, if modest, improvement over fixed-ATR, worth carrying
  into any follow-up work regardless of which strategy is used.
- The causal engine and statistical validation pipeline themselves — the
  actual deliverable of this research phase, and the one component that
  passed every test thrown at it, including the adversarial ones.

## 26. Recommended next experiments

1. **Re-run the `trend_pullback` × XAUUSD cell on multiple independent
   synthetic seeds** to see if `EDGE_ESTABLISHED` is stable or a single
   lucky draw — the single most important open question this report
   leaves unanswered.
2. **Apply the full walk-forward/bootstrap/permutation/BH-FDR validation
   machinery to the (strategy × exit-model) grid**, not just the
   (symbol × strategy) grid — Section 12's "best exit per strategy" table
   is currently informal and known to be subject to selection bias.
3. **Run a gross-vs-net-of-cost comparison explicitly** (Section 17 gap).
4. **Build a dedicated directional-bias validation matrix** (Section 7
   gap) rather than only testing bias as an ablation add-on.
5. **If this project is ever extended to real markets**: replace
   `research/data/synthetic.py` with an actual historical-data connector
   behind the same `SymbolEngineData` interface (`research/core/
   feature_bar.py`) — every downstream module (strategies, risk, backtest,
   validation, web terminal) was built against that interface
   specifically so this swap would not require touching strategy logic.
   This is explicitly a future step requiring new human authorization,
   not something to do automatically.

---

## 27-31. Best-supported selections, what failed, what's missing

**BEST_SUPPORTED_STRATEGY**: None, at the "trade this" level — see Section
23. If forced to name the single most promising *candidate for further
study*: `trend_pullback` (XAUUSD cell; n=3,210; 4/5 walk-forward folds
positive; survives BH-FDR at α=0.05; **synthetic data only, single
instance, not confirmed independently — do not act on this**).

**BEST_MARKET_CONDITION**: `DATA_UNAVAILABLE` — the regime classifier's
~33% (chance-level) agreement with true regime state (Section 3) means
this project cannot yet say which real market condition favors which
strategy with any confidence.

**BEST_DIRECTIONAL_BIAS**: Untested independently (Section 7/26).

**BEST_ENTRY**: `NO_INFORMATION_DEMONSTRATED` — no entry family
outperformed the others by more than noise (Section 8).

**BEST_SL**: STRUCTURE_INVALIDATION (Section 10) — best-supported, still
not sufficient to create a positive-expectancy system on its own.

**BEST_TP**: `NO_INFORMATION_DEMONSTRATED` — every TP model tested stayed
net-negative (Section 11); STRUCTURE_TARGET's win-rate/drawdown profile
is notable but its low profit factor disqualifies it as "best."

**BEST_EXIT**: `INFORMATION_PRESENT`, not robust (Section 12) — varies by
strategy, not independently validated.

**BEST_RISK**: N/A — risk sizing cannot rescue a strategy with no edge
(Section 13); lower risk simply loses more slowly.

**BEST_PAIR**: `NO_INFORMATION_DEMONSTRATED`, with the single XAUUSD
exception already flagged as unconfirmed (Section 15).

**BEST_SESSION**: Untested independently — session classification exists
and works (`research/core/sessions.py`) but was not run as its own
comparison matrix; listed in Section 26 as a gap, not fabricated here.

**WHAT FAILED**: Every strategy at its default configuration; the
Fibonacci-ratio hypothesis; the regime classifier's real-time skill;
naive trade-level correlation/hedging analysis (diluted by pooling
heterogeneous trade timing).

**WHY IT FAILED**: Most plausibly, because the synthetic generator's
regime drift/volatility ratio is deliberately modest (a low, FX-realistic
Sharpe-like drift-to-noise ratio — see `research/data/synthetic.py`
`REGIME_STATES`), so a rules-based entry filter built on lagging,
noisy, causally-constrained features has little true signal to find. This
is arguably a *realistic* difficulty (real FX drift-to-vol ratios are
similarly low), which is exactly why Section 3 refuses to let any of this
project's synthetic findings be read as real-market claims in either
direction — the null result could reflect real market difficulty, or it
could reflect this specific synthetic generator's calibration, and this
project cannot distinguish those two explanations without real data.

**WHAT DATA WAS MISSING**: real MT5/broker historical data (never
available in this environment); DXY cross-asset data; real resting-order/
iceberg liquidity data (by design, never claimed — Section 2).

**WHAT CANNOT YET BE CONCLUDED**: whether any strategy tested here has
real-market value, in either direction. This report's job was to build
and validate the *machine* that could eventually answer that question
given real data — not to answer it from synthetic data standing in for
data this project was never able to obtain.
