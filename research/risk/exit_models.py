"""
Phase 11 — Exit model research.

This is explicitly an experiment: `simulate_trade` walks the trade forward
bar-by-bar (causal — the entry bar itself is excluded from exit
evaluation, since exit decisions must not use the same bar's range that
produced the entry signal) and applies exactly one named exit model.
Nothing here declares a winner; research/backtest/validation.py does that,
out-of-sample, per strategy/regime.

Implemented (8 of the 12 named in the MASTER COMMAND):
  EXIT_A  FIXED               (fixed SL/TP)
  EXIT_B  STRUCTURE           (exit on first opposite-direction structure
                                break after entry — this also covers
                                EXIT_H "opposite MSS/CHOCH": under this
                                project's mechanical BOS/CHOCH definitions
                                the two are the same event stream, so
                                testing both separately would test the same
                                hypothesis twice)
  EXIT_C  TRAILING_ATR
  EXIT_D  TRAILING_SWING
  EXIT_E  BREAKEVEN_1R
  EXIT_F  PARTIAL_1R_RUNNER
  EXIT_I  TIME_BASED
  EXIT_J  SESSION_CLOSE
Deferred: EXIT_G (liquidity target — same mechanical target as
STRUCTURE_TARGET in tp_models.py under this project's swing-based
liquidity-pool definition) and EXIT_K/L (hybrid/strategy-specific —
compositions of the above, not new mechanisms; a specific composition can
be added once Phase 21 shows a base model that needs it).
"""
from __future__ import annotations

import dataclasses
from typing import List, Optional

import pandas as pd

from research.core.sessions import NY_SESSION_OPEN, NY_TZ, session_open_utc
from research.strategies.base import Signal, window_after

EXIT_MODELS = [
    "FIXED", "STRUCTURE", "TRAILING_ATR", "TRAILING_SWING",
    "BREAKEVEN_1R", "PARTIAL_1R_RUNNER", "TIME_BASED", "SESSION_CLOSE",
]


@dataclasses.dataclass
class TradeResult:
    signal: Signal
    sl_model: str
    tp_model: Optional[str]
    exit_model: str
    entry_ts: pd.Timestamp
    entry_price: float
    initial_sl: float
    initial_risk: float
    exit_ts: Optional[pd.Timestamp]
    exit_price: Optional[float]
    exit_reason: str
    r_multiple: float
    mfe_r: float
    mae_r: float
    duration_bars: int
    partial_taken: bool = False


def _signed(direction: str, value_long: float, value_short: float) -> float:
    return value_long if direction == "LONG" else value_short


