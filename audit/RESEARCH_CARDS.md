# Phase 0 — Research Cards

Structured external research performed before any implementation, per MASTER
COMMAND PHASE 7. ICT/SMC educational material is treated as **terminology /
framework** material, not empirical proof of profitability — every such
concept below is marked accordingly and routed to `test_required`.

Format: concept, source, source_type, claim, evidence_strength,
measurable_definition, possible_bias, test_required.

---

### A/B. Opening Range Breakout (ORB) / Retest

- **concept**: Trading a breakout of the high/low established in the first
  N minutes after a session or exchange open.
- **source**: Zarattini & Aziz, "Assessing the Profitability of Intraday
  Opening Range Breakout Strategies" (SSRN/ScienceDirect); QuantConnect
  research note "Opening Range Breakout for Stocks in Play."
- **source_type**: peer-reviewed / practitioner-quant working paper.
- **claim**: ORB can be profitable (reported Sharpe ~2.4 in one 2016–2023
  US equity sample) but effectiveness is concentrated in liquid,
  high-relative-volume names with a news catalyst; a large sample of
  individual futures/FX day traders using similar rules lost money net of
  costs (2007–2008 sample).
- **evidence_strength**: MODERATE, sample- and market-specific; not a
  universal law. Different asset class (equities-in-play) than this
  project's synthetic FX/CFD symbols.
- **measurable_definition**: `OR_high`/`OR_low` from the first closed 15m
  candle after session open; breakout = first M5 **close** beyond the
  range (wick-only variant tested separately, see Strategy A2/A4).
- **possible_bias**: selection bias (only "stocks in play" tested);
  survivorship in the source universe; regime dependence (2016–2023 was
  trending post-COVID equities).
- **test_required**: causal walk-forward test on this project's own
  (synthetic, then real-data-if-available) instruments; report by regime
  and session, not pooled.

### C. Intraday Momentum / Persistence

- **concept**: Early-session return predicts late-session return
  ("intraday momentum").
- **source**: Gao, Han, Li & Zhou (2018), "Market Intraday Momentum,"
  *Journal of Financial Economics* (SSRN 2440866; SPY 1993–2013, minute
  data).
- **source_type**: peer-reviewed, top finance journal.
- **claim**: First half-hour return predicts last half-hour return,
  statistically and economically significant; stronger on high-volume,
  high-volatility, and macro news days.
- **evidence_strength**: STRONG for US equity index ETFs over the sampled
  period; **not yet demonstrated** for FX/CFD pairs or this project's
  data.
- **measurable_definition**: corr(ret[0:30m], ret[last 30m]) conditioned on
  volume/volatility terciles.
- **possible_bias**: single-asset-class result (S&P 500 ETF and other
  large-cap US ETFs); mechanism proposed (return-chasing by informed
  traders + late-day index-fund rebalancing) may not transfer to 24-hour
  FX/CFD markets with no single "close."
- **test_required**: analogous session-return correlation test on this
  project's session-segmented synthetic data; treat any FX transfer of
  this finding as an untested hypothesis.

### D. Trend-Following vs. Mean-Reversion Regimes

- **concept**: Markets alternate between persistent (trending) and
  reverting (ranging) regimes; strategy fit is regime-dependent.
- **source**: well-established quantitative-finance stylized fact
  (documented across CTA/managed-futures literature); no single canonical
  paper cited here — treated as a framework assumption to be tested, not
  an established claim for this data.
- **source_type**: industry/quant-practitioner consensus.
- **claim**: trend-following works better in persistent regimes,
  mean-reversion in range regimes; regime switches are themselves hard to
  detect causally in real time.
- **evidence_strength**: WEAK-TO-MODERATE as a general law; regime
  identification lag is a known confound.
- **measurable_definition**: see `research/core/regime.py` — ATR-normalized
  slope, swing persistence, BOS/CHOCH frequency.
- **possible_bias**: hindsight regime labeling (a regime is often only
  "obvious" after it ends) — this project's classifier is restricted to
  causal (past-only) inputs to avoid this.
