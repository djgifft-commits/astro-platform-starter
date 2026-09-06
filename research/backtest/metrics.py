"""Shared trade-level and equity-level statistics used throughout Phases
20-27 and the audit report."""
from __future__ import annotations

from typing import Dict, List

import numpy as np
import pandas as pd

from research.risk.exit_models import TradeResult


def trade_stats(trades: List[TradeResult]) -> Dict[str, float]:
    if not trades:
        return {
            "n": 0, "win_rate": float("nan"), "expectancy_r": float("nan"), "median_r": float("nan"),
            "profit_factor": float("nan"), "avg_win_r": float("nan"), "avg_loss_r": float("nan"),
            "max_drawdown_r": float("nan"), "sharpe": float("nan"), "sortino": float("nan"),
            "avg_mfe_r": float("nan"), "avg_mae_r": float("nan"), "avg_duration_bars": float("nan"),
        }

    rs = np.array([t.r_multiple for t in trades])
    wins = rs[rs > 0]
    losses = rs[rs <= 0]
    win_rate = len(wins) / len(rs)
    expectancy = float(rs.mean())
    median_r = float(np.median(rs))
    gains = wins.sum()
    loss_sum = -losses.sum()
    profit_factor = float(gains / loss_sum) if loss_sum > 0 else (float("inf") if gains > 0 else 0.0)
    avg_win = float(wins.mean()) if len(wins) else 0.0
    avg_loss = float(losses.mean()) if len(losses) else 0.0

    equity = 1.0 + np.cumsum(rs)
    peak = np.maximum.accumulate(equity)
    dd = (equity - peak)
    max_dd = float(dd.min())

    sharpe = float(rs.mean() / rs.std() * np.sqrt(len(rs))) if rs.std() > 0 else 0.0
    downside = rs[rs < 0]
    sortino = float(rs.mean() / downside.std() * np.sqrt(len(rs))) if len(downside) > 1 and downside.std() > 0 else 0.0

    avg_mfe = float(np.mean([t.mfe_r for t in trades]))
    avg_mae = float(np.mean([t.mae_r for t in trades]))
    avg_duration = float(np.mean([t.duration_bars for t in trades]))

    return {
        "n": len(trades), "win_rate": win_rate, "expectancy_r": expectancy, "median_r": median_r,
        "profit_factor": profit_factor, "avg_win_r": avg_win, "avg_loss_r": avg_loss,
        "max_drawdown_r": max_dd, "sharpe": sharpe, "sortino": sortino,
        "avg_mfe_r": avg_mfe, "avg_mae_r": avg_mae, "avg_duration_bars": avg_duration,
    }


def equity_curve(trades: List[TradeResult]) -> pd.Series:
    if not trades:
        return pd.Series(dtype=float)
    ordered = sorted([t for t in trades if t.exit_ts is not None], key=lambda t: t.exit_ts)
    idx = pd.DatetimeIndex([t.exit_ts for t in ordered])
    r = pd.Series([t.r_multiple for t in ordered], index=idx)
    return (1.0 + r.cumsum())
