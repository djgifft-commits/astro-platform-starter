# Research / Backtesting Sandbox (Phase 7 + Phase 8)

**This is a standalone research project living inside the
`astro-platform-starter` repository. It has no connection to the Astro
site, no MT5/broker integration, and no live trading capability.** See
`audit/PHASE_7_MULTI_STRATEGY_HEDGE_BACKTEST.md` and `audit/
PHASE_8_REAL_DATA_MULTI_STRATEGY_HEDGE_BACKTEST.md` for the full research
reports, `audit/RESEARCH_CARDS.md` + `audit/PHASE_8B_EXTERNAL_RESEARCH.md`
for the external-research basis, and `audit/
PHASE_8A_ARCHITECTURE_AUDIT.md` for why Phase 8 still runs on synthetic
data (no real historical data is reachable from this environment — see
that document for the direct evidence).

Run `research/.venv/bin/python -m research.run_experiments_phase8` to
regenerate `research/results_8/` (the Phase 8 artifacts the web terminal's
`[P8]`-prefixed tabs read), in addition to the `run_experiments`
instructions below for the Phase 7 artifacts.

## Why this exists

`djgifft-commits/astro-platform-starter` is the Netlify Astro Platform
Starter template. It contains no trading, backtesting, or market-data code
of any kind. A request to build a "research-grade multi-strategy hedge
market backtesting engine, reusing existing production functions" was
made against this repository; since no such production system exists here
to reuse, this was built greenfield, using a labeled SYNTHETIC data
generator (see DATA DISCLOSURE below) rather than fabricating a connection
to real market data that isn't available in this environment.

## DATA DISCLOSURE

There is **no MT5, broker, or live/historical market-data feed** anywhere
in this project. `research/data/synthetic.py` generates a regime-
switching, session-aware, correlated random-walk FX price process for
engine-validation purposes only. **No number produced by this codebase is
a claim about real market behavior.** Every result is either an engine
correctness check (e.g. "the resampler never exposes a forming bar") or an
ENGINE VALIDATION statistic on synthetic data (e.g. "this strategy has
negative expectancy on synthetic data, net of synthetic spread costs").

## Setup

```bash
cd research
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
```

## Running the research pipeline

```bash
./research/.venv/bin/python -m research.run_experiments
```

Writes JSON artifacts to `research/results/` (gitignored by default —
regenerate rather than expecting them to be committed).

## Running the web terminal

```bash
./research/.venv/bin/python web/app.py
# open http://127.0.0.1:8050
```

## Layout

```
research/
  config.py              constants, DATA DISCLOSURE
  data/
    synthetic.py          SYNTHETIC_DATA generator
    loaders.py             causal timeframe resampling
    quality.py              Phase 2 data quality / causality audit
  core/
    sessions.py            Phase 17 session engine, NY opening range (DST-correct)
    atr.py                  ATR / volatility normalization
    candle_anatomy.py        Phase 6 candlestick geometry + pattern recognizer
    structure.py             Phase 3/5 swing/BOS/CHOCH/MSS (mechanical, causal)
    regime.py                 Phase 3 market condition classifier
    bias.py                    Phase 4 multi-timeframe directional bias
    fibonacci.py                Phase 7 retracement engine (+ negative-control levels)
    liquidity.py                 Phase 19 ESTIMATED_STOP_LIQUIDITY / ICEBERG_DATA_UNAVAILABLE
    feature_bar.py                per-symbol causal feature-bar engine
  strategies/               Phase 5 strategy library (base.py + 6 strategies)
  risk/                      Phases 9-13: SL/TP/exit models, position sizing, portfolio/hedge
  backtest/                  Phases 20-22: engine, metrics, validation, ablation
  run_experiments.py        orchestrator -> research/results/*.json
web/
  app.py                    Phases 23-27 Dash/Plotly terminal
audit/
  RESEARCH_CARDS.md          Phase 0 external research
  PHASE_7_MULTI_STRATEGY_HEDGE_BACKTEST.md   Phase 29 report
  SAFETY_REPORT.md            Phase 30 governance/safety audit
```

## Every module's own test

Every module under `research/` has a `if __name__ == "__main__":` block
that exercises and sanity-checks it in isolation, including explicit
causality assertions (e.g. "recomputing a feature with only the first half
of the data must not change any value in that half"). Run any of them
directly, e.g.:

```bash
./research/.venv/bin/python -m research.core.structure
./research/.venv/bin/python -m research.strategies.opening_range
```