- **test_required**: causal classifier accuracy vs. a hidden synthetic
  ground-truth label (engine validation only), then strategy performance
  conditioned on classifier output (never on the hidden label).

### E/F/G. Market Structure (Swing HH/HL/LH/LL, BOS, CHOCH, MSS)

- **concept**: Price structure defined by sequences of swing highs/lows;
  "break of structure" (BOS) = continuation signal, "change of character"
  (CHOCH) / "market structure shift" (MSS) = reversal signal.
- **source**: ICT (Inner Circle Trader) / Smart Money Concepts educational
  material; no peer-reviewed academic paper defines these terms with a
  standardized, falsifiable definition.
- **source_type**: retail-educational, **not empirical**.
- **claim**: structure breaks mark genuine continuation/reversal points.
- **evidence_strength**: NONE (academic) — terminology/framework only.
- **measurable_definition**: this project defines swings via a causal
  fractal rule (`research/core/structure.py`) and BOS/CHOCH/MSS as a
  confirmed close beyond the prior swing extreme — an explicit,
  falsifiable operationalization, not the ambiguous discretionary version
  common in retail material.
- **possible_bias**: many free parameters (swing lookback, confirmation
  bar count) allow this to be curve-fit; results must be reported across a
  parameter grid, not a single hand-picked setting.
- **test_required**: full statistical validation (Phase 21) required
  before any BOS/CHOCH-based signal is called informative.

### H/I. Fibonacci Retracement (23.6/38.2/50/61.8/78.6%)

- **concept**: retracements of a prior move tend to react near Fibonacci
  ratios.
- **source**: peer-reviewed: "Automatic identification and evaluation of
  Fibonacci retracements" (ScienceDirect, three equity markets);
  practitioner review (Capital.com, LuxAlgo).
- **source_type**: mixed — one peer-reviewed empirical study, remainder
  practitioner explainer content.
- **claim**: "Academic research and market studies show no statistical
  evidence that prices naturally follow Fibonacci ratios... no landmark
  academic study unambiguously confirming Fibonacci levels generate
  statistically significant trading signals." One study found a positive
  relationship between Fibonacci-zone width and bounce probability, but
  explicitly notes this does not imply a profitable strategy.
  Self-reinforcement (many traders watching the same levels) is offered
  as the more plausible mechanism than any price "law."
- **evidence_strength**: WEAK. This is the single clearest instance in
  this research pass of a widely-believed retail concept with essentially
  no strong empirical support.
- **measurable_definition**: `research/core/fibonacci.py` computes
  retracement depth/speed/duration/rejection per level, per impulse.
  Rule 7 in this project ("never assume 23.6% = continuation") reflects
  this research finding directly.
- **possible_bias**: confirmation bias (traders remember bounces at
  Fibonacci levels, forget the majority of level-crosses that don't
  bounce); multiple-level testing without correction inflates apparent hit
  rate.
- **test_required**: mandatory — measure hit rate per level against a
  **shuffled/random-level negative control** (see Phase 21 permutation
  test) before attributing any bounce rate to the specific ratio.

### J. Candlestick Patterns

- **concept**: specific OHLC geometries (engulfing, hammer, doji, etc.)
  carry predictive information.
- **source**: Tharavanij, Siraprapasiri & Rajchamaha (2017), "Profitability
  of Candlestick Charting Patterns in the Stock Exchange of Thailand,"
  *SAGE Open*; Marshall/Young/Rose-type US/Japan null-result literature;
  Deng et al. (2022) SSE50 study.
- **source_type**: peer-reviewed, multiple markets, **conflicting
  results**.
- **claim**: "No agreement on whether candlestick patterns are
  profitable" — US and Japanese equity studies mostly find no
  statistically significant mean return from reversal patterns; several
  Asian-market studies (Taiwan, Thailand, China SSE50) find some patterns
  (e.g., Harami, Long White, Bullish Gap) with significant positive
  abnormal returns over specific holding periods, but "different patterns
  require different holding periods to be profitable" and high variance
  accompanies any significant patterns.