def simulate_trade(
    signal: Signal,
    exec_df: pd.DataFrame,
    atr_series: pd.Series,
    initial_sl: float,
    exit_model: str,
    initial_tp: Optional[float] = None,
    structure_events: Optional[List] = None,
    swings: Optional[List] = None,
    max_bars: int = 500,
    time_based_bars: int = 48,
    trailing_atr_mult: float = 2.0,
    breakeven_r_trigger: float = 1.0,
    partial_r_trigger: float = 1.0,
    sl_model_name: str = "",
    tp_model_name: Optional[str] = None,
) -> TradeResult:
    direction = signal.direction
    entry_price = signal.entry_price
    initial_risk = abs(entry_price - initial_sl)
    if initial_risk <= 0:
        return TradeResult(signal, sl_model_name, tp_model_name, exit_model, signal.entry_ts, entry_price,
                            initial_sl, 0.0, signal.entry_ts, entry_price, "INVALID_RISK", 0.0, 0.0, 0.0, 0)

    future = window_after(exec_df, signal.entry_ts, max_bars)
    if future.empty:
        return TradeResult(signal, sl_model_name, tp_model_name, exit_model, signal.entry_ts, entry_price,
                            initial_sl, initial_risk, None, None, "NO_FUTURE_DATA", 0.0, 0.0, 0.0, 0)

    current_sl = initial_sl
    mfe_r = 0.0
    mae_r = 0.0
    partial_taken = False
    trailing_extreme = entry_price
    session_close_ts = None
    if exit_model == "SESSION_CLOSE":
        d = signal.entry_ts.tz_convert(NY_TZ).normalize()
        session_close_ts = session_open_utc(d, "17:00", NY_TZ)
        if session_close_ts <= signal.entry_ts:
            session_close_ts = session_open_utc(d + pd.Timedelta(days=1), "17:00", NY_TZ)

    for bar_idx, (ts, row) in enumerate(future.iterrows(), start=1):
        high, low, close = row["high"], row["low"], row["close"]

        fav_excursion = _signed(direction, high - entry_price, entry_price - low)
        adv_excursion = _signed(direction, entry_price - low, high - entry_price)
        mfe_r = max(mfe_r, fav_excursion / initial_risk)
        mae_r = max(mae_r, adv_excursion / initial_risk)

        sl_hit = (low <= current_sl) if direction == "LONG" else (high >= current_sl)
        tp_hit = initial_tp is not None and ((high >= initial_tp) if direction == "LONG" else (low <= initial_tp))

        if exit_model == "FIXED":
            if sl_hit:
                return _close(signal, sl_model_name, tp_model_name, exit_model, entry_price, initial_sl,
                              initial_risk, ts, current_sl, "SL_HIT", mfe_r, mae_r, bar_idx)
            if tp_hit:
                return _close(signal, sl_model_name, tp_model_name, exit_model, entry_price, initial_sl,
                              initial_risk, ts, initial_tp, "TP_HIT", mfe_r, mae_r, bar_idx)

        elif exit_model == "STRUCTURE":
            if sl_hit:
                return _close(signal, sl_model_name, tp_model_name, exit_model, entry_price, initial_sl,
                              initial_risk, ts, current_sl, "SL_HIT", mfe_r, mae_r, bar_idx)
            opposite = [e for e in (structure_events or []) if e.timestamp <= ts and e.timestamp > signal.entry_ts
                        and ((direction == "LONG" and e.direction == "BEARISH") or (direction == "SHORT" and e.direction == "BULLISH"))]
            if opposite:
                return _close(signal, sl_model_name, tp_model_name, exit_model, entry_price, initial_sl,
                              initial_risk, ts, close, "OPPOSITE_STRUCTURE_BREAK", mfe_r, mae_r, bar_idx)

        elif exit_model == "TRAILING_ATR":
            if sl_hit:
                return _close(signal, sl_model_name, tp_model_name, exit_model, entry_price, initial_sl,
                              initial_risk, ts, current_sl, "SL_HIT", mfe_r, mae_r, bar_idx)
            a = atr_series.asof(ts)
            if pd.notna(a):
                if direction == "LONG":
                    trailing_extreme = max(trailing_extreme, high)
                    current_sl = max(current_sl, trailing_extreme - trailing_atr_mult * a)
                else:
                    trailing_extreme = min(trailing_extreme, low)
                    current_sl = min(current_sl, trailing_extreme + trailing_atr_mult * a)

        elif exit_model == "TRAILING_SWING":
            if sl_hit:
                return _close(signal, sl_model_name, tp_model_name, exit_model, entry_price, initial_sl,
                              initial_risk, ts, current_sl, "SL_HIT", mfe_r, mae_r, bar_idx)
            kind_needed = "LOW" if direction == "LONG" else "HIGH"
            recent = [s for s in (swings or []) if s.timestamp <= ts and s.kind == kind_needed]
            if recent:
                candidate = recent[-1].price
                current_sl = max(current_sl, candidate) if direction == "LONG" else min(current_sl, candidate)

        elif exit_model == "BREAKEVEN_1R":
            if sl_hit:
                return _close(signal, sl_model_name, tp_model_name, exit_model, entry_price, initial_sl,
                              initial_risk, ts, current_sl, "SL_HIT", mfe_r, mae_r, bar_idx)
            if tp_hit:
                return _close(signal, sl_model_name, tp_model_name, exit_model, entry_price, initial_sl,
                              initial_risk, ts, initial_tp, "TP_HIT", mfe_r, mae_r, bar_idx)
            if fav_excursion / initial_risk >= breakeven_r_trigger:
                current_sl = max(current_sl, entry_price) if direction == "LONG" else min(current_sl, entry_price)

        elif exit_model == "PARTIAL_1R_RUNNER":
            if not partial_taken and fav_excursion / initial_risk >= partial_r_trigger:
                partial_taken = True
                current_sl = entry_price
            if sl_hit:
                reason = "SL_HIT_AFTER_PARTIAL" if partial_taken else "SL_HIT"
                return _close(signal, sl_model_name, tp_model_name, exit_model, entry_price, initial_sl,
                              initial_risk, ts, current_sl, reason, mfe_r, mae_r, bar_idx, partial_taken)
            if tp_hit:
                return _close(signal, sl_model_name, tp_model_name, exit_model, entry_price, initial_sl,
                              initial_risk, ts, initial_tp, "TP_HIT", mfe_r, mae_r, bar_idx, partial_taken)

        elif exit_model == "TIME_BASED":
            if sl_hit:
                return _close(signal, sl_model_name, tp_model_name, exit_model, entry_price, initial_sl,
                              initial_risk, ts, current_sl, "SL_HIT", mfe_r, mae_r, bar_idx)
            if tp_hit:
                return _close(signal, sl_model_name, tp_model_name, exit_model, entry_price, initial_sl,
                              initial_risk, ts, initial_tp, "TP_HIT", mfe_r, mae_r, bar_idx)
            if bar_idx >= time_based_bars:
                return _close(signal, sl_model_name, tp_model_name, exit_model, entry_price, initial_sl,
                              initial_risk, ts, close, "TIME_LIMIT", mfe_r, mae_r, bar_idx)

        elif exit_model == "SESSION_CLOSE":
            if sl_hit:
                return _close(signal, sl_model_name, tp_model_name, exit_model, entry_price, initial_sl,
                              initial_risk, ts, current_sl, "SL_HIT", mfe_r, mae_r, bar_idx)
            if tp_hit:
                return _close(signal, sl_model_name, tp_model_name, exit_model, entry_price, initial_sl,
                              initial_risk, ts, initial_tp, "TP_HIT", mfe_r, mae_r, bar_idx)
            if session_close_ts is not None and ts >= session_close_ts:
                return _close(signal, sl_model_name, tp_model_name, exit_model, entry_price, initial_sl,
                              initial_risk, ts, close, "SESSION_CLOSE", mfe_r, mae_r, bar_idx)
        else:
            raise ValueError(f"unknown exit_model {exit_model}")

    last_row = future.iloc[-1]
    return _close(signal, sl_model_name, tp_model_name, exit_model, entry_price, initial_sl, initial_risk,
                  future.index[-1], last_row["close"], "END_OF_DATA", mfe_r, mae_r, len(future), partial_taken)


