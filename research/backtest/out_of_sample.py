"""
Phase 8AH — Out-of-sample final test.

LOCKED MODEL: TrendPullback with its DEFAULT parameters (min_depth=0.30,
max_depth=0.65, min_persistence=0.55 -- research/strategies/
trend_pullback.py), BacktestConfig with its DEFAULT SL/TP/exit
(FIXED_ATR@1.5, FIXED_2R, FIXED), on XAUUSD -- the exact configuration
that reached `EDGE_ESTABLISHED` in Phase 7 and was then perturbation-
tested in research/backtest/robustness.py.

LOCKED TEST DATA: a synthetic dataset generated with random seed 424242,
distinct from every other seed used anywhere else in this project (Phase
7's orchestrator and every Phase 8 module either use the default
RANDOM_SEED from research/config.py or an explicit seed the docstring/
call site names -- 424242 has not appeared anywhere else in this
codebase, grep-verified before this module was written).

RULE: this script is run exactly once per invocation and its result is
reported as-is in the final report, with no follow-up parameter,
threshold, or strategy change permitted after seeing the number --
whatever it says.
"""
from __future__ import annotations

from research.backtest.engine import BacktestConfig, run_backtest
from research.backtest.metrics import trade_stats
from research.backtest.validation import bootstrap_mean_ci, permutation_negative_control
from research.core.feature_bar import build_symbol_engine_data
from research.data.synthetic import generate_multi_symbol_dataset
from research.strategies.trend_pullback import TrendPullback

LOCKED_SEED = 424242
LOCKED_SYMBOL = "XAUUSD"
LOCKED_DAYS = 300


def run_locked_out_of_sample_test() -> dict:
    ds = generate_multi_symbol_dataset([LOCKED_SYMBOL], n_days=LOCKED_DAYS, seed=LOCKED_SEED)
    ctx = build_symbol_engine_data(LOCKED_SYMBOL, ds[LOCKED_SYMBOL].bars)

    strategy = TrendPullback()  # frozen defaults, unchanged from Phase 7
    config = BacktestConfig()   # frozen defaults, unchanged from Phase 7

    run = run_backtest(ctx, strategy, config)
    stats = trade_stats(run.trades)

    import numpy as np
    rs = np.array([t.r_multiple for t in run.trades])
    ci = bootstrap_mean_ci(rs, n_boot=1000) if len(rs) >= 2 else {"excludes_zero": False}
    perm = permutation_negative_control(rs, n_perm=1000) if len(rs) >= 2 else {"p_value": 1.0}

    return {
        "locked_seed": LOCKED_SEED, "locked_symbol": LOCKED_SYMBOL, "locked_days": LOCKED_DAYS,
        "strategy": "trend_pullback (default params, frozen from Phase 7)",
        "config": "FIXED_ATR@1.5 / FIXED_2R / FIXED (default, frozen from Phase 7)",
        **stats,
        "bootstrap_ci": ci,
        "permutation": perm,
    }


if __name__ == "__main__":
    result = run_locked_out_of_sample_test()
    for k, v in result.items():
        print(k, ":", v)
    print("OK -- this result is reported as-is in the final report, no follow-up changes permitted.")