- **evidence_strength**: MODERATE but market/period-specific and
  **inconsistent across markets** — the single strongest justification in
  this research set for Phase 6's explicit rule that a pattern is a
  *feature*, tested conditionally (pattern+trend, pattern+structure,
  etc.), never an unconditional signal.
- **measurable_definition**: `research/core/candle_anatomy.py` — pure OHLC
  geometry, deterministic thresholds, no manual eyeballing.
- **possible_bias**: pattern definitions vary across sources (threshold
  ambiguity for "small body," "long wick"); look-ahead risk if the
  pattern's confirmation bar is misaligned with decision time.
- **test_required**: pattern alone vs. pattern+context ablation (Phase 20)
  required before any pattern is used in a strategy's confirmation stack.

### K. ATR-Based Volatility Normalization

- **concept**: normalize move size / stop distance by Average True Range
  to compare across volatility regimes.
- **source**: J. Welles Wilder, *New Concepts in Technical Trading
  Systems* (1978) — original ATR definition; widely adopted in
  practitioner and academic volatility-normalization literature since.
- **source_type**: foundational technical-analysis text, since absorbed
  into standard quantitative practice (e.g., volatility-adjusted position
  sizing is standard in CTA risk management).
- **claim**: ATR is a reasonable, well-defined volatility proxy; useful for
  cross-regime and cross-instrument normalization of stops/targets.
- **evidence_strength**: STRONG as a *measurement tool*; this is not a
  profitability claim, just a normalization convention.
- **measurable_definition**: Wilder's smoothed true range,
  `research/core/atr.py`.
- **possible_bias**: none material as a pure measurement; choice of
  lookback (14 vs. other) is a free parameter to be varied, not
  hand-picked once.
- **test_required**: sensitivity check across ATR lookback (e.g., 10/14/21)
  for any SL/TP model that depends on it.

### L/M/N. Stop-Loss / Take-Profit / Trailing-Stop Methodologies

- **concept**: fixed-distance, structure-based, volatility-adaptive, and
  trailing exit rules.
- **source**: standard risk-management practice across CTA/prop-trading
  literature; no single claim tested here beyond "different exit rules
  produce different risk/return trade-offs," which is close to tautological
  and is exactly why Phase 9–11 require head-to-head measurement rather
  than assumption.
- **source_type**: practitioner consensus / operational definitions.
- **claim**: none assumed superior a priori.
- **evidence_strength**: N/A — this is a measurement exercise, not a
  literature claim.
- **measurable_definition**: `research/risk/sl_models.py`,
  `tp_models.py`, `exit_models.py`.
