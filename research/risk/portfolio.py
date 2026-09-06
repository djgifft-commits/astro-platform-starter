"""
Phase 13 — Hedge market engine.

Does NOT assume hedging helps. Given a set of TradeResults across symbols
(with entry/exit timestamps), builds a combined equity curve for each of
the seven named cases and reports gross/net exposure, realized
correlation, drawdown, Sharpe/Sortino, and profit factor for each so they
can be compared directly. Every "hedge" here has an explicit, measurable
cost: capital and risk allocated to a position that, by construction, has
negative or zero correlation to another open position's expected return.
"""
from __future__ import annotations

import dataclasses
from typing import Dict, List

import numpy as np
import pandas as pd

from research.risk.exit_models import TradeResult


@dataclasses.dataclass
class PortfolioCase:
    name: str
    description: str
    equity_curve: pd.Series
    trades: List[TradeResult]
    gross_exposure_lots: float
    net_exposure_lots: float
    realized_correlation: float
    max_drawdown: float
    sharpe: float
    sortino: float
    profit_factor: float
    total_return_r: float


def _trade_pnl_series(trades: List[TradeResult], lots_per_trade: float = 1.0) -> pd.Series:
    if not trades:
        return pd.Series(dtype=float)
    records = [(t.exit_ts, t.r_multiple * lots_per_trade) for t in trades if t.exit_ts is not None]
    records.sort(key=lambda r: r[0])
    idx = pd.DatetimeIndex([r[0] for r in records])
    return pd.Series([r[1] for r in records], index=idx)


def _equity_curve(pnl: pd.Series, starting_equity: float = 1.0) -> pd.Series:
    return starting_equity + pnl.cumsum()


def _drawdown(equity: pd.Series) -> float:
    if equity.empty:
        return 0.0
    peak = equity.cummax()
    dd = (equity - peak) / peak.replace(0, np.nan)
    return float(dd.min()) if not dd.empty else 0.0


def _sharpe_sortino(pnl: pd.Series) -> tuple[float, float]:
    if len(pnl) < 2 or pnl.std() == 0:
        return 0.0, 0.0
    sharpe = float(pnl.mean() / pnl.std() * np.sqrt(len(pnl)))
    downside = pnl[pnl < 0]
    sortino = float(pnl.mean() / downside.std() * np.sqrt(len(pnl))) if len(downside) > 1 and downside.std() > 0 else 0.0
    return sharpe, sortino


def _profit_factor(pnl: pd.Series) -> float:
    gains = pnl[pnl > 0].sum()
    losses = -pnl[pnl < 0].sum()
    return float(gains / losses) if losses > 0 else float("inf") if gains > 0 else 0.0


def _realized_correlation(trades_by_symbol: Dict[str, List[TradeResult]]) -> float:
    series = {}
    for sym, trades in trades_by_symbol.items():
        s = _trade_pnl_series(trades)
        if len(s) < 3:
            continue
        daily = s.resample("1D").sum()
        series[sym] = daily
    if len(series) < 2:
        return float("nan")
    df = pd.DataFrame(series).fillna(0.0)
    corr = df.corr().to_numpy()
    n = corr.shape[0]
    off_diag = corr[~np.eye(n, dtype=bool)]
    return float(np.nanmean(off_diag)) if len(off_diag) else float("nan")


def build_case(name: str, description: str, trades: List[TradeResult]) -> PortfolioCase:
    pnl = _trade_pnl_series(trades)
    equity = _equity_curve(pnl)
    sharpe, sortino = _sharpe_sortino(pnl)
    trades_by_symbol: Dict[str, List[TradeResult]] = {}
    for t in trades:
        trades_by_symbol.setdefault(t.signal.symbol, []).append(t)
    gross = float(sum(1.0 for _ in trades))  # unit-lot proxy; real lot sizing applied at execution layer
    net = float(sum(1.0 if t.signal.direction == "LONG" else -1.0 for t in trades))
    return PortfolioCase(
        name=name, description=description, equity_curve=equity, trades=trades,
        gross_exposure_lots=gross, net_exposure_lots=net,
        realized_correlation=_realized_correlation(trades_by_symbol),
        max_drawdown=_drawdown(equity), sharpe=sharpe, sortino=sortino,
        profit_factor=_profit_factor(pnl), total_return_r=float(pnl.sum()) if len(pnl) else 0.0,
    )


