"""
Phase 9AB — Out-of-sample final test for the Phase 9B OR state machine.

LOCKED MODEL: OpeningRangeStateMachine(entry_family="breakout") with its
DEFAULT parameters (require_bias_agreement=True -- research/strategies/
opening_range_v2.py), BacktestConfig with its DEFAULT SL/TP/exit
(FIXED_ATR@1.5, FIXED_2R, FIXED).

LOCKED TEST DATA: a synthetic dataset generated with random seed 918273645
on EURUSD -- distinct from every other seed used anywhere else in this
codebase (RANDOM_SEED=20240906 in research/config.py, 424242 in
research/backtest/out_of_sample.py's Phase 8 lock, and 7 in a Phase 9B
mutation test; grep-verified before this module was written).

RULE: this script is run exactly once per invocation and its result is
reported as-is in the Phase 9B final report, with no follow-up parameter,
threshold, or strategy change permitted after seeing the number --
whatever it says.
"""
from __future__ import annotations

import numpy as np

from research.backtest.engine import BacktestConfig, run_backtest
from research.backtest.metrics import trade_stats
from research.backtest.validation import bootstrap_mean_ci, permutation_negative_control
from research.core.feature_bar import build_symbol_engine_data
from research.data.synthetic import generate_multi_symbol_dataset
from research.strategies.opening_range_v2 import OpeningRangeStateMachine

LOCKED_SEED = 918273645
LOCKED_SYMBOL = "EURUSD"
LOCKED_DAYS = 300


def run_locked_out_of_sample_test_9b() -> dict:
    ds = generate_multi_symbol_dataset([LOCKED_SYMBOL], n_days=LOCKED_DAYS, seed=LOCKED_SEED)
    ctx = build_symbol_engine_data(LOCKED_SYMBOL, ds[LOCKED_SYMBOL].bars)

    strategy = OpeningRangeStateMachine(entry_family="breakout")  # frozen defaults
    config = BacktestConfig()  # frozen defaults

    run = run_backtest(ctx, strategy, config)
    stats = trade_stats(run.trades)

    rs = np.array([t.r_multiple for t in run.trades])
    ci = bootstrap_mean_ci(rs, n_boot=1000) if len(rs) >= 2 else {"excludes_zero": False}
    perm = permutation_negative_control(rs, n_perm=1000) if len(rs) >= 2 else {"p_value": 1.0}

    return {
        "locked_seed": LOCKED_SEED, "locked_symbol": LOCKED_SYMBOL, "locked_days": LOCKED_DAYS,
        "strategy": "opening_range_v2 breakout (default params, frozen)",
        "config": "FIXED_ATR@1.5 / FIXED_2R / FIXED (default)",
        **stats,
        "bootstrap_ci": ci,
        "permutation": perm,
    }


if __name__ == "__main__":
    result = run_locked_out_of_sample_test_9b()
    print(result)
    print("OK")