- **possible_bias**: a stop/exit that improves win rate by cutting winners
  short can *reduce* expectancy — explicitly guarded against in Phase 9's
  rule ("a stop that improves win rate but destroys expectancy must not be
  called better").
- **test_required**: full head-to-head comparison, expectancy-primary.

### O. Risk of Ruin / Position Sizing (Kelly, Fixed-Fractional)

- **concept**: position size as a fraction of the edge; Kelly criterion
  `f* = (bp - q) / b` maximizes long-run geometric growth but at high
  variance; fixed-fractional (e.g., 1% per trade) is the common practical
  alternative.
- **source**: Kelly (1956); practitioner synthesis (Astute Investor's
  Calculus, Journal Plus) on half-/quarter-Kelly in practice.
- **source_type**: foundational math result (Kelly) + practitioner
  application notes.
- **claim**: full Kelly sizing produces 50–80%+ drawdowns even with a true
  edge; half-/quarter-Kelly trades growth rate for materially lower
  drawdown; Kelly inputs (win rate, payoff ratio) need "200–500 trades"
  for reliable estimation and must be re-estimated as edge changes.
- **evidence_strength**: STRONG (Kelly math is a proven optimality result
  under its assumptions); MODERATE for the specific "200–500 trades"
  heuristic (practitioner rule of thumb, not a formal derivation).
- **measurable_definition**: `research/risk/position_sizing.py` implements
  fixed-fractional sizing from equity/risk%/stop-distance/contract specs;
  Kelly is reported diagnostically, never used to auto-size, per the
  project rule that "confidence must never magically increase risk unless
  statistically validated."
- **possible_bias**: Kelly assumes stationary, correctly-estimated edge —
  false in practice; mis-estimated edge is the single most common cause of
  real-money "risk of ruin."
- **test_required**: fixed risk-percent sweep (0.25%–2.00%) plus
  volatility-adjusted variant, evaluated on drawdown and consecutive-loss
  distributions, not just terminal equity.

### P/Q. Transaction-Cost / Spread-Slippage Sensitivity

- **concept**: spread and slippage are a direct, certain cost paid on
  every trade; short-horizon strategies are disproportionately exposed.
- **source**: general market-microstructure literature (bid-ask spread
  decomposition: adverse-selection component ~43%, inventory component
  ~10%, per cited synthesis); retail-trading-loss statistics (~70% of
  retail day traders reported to lose money, transaction costs cited as a
  primary factor).
- **source_type**: practitioner/industry synthesis of microstructure
  research; retail-loss statistic is a commonly cited industry figure, not
  independently re-verified here — flagged as **evidence_strength: WEAK
  (unverified statistic)**.
- **claim**: a 2-pip spread can consume 20–40% of a 5–10 pip scalping
  target; cost sensitivity must be tested explicitly, not assumed
  negligible.
- **evidence_strength**: STRONG for the *mechanism* (spread is a real,
  measurable cost), WEAK for any specific quoted percentage without
  re-deriving it from this project's own trade size/target distribution.
- **measurable_definition**: `research/config.py` baseline spread per
  symbol; backtest engine deducts spread (and can add slippage) on every
  fill.
- **possible_bias**: real spreads widen during news/low-liquidity in ways
  a constant or simple time-of-day multiplier will underestimate.
- **test_required**: report every strategy's results gross AND net of
  costs; flag strategies whose edge is cost-fragile (Phase 15/22).

### R. Multi-Timeframe Confirmation

- **concept**: aligning entries with higher-timeframe trend/structure
  reduces false signals.
- **source**: standard technical-analysis practice; no single strong
  academic citation located in this pass specific to MTF alignment as a
  standalone edge.
- **source_type**: practitioner consensus.
- **claim**: unconfirmed as an independent edge source; plausible as a
  *filter* that reduces trade count and possibly variance, not
  necessarily a source of positive expectancy on its own.
- **evidence_strength**: WEAK/untested by strong independent literature.
- **measurable_definition**: `research/core/bias.py` — D1/H4/H1 alignment
  score feeding the M15/M5/M1 execution layer.
- **possible_bias**: adding timeframes multiplies free parameters
  (lookback per timeframe) — high overfitting risk if tuned on the same
  sample used to validate.
- **test_required**: Phase 20 ablation — add MTF alignment as one
  incremental feature and measure ΔExpectancy/ΔSharpe out-of-sample.

### S. Walk-Forward Validation

- **concept**: repeatedly re-validate a strategy on data outside its
  fitting window, sliding forward through time.
- **source**: Pardo, *Design, Testing and Optimization of Trading Systems*
  (1992) — originated walk-forward analysis.
- **source_type**: foundational, widely adopted quant-practitioner
  methodology.
- **claim**: "if your strategy survives 20 to 40 out-of-sample test
  windows with performance that roughly matches the in-sample results, you
  have evidence of robustness."
- **evidence_strength**: STRONG as methodology; this project's Phase 21
  implements chronological train/validation/test splits and walk-forward
  folds directly on this basis. This project's synthetic-data sample size
  will generally fall short of "20-40 windows" for some strategy/regime
  cells — where it does, the report labels the result
  `INSUFFICIENT_SAMPLE`, not `EDGE_ESTABLISHED`.
- **measurable_definition**: `research/backtest/validation.py`.
- **possible_bias**: even walk-forward can overfit if the *researcher*
  iterates on the walk-forward result itself (meta-overfitting).
- **test_required**: report walk-forward fold count and per-fold
  dispersion, not just the average.

### T. Multiple-Testing / Data-Mining Bias

- **concept**: testing many strategy variants and reporting only the best
  one systematically overstates the true edge.
- **source**: Bailey & López de Prado (2014), "The Deflated Sharpe Ratio:
  Correcting for Selection Bias, Backtest Overfitting and Non-Normality"
  (SSRN 2460551).
- **source_type**: peer-reviewed / widely cited quantitative-finance
  methodology paper.
- **claim**: "the probability of selecting an overfit strategy grows
  rapidly with the number of trials"; performance metrics must be
  corrected for the number of configurations tried.
- **evidence_strength**: STRONG, directly actionable.
- **measurable_definition**: `research/backtest/validation.py` applies a
  Benjamini-Hochberg false-discovery-rate correction across the full set
  of strategy × regime × entry × exit cells tested, and reports the raw
  trial count alongside every "surviving" result.
- **possible_bias**: correction is only as good as the recorded trial
  count — this project logs every cell it runs (not just winners) to
  keep that count honest.
- **test_required**: N/A — this IS the required correction, applied
  throughout Phase 20–21.

### U/V. Portfolio Hedging / Correlation Between FX Pairs

- **concept**: opposing or correlated positions change portfolio-level
  risk; hedging has a measurable cost (given up expectancy on the hedge
  leg) and a measurable benefit (reduced variance/drawdown).
- **source**: standard portfolio theory (Markowitz variance-reduction
  logic applied to a 2–3 asset FX book); no strategy-specific paper cited
  — this project treats hedging as an empirical question per Phase 13's
  explicit instruction not to assume it helps.
- **source_type**: foundational portfolio theory, applied here as a
  measurement framework.
- **claim**: none assumed; to be measured (Phase 13, cases A–G).
- **evidence_strength**: N/A — measurement exercise.
- **measurable_definition**: `research/risk/portfolio.py` — realized
  correlation matrix from the synthetic multi-symbol dataset, gross/net
  exposure, case-by-case Sharpe/drawdown.
- **possible_bias**: synthetic correlation is a *designed* parameter
  (this project builds EURUSD/GBPUSD/USDJPY with a specified factor
  loading) — it validates the hedging *mechanics*, not real FX
  correlation behavior, which is regime-dependent and can invert during
  stress.
- **test_required**: explicit `DATA_UNAVAILABLE` label on any claim about
  *real* FX correlation; only mechanics/engine claims are supported here.

### W. Regime-Dependent Strategy Fit

- Covered under card D above (Trend-Following vs. Mean-Reversion Regimes);
  the Phase 3 classifier and Phase 18/26 comparison dashboards operate on
  this basis.

---

## Summary Table

| # | Concept | Evidence strength | Verdict routing |
|---|---|---|---|
| A/B | ORB | Moderate, market-specific | Test causally, report by regime |
| C | Intraday momentum | Strong (equities), untested (FX) | Test, do not assume transfer |
| D/W | Regime dependence | Weak-moderate | Test via causal classifier only |
| E/F/G | BOS/CHOCH/MSS | None (academic); framework only | Full validation required |
| H/I | Fibonacci levels | Weak | Test against random-level negative control |
| J | Candlestick patterns | Moderate, market-inconsistent | Conditional testing only, never standalone |
| K | ATR | Strong (as measurement) | Sensitivity sweep on lookback |
| L/M/N | SL/TP/Trailing | N/A (measurement) | Head-to-head, expectancy-primary |
| O | Position sizing / Kelly | Strong (math), weak (heuristics) | Fixed-fractional sweep, Kelly diagnostic-only |
| P/Q | Costs/spread | Strong (mechanism) | Report gross vs. net always |
| R | MTF confirmation | Weak/untested | Ablation required |
| S | Walk-forward | Strong (methodology) | Implemented; label INSUFFICIENT_SAMPLE where short |
| T | Multiple testing | Strong | BH-FDR applied throughout |
| U/V | Hedging/correlation | N/A (measurement); real-market claim unsupported | DATA_UNAVAILABLE for real-FX claims |