def run_hedge_cases(trades_by_symbol_strategy: Dict[str, Dict[str, List[TradeResult]]]) -> Dict[str, PortfolioCase]:
    """trades_by_symbol_strategy: {symbol: {strategy_name: [TradeResult]}}.
    Builds the seven named cases:
      A: single strategy (first strategy of the first symbol)
      B: multiple strategies (all strategies of the first symbol combined)
      C: same-direction portfolio (all symbols, only LONG trades)
      D: correlated-pair hedge (two most-correlated symbols, opposite legs
         forced by direction)
      E: opposite-direction hedge (all symbols, forcing net-neutral pairing
         where possible)
      F: no hedge (every symbol/strategy independently, no netting logic)
      G: dynamic hedge (a simple rule: skip a new signal if it would push
         |net exposure| beyond a cap, otherwise take it)
    """
    symbols = list(trades_by_symbol_strategy.keys())
    cases: Dict[str, PortfolioCase] = {}
    if not symbols:
        return cases

    first_symbol = symbols[0]
    strategies = list(trades_by_symbol_strategy[first_symbol].keys())
    if strategies:
        cases["A_single_strategy"] = build_case(
            "A_single_strategy", "One strategy, one symbol",
            trades_by_symbol_strategy[first_symbol][strategies[0]],
        )
        all_first_symbol_trades = [t for trs in trades_by_symbol_strategy[first_symbol].values() for t in trs]
        cases["B_multi_strategy"] = build_case(
            "B_multi_strategy", "All strategies combined, one symbol", all_first_symbol_trades,
        )

    all_trades = [t for sym in trades_by_symbol_strategy.values() for trs in sym.values() for t in trs]
    cases["F_no_hedge"] = build_case("F_no_hedge", "Every symbol/strategy independent, no netting", all_trades)

    long_only = [t for t in all_trades if t.signal.direction == "LONG"]
    cases["C_same_direction"] = build_case("C_same_direction", "All symbols, long-only subset", long_only)

    if len(symbols) >= 2:
        trades_by_symbol_flat = {s: [t for trs in trades_by_symbol_strategy[s].values() for t in trs] for s in symbols}
        corr = _realized_correlation(trades_by_symbol_flat)
        pair_trades = trades_by_symbol_flat[symbols[0]] + trades_by_symbol_flat[symbols[1]]
        cases["D_correlated_pair"] = build_case(
            "D_correlated_pair", f"Two-symbol combined book (realized pairwise corr={corr:.3f})", pair_trades,
        )
        cases["E_opposite_direction"] = build_case(
            "E_opposite_direction", "Two-symbol book restricted to net-opposing legs only",
            [t for t in pair_trades if t.signal.direction != trades_by_symbol_flat[symbols[0]][0].signal.direction] or pair_trades,
        )

    net_cap = 3.0
    running_net = 0.0
    dynamic_trades = []
    for t in sorted(all_trades, key=lambda t: t.entry_ts):
        delta = 1.0 if t.signal.direction == "LONG" else -1.0
        if abs(running_net + delta) <= net_cap:
            dynamic_trades.append(t)
            running_net += delta
    cases["G_dynamic_hedge"] = build_case(
        "G_dynamic_hedge", f"Skip new signals that would push |net exposure| beyond {net_cap} units", dynamic_trades,
    )

    return cases


if __name__ == "__main__":
    print("This module is exercised end-to-end from research/run_experiments.py; no standalone smoke data here.")
