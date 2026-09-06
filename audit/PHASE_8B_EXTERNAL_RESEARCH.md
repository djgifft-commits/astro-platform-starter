# Phase 8B — External Research (fresh, Phase 8-specific)

This supplements `audit/RESEARCH_CARDS.md` (Phase 7/Phase 0), which
already covers ORB, intraday momentum, trend/mean-reversion regimes, BOS/
CHOCH/MSS terminology, Fibonacci, candlesticks, ATR, SL/TP/trailing
methods, Kelly/position sizing, transaction costs, MTF confirmation,
walk-forward validation, and multiple-testing correction — those cards
are not repeated here. This document covers only the topics Phase 8
raises that Phase 7 did not: purged/embargoed cross-validation, DXY, and
regime-dependent (dynamic) correlation. As in Phase 7: research informs
hypotheses; only the experiments in this branch's code decide whether a
hypothesis survives.

---

### Purged / Embargoed Cross-Validation (Phase 8B item L, Phase 8W)

- **source**: López de Prado (2017, *Advances in Financial Machine
  Learning*, formalized on Wikipedia's "Purged cross-validation" page);
  Bailey, Borwein, López de Prado & Zhu, Combinatorial Purged
  Cross-Validation (CPCV) methodology.
- **source_type**: peer-reviewed / widely-adopted quant methodology,
  originating from a named practitioner-academic (Guggenheim Partners /
  Cornell).
- **claim**: standard k-fold cross-validation on financial time series
  leaks information because a label's outcome window can overlap between
  a "training" fold and a "test" fold that are chronologically adjacent.
  **Purging** removes training observations whose outcome window overlaps
  the test window; an **embargo** additionally excludes a further window
  of training observations immediately after the test period, since
  serial correlation in financial data means information can leak forward
  even without direct overlap. **Combinatorial Purged CV (CPCV)** extends
  this to generate many train/test path combinations rather than one
  linear walk-forward sequence, "testing every part of the series
  multiple times."
- **evidence_strength**: STRONG — this is a widely cited, mechanically
  precise correction for a real, well-understood leakage mode, not a
  probabilistic claim requiring further validation of its own.
- **measurable_definition**: this project's `research/backtest/
  validation.py::purged_walk_forward_folds` (Phase 8W deliverable) removes
  training trades whose *outcome window* (entry → exit) overlaps the test
  fold's time span, and additionally excludes training trades whose entry
  falls within `embargo_bars` after the test fold ends.
- **possible_bias**: purging/embargo correct a real leakage mode but do
  NOT correct for the separate multiple-testing bias already handled by
  BH-FDR (Phase 7) — the two corrections are complementary, not
  substitutes for each other, and this project applies both.
- **test_required**: re-run the Phase 7 walk-forward validation with
  purging/embargo added and report whether any previously-`EDGE_ESTABLISHED`
  or `INFORMATION_PRESENT` cell changes classification — a change would
  indicate the original walk-forward folds materially benefited from
  boundary leakage.

### DXY / US Dollar Index correlation (Phase 8Y "BASELINE + DXY")

- **source**: general FX-market-structure explainer material (dealer/
  broker education content — PriceActionNinja, Blueberry Markets, Orbex);
  DXY's own published formula
  (`50.14 × EURUSD^-0.576 × USDJPY^0.136 × GBPUSD^-0.119 × USDCAD^0.091 ×
  USDSEK^0.042 × USDCHF^0.036`) is a matter of public index-construction
  record, not a statistical finding.
- **source_type**: MOSTLY practitioner/broker-education content, not
  peer-reviewed. The index formula itself is authoritative (ICE/NYBOT
  index construction); the "85%+ correlation," "50-80 pip move" claims are
  **unverified marketing-adjacent statistics**, not independently
  reproduced in this research pass.
- **claim**: EURUSD has a strong, mechanically-explained inverse
  relationship with DXY because EUR/USD is ~57.6% of the index's log-
  weighted formula by construction — this part is a mathematical fact, not
  an empirical claim. Beyond EURUSD, the relationship to other pairs
  (GBPUSD, USDJPY, etc.) is looser and time-varying.
- **evidence_strength**: STRONG for the EURUSD/DXY mechanical relationship
  (it is definitional, not statistical); WEAK/unverified for specific
  correlation percentages or pip-conversion figures quoted by broker
  content.
- **measurable_definition**: this project has **no DXY data** — real or
  synthetic. Building a synthetic "DXY" as a weighted combination of this
  project's own synthetic USD pairs would be circular (it would recover
  exactly the mechanical relationship already encoded in the same
  correlated-factor generator, proving nothing new). **Verdict:
  `DATA_UNAVAILABLE`** for any DXY-conditioned experiment in this project;
  Phase 8Y's "BASELINE + DXY" ablation cell is explicitly marked
  `DATA_UNAVAILABLE` in the ablation matrix rather than faked with a
  synthetic proxy.
- **test_required**: N/A until real DXY (or real constituent-pair) data is
  available.

### Regime-dependent / dynamic correlation and correlation breakdown (Phase 8S)

- **source**: general cross-asset correlation literature (rolling-
  correlation-network studies on arXiv, e.g. regime-dependent
  cross-asset spillover research; USD/CNY crisis-correlation studies using
  rolling correlation and DCC-GARCH); practitioner synthesis (Collin
  Seow, "Correlation Breakdown During Crises").
- **source_type**: mixed — some peer-reviewed/preprint academic work on
  specific pairs (USD/CNY), some practitioner synthesis of the general
  phenomenon.
- **claim**: correlations are **regime-dependent, not stable**, and have
  "an unfortunate tendency to spike toward 1.0 exactly when you need
  diversification most" — i.e., in a crisis or high-volatility regime,
  previously-diversifying assets often move together, precisely
  undermining a hedge built on a calmer-period correlation estimate.
  Rolling-window correlation is better than a single static number but
  is inherently backward-looking and "will lie to you during regime
  transitions."
- **evidence_strength**: MODERATE-STRONG as a general stylized fact
  (widely documented across multiple asset classes and specific pairs);
  WEAK as applied to this project's own synthetic multi-symbol basket
  specifically, since that basket's correlation structure is a designed
  generator parameter, not an emergent market phenomenon.
- **measurable_definition**: this is the direct motivation for Phase 8S's
  rolling correlation/beta module (`research/risk/hedge.py`), replacing
  Phase 7's single static `_realized_correlation` number with a
  time-varying series, explicitly measured across the four regime windows
  Phase 8S names (normal, high-volatility, trend, reversal) using this
  project's own causal regime classifier (Section 6 of Phase 7's report)
  to select those windows.
- **possible_bias**: because this project's synthetic multi-symbol
  correlation is a *designed* generator parameter (not real market
  behavior), any "correlation breaks down in high-volatility regimes"
  finding from this project's own data would be a mechanical artifact of
  how `research/data/synthetic.py` composes its shock-volatility term with
  the shared factor loading, not independent confirmation of the general
  real-market phenomenon cited above. **This project's rolling-
  correlation results validate the measurement MACHINERY only** — labeled
  `DATA_UNAVAILABLE` for any claim about real FX correlation behavior,
  exactly as Phase 7's static correlation result was labeled.
- **test_required**: `research/risk/hedge.py`'s rolling correlation/beta,
  re-computed per regime window, on synthetic data, reported as an engine-
  validation result only.

### Position sizing / risk-of-ruin formalism (supplementing Phase 7's Kelly card)

- **source**: standard risk-of-ruin formalism from gambling/trading
  mathematics (the classical risk-of-ruin formula for a biased random walk
  with fixed bet fraction); already partially covered by Phase 7's Kelly
  card (RESEARCH_CARDS.md card O).
- **source_type**: foundational applied-probability result.
- **claim**: for a strategy with edge `p` (win probability) and
  payoff ratio `b`, and fixed fractional risk `f` per trade, the
  probability of hitting a given drawdown threshold before growing equity
  can be approximated in closed form for the idealized (i.i.d., binary
  outcome) case; real trade sequences violate the i.i.d. assumption
  (serial correlation, regime dependence), so the closed-form risk-of-ruin
  is a **lower bound sanity check**, not a precise forecast.
- **evidence_strength**: STRONG as pure mathematics under stated
  assumptions; WEAK as a predictor of actual real-world ruin probability,
  precisely because real returns are not i.i.d.
- **measurable_definition**: this project reports an *empirical* proxy —
  the observed maximum drawdown and worst-day/week/month across the
  actual (non-i.i.d.) simulated trade sequence at each tested risk level
  (Phase 7's `risk_level_sweep.json`, extended in Phase 8U) — rather than
  computing the closed-form formula, precisely because the closed-form
  result's i.i.d. assumption is known to be violated by real trade
  sequences (serial correlation from overlapping trades, regime
  clustering).
- **test_required**: N/A — already implemented as the empirical drawdown/
  worst-period reporting in Phase 7, extended in Phase 8U.

---

## Summary Table

| # | Concept | Evidence strength | Verdict routing |
|---|---|---|---|
| Purged/embargoed CV | Strong (mechanical leakage fix) | Implement and re-check Phase 7 verdicts for sensitivity to leakage |
| DXY / EURUSD mechanical relationship | Strong (definitional) | Cannot test — no DXY data, real or non-circular synthetic — `DATA_UNAVAILABLE` |
| DXY specific correlation % claims | Weak (unverified broker content) | Not used for any quantitative claim in this project |
| Regime-dependent correlation breakdown (general) | Moderate-strong (real-market literature) | Motivates rolling correlation/beta build; own results labeled `DATA_UNAVAILABLE` for real-market claims |
| Risk-of-ruin closed-form | Strong (math), weak (real-world applicability) | Use empirical drawdown proxy instead, as Phase 7 already did |

## Sources

- [Purged cross-validation — Wikipedia](https://en.wikipedia.org/wiki/Purged_cross-validation)
- [The Pitfalls of Standard Cross-Validation in Financial Machine Learning](https://bhakta-works.medium.com/the-pitfalls-of-standard-cross-validation-in-financial-machine-learning-aec03f672179)
- [THE 10 REASONS MOST MACHINE LEARNING FUNDS FAIL — Marcos López de Prado (GARP)](https://www.garp.org/hubfs/Whitepapers/a1Z1W0000054x6lUAA.pdf)
- [Dollar Index (DXY) Correlations Explained — PriceActionNinja](https://priceactionninja.com/dollar-index-dxy-correlations-explained-how-other-markets-impact-the-dollar/)
- [How to Use the USDX for Smarter Forex Trades — Blueberry Markets](https://blueberrymarkets.com/market-analysis/how-to-use-the-usdx-for-forex-trading/)
- [Correlation Breakdown During Crises — Collin Seow](https://collinseow.com/correlation-crises-guide/)
- [USD/CNY Exchange Rate Correlation dynamic mechanism — Economics Open](https://www.worldscientific.com/doi/full/10.1142/S3082841425500054)
- [Backtest overfitting in the machine learning era — ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0950705124011110)
