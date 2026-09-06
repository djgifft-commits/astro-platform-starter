"""
Phase 12 — Risk engine: position sizing and account-level guards.

Lot size is calculated from account equity, risk %, entry/stop distance,
and contract specs -- never used as a risk-management substitute on its
own (MASTER COMMAND: "never use lot size as a substitute for risk
management").

Kelly is reported as a DIAGNOSTIC only (see RESEARCH_CARDS.md card O): it
is never used to auto-size a position, since doing so would let a
possibly-overfit sample edge estimate silently increase real risk, which
the MASTER COMMAND explicitly forbids ("confidence must never magically
increase risk unless statistically validated").
"""
from __future__ import annotations

import dataclasses
from typing import List, Optional

from research.config import CONTRACT_SIZE, PIP_SIZE


@dataclasses.dataclass
class PositionSize:
    lots: float
    units: float
    risk_amount: float
    risk_percent: float


def fixed_fractional_lots(
    equity: float,
    risk_percent: float,
    entry_price: float,
    stop_price: float,
    symbol: str,
    quote_to_account_rate: float = 1.0,
) -> PositionSize:
    """lots = (equity * risk%) / (stop_distance_in_quote_ccy * contract_size * quote_to_account_rate)"""
    stop_distance = abs(entry_price - stop_price)
    if stop_distance <= 0:
        return PositionSize(0.0, 0.0, 0.0, risk_percent)
    risk_amount = equity * risk_percent
    value_per_unit = stop_distance * quote_to_account_rate
    units = risk_amount / value_per_unit if value_per_unit > 0 else 0.0
    lots = units / CONTRACT_SIZE
    return PositionSize(lots=lots, units=units, risk_amount=risk_amount, risk_percent=risk_percent)


def volatility_adjusted_lots(
    equity: float,
    base_risk_percent: float,
    entry_price: float,
    stop_price: float,
    symbol: str,
    natr_percentile: float,
    quote_to_account_rate: float = 1.0,
) -> PositionSize:
    """Scales risk % down in the top volatility decile and up (modestly) in
    the bottom decile, capped to +/-25% of base risk, rather than letting a
    wide ATR-based stop alone dictate lot size (which fixed_fractional_lots
    already does implicitly through stop_distance)."""
    if natr_percentile >= 0.9:
        adj = 0.75
    elif natr_percentile <= 0.1:
        adj = 1.10
    else:
        adj = 1.0
    return fixed_fractional_lots(equity, base_risk_percent * adj, entry_price, stop_price, symbol, quote_to_account_rate)


def kelly_fraction_diagnostic(win_rate: float, avg_win_r: float, avg_loss_r: float) -> Optional[float]:
    """f* = (bp - q) / b, DIAGNOSTIC ONLY -- reported alongside backtest
    results, never fed back into position sizing. avg_loss_r should be
    positive (a magnitude)."""
    if avg_loss_r <= 0 or win_rate <= 0 or win_rate >= 1:
        return None
    b = avg_win_r / avg_loss_r
    p = win_rate
    q = 1 - win_rate
    f_star = (b * p - q) / b
    return f_star


@dataclasses.dataclass
class RiskGuardState:
    daily_pnl: float = 0.0
    current_drawdown: float = 0.0
    peak_equity: float = 0.0
    consecutive_losses: int = 0
    open_positions: int = 0
    symbol_exposure: dict = dataclasses.field(default_factory=dict)


@dataclasses.dataclass
class RiskLimits:
    max_daily_loss_pct: float = 0.03
    max_drawdown_pct: float = 0.15
    max_consecutive_losses: int = 6
    max_open_positions: int = 5
    max_symbol_exposure_lots: float = 1.0
    max_gross_exposure_lots: float = 3.0


def check_risk_limits(state: RiskGuardState, limits: RiskLimits, equity: float) -> List[str]:
    """Returns a list of violated limit names (empty = OK to trade)."""
    violations = []
    if state.daily_pnl <= -limits.max_daily_loss_pct * equity:
        violations.append("MAX_DAILY_LOSS")
    if state.current_drawdown >= limits.max_drawdown_pct:
        violations.append("MAX_DRAWDOWN")
    if state.consecutive_losses >= limits.max_consecutive_losses:
        violations.append("MAX_CONSECUTIVE_LOSSES")
    if state.open_positions >= limits.max_open_positions:
        violations.append("MAX_OPEN_POSITIONS")
    gross = sum(abs(v) for v in state.symbol_exposure.values())
    if gross >= limits.max_gross_exposure_lots:
        violations.append("MAX_GROSS_EXPOSURE")
    return violations


if __name__ == "__main__":
    ps = fixed_fractional_lots(equity=10_000, risk_percent=0.01, entry_price=1.0950, stop_price=1.0930, symbol="EURUSD")
    print(ps)
    assert ps.lots > 0

    k = kelly_fraction_diagnostic(win_rate=0.45, avg_win_r=1.8, avg_loss_r=1.0)
    print("Kelly diagnostic f* =", k)

    limits = RiskLimits()
    state = RiskGuardState(daily_pnl=-400, peak_equity=10_000, current_drawdown=0.05, consecutive_losses=2, open_positions=1)
    print(check_risk_limits(state, limits, equity=10_000))
    print("OK")