def _close(signal, sl_model_name, tp_model_name, exit_model, entry_price, initial_sl, initial_risk,
           exit_ts, exit_price, reason, mfe_r, mae_r, duration_bars, partial_taken=False) -> TradeResult:
    sign = 1 if signal.direction == "LONG" else -1
    pnl_price = sign * (exit_price - entry_price)
    r_multiple = pnl_price / initial_risk if initial_risk > 0 else 0.0
    return TradeResult(
        signal=signal, sl_model=sl_model_name, tp_model=tp_model_name, exit_model=exit_model,
        entry_ts=signal.entry_ts, entry_price=entry_price, initial_sl=initial_sl, initial_risk=initial_risk,
        exit_ts=exit_ts, exit_price=exit_price, exit_reason=reason,
        r_multiple=r_multiple, mfe_r=mfe_r, mae_r=mae_r, duration_bars=duration_bars, partial_taken=partial_taken,
    )


if __name__ == "__main__":
    from research.core.feature_bar import build_symbol_engine_data
    from research.data.synthetic import generate_multi_symbol_dataset
    from research.risk import sl_models, tp_models
    from research.strategies.opening_range import OpeningRangeBreakout

    ds = generate_multi_symbol_dataset(["EURUSD"], n_days=90)
    data = build_symbol_engine_data("EURUSD", ds["EURUSD"].bars)
    strat = OpeningRangeBreakout(variant="continuation")
    signals, _ = strat.scan(data)
    print(f"{len(signals)} signals to test exits on")

    exec_df = data.frames[data.execution_tf]
    from collections import Counter
    for exit_model in EXIT_MODELS:
        reasons = Counter()
        rs = []
        for sig in signals[:200]:
            a = data.atr_series.asof(sig.entry_ts)
            if pd.isna(a):
                continue
            sl = sl_models.fixed_atr(sig, a, mult=1.5)
            tp = tp_models.fixed_r(sig, sl.distance, 2.0)
            res = simulate_trade(sig, exec_df, data.atr_series, sl.price, exit_model, initial_tp=tp.price,
                                  structure_events=data.structure_events, sl_model_name=sl.model, tp_model_name=tp.model)
            reasons[res.exit_reason] += 1
            rs.append(res.r_multiple)
        avg_r = sum(rs) / len(rs) if rs else float("nan")
        print(f"{exit_model}: n={len(rs)} avg_R={avg_r:.3f} reasons={dict(reasons)}")
    print("OK")
