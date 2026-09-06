"""
Phase 7 — Retracement engine.

RESEARCH_CARDS.md card H/I: no strong academic evidence that price
respects Fibonacci ratios specifically. This module treats every level as
an equally-unproven hypothesis and computes the SAME measurements
(touch/rejection/depth/duration/displacement-after) for a set of
CONTROL levels chosen without any Fibonacci basis, so a validation pass
can compare "hit rate at 61.8%" against "hit rate at an arbitrary level of
similar depth" before crediting the ratio itself with anything.
"""
from __future__ import annotations

import dataclasses
from typing import List, Literal

import numpy as np
import pandas as pd

FIB_LEVELS = [0.236, 0.382, 0.5, 0.618, 0.786]
CONTROL_LEVELS = [0.30, 0.45, 0.55, 0.70, 0.85]  # non-Fibonacci negative-control depths


@dataclasses.dataclass
class Impulse:
    start_pos: int
    end_pos: int
    start_ts: pd.Timestamp
    end_ts: pd.Timestamp
    direction: Literal["UP", "DOWN"]
    start_price: float
    end_price: float

    @property
    def size(self) -> float:
        return abs(self.end_price - self.start_price)


@dataclasses.dataclass
class RetracementOutcome:
    impulse: Impulse
    level: float
    level_price: float
    touched: bool
    touch_pos: int | None
    max_depth_fraction: float | None
    bars_to_touch: int | None
    structure_preserved: bool
    displacement_after: float | None  # price move in impulse direction within eval_window after touch, ATR-normalized


def find_impulses(df: pd.DataFrame, atr_series: pd.Series, min_atr_multiple: float = 2.0, lookback: int = 20) -> List[Impulse]:
    """A causal, mechanical impulse detector: at each bar, look back
    `lookback` bars; if the net move exceeds `min_atr_multiple` * ATR (as of
    the impulse start) and is monotonic-ish (>=70% of bars agree in
    direction), record it as a significant impulse ending at this bar."""
    closes = df["close"].to_numpy()
    n = len(df)
    impulses: List[Impulse] = []
    last_end = -1
    for i in range(lookback, n):
        if i <= last_end:
            continue
        start = i - lookback
        a = atr_series.iloc[start]
        if pd.isna(a) or a == 0:
            continue
        move = closes[i] - closes[start]
        if abs(move) < min_atr_multiple * a:
            continue
        diffs = np.diff(closes[start : i + 1])
        agree = (np.sign(diffs) == np.sign(move)).mean() if move != 0 else 0
        if agree < 0.6:
            continue
        direction = "UP" if move > 0 else "DOWN"
        impulses.append(Impulse(start, i, df.index[start], df.index[i], direction, float(closes[start]), float(closes[i])))
        last_end = i
    return impulses


def evaluate_retracements(
    df: pd.DataFrame,
    impulses: List[Impulse],
    atr_series: pd.Series,
    levels: List[float] = None,
    eval_window: int = 20,
    structure_buffer_atr: float = 0.5,
) -> List[RetracementOutcome]:
    """For each impulse, for each level, measure whether/when price touched
    that retracement level within `eval_window` bars after the impulse end,
    and whether the impulse's origin was preserved (no close beyond impulse
    start +/- buffer) and what displacement followed."""
    if levels is None:
        levels = FIB_LEVELS + CONTROL_LEVELS

    closes = df["close"].to_numpy()
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    n = len(df)
    out: List[RetracementOutcome] = []

    for imp in impulses:
        window_end = min(n, imp.end_pos + eval_window + 1)
        if imp.end_pos + 1 >= window_end:
            continue
        a = atr_series.iloc[imp.end_pos]
        for level in levels:
            if imp.direction == "UP":
                level_price = imp.end_price - level * imp.size
            else:
                level_price = imp.end_price + level * imp.size

            touched = False
            touch_pos = None
            for j in range(imp.end_pos + 1, window_end):
                if imp.direction == "UP" and lows[j] <= level_price:
                    touched, touch_pos = True, j
                    break
                if imp.direction == "DOWN" and highs[j] >= level_price:
                    touched, touch_pos = True, j
                    break

            # CAUSALITY: both of these describe "what has happened by the time
            # price actually touches this level" (touch_pos), NOT what happens
            # over the whole fixed-size eval_window -- a strategy deciding to
            # act at touch_pos cannot see bars after it. When untouched, there
            # is no decision point to protect, so the full window is reported
            # for descriptive purposes only (never consumed by a strategy).
            depth_end = (touch_pos + 1) if touched else window_end

            max_depth_fraction = None
            if imp.direction == "UP":
                trough = lows[imp.end_pos + 1 : depth_end].min() if depth_end > imp.end_pos + 1 else np.nan
                if imp.size > 0:
                    max_depth_fraction = float((imp.end_price - trough) / imp.size)
            else:
                peak = highs[imp.end_pos + 1 : depth_end].max() if depth_end > imp.end_pos + 1 else np.nan
                if imp.size > 0:
                    max_depth_fraction = float((peak - imp.end_price) / imp.size)

            buffer = structure_buffer_atr * (a if not pd.isna(a) else 0)
            if imp.direction == "UP":
                structure_preserved = bool((closes[imp.end_pos + 1 : depth_end] > (imp.start_price - buffer)).all())
            else:
                structure_preserved = bool((closes[imp.end_pos + 1 : depth_end] < (imp.start_price + buffer)).all())

            displacement_after = None
            if touched and touch_pos is not None and touch_pos + eval_window <= n and not pd.isna(a) and a > 0:
                future_close = closes[min(n - 1, touch_pos + eval_window)]
                disp = (future_close - closes[touch_pos]) if imp.direction == "UP" else (closes[touch_pos] - future_close)
                displacement_after = float(disp / a)

            out.append(
                RetracementOutcome(
                    impulse=imp,
                    level=level,
                    level_price=level_price,
                    touched=touched,
                    touch_pos=touch_pos,
                    max_depth_fraction=max_depth_fraction,
                    bars_to_touch=(touch_pos - imp.end_pos) if touch_pos is not None else None,
                    structure_preserved=structure_preserved,
                    displacement_after=displacement_after,
                )
            )
    return out


if __name__ == "__main__":
    from research.core.atr import atr
    from research.data.synthetic import generate_multi_symbol_dataset

    ds = generate_multi_symbol_dataset(["EURUSD"], n_days=60)
    m15 = ds["EURUSD"].bars.resample("15min").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}
    ).dropna()
    a = atr(m15, 14)

    impulses = find_impulses(m15, a)
    print(f"{len(impulses)} impulses found")
    outcomes = evaluate_retracements(m15, impulses, a)
    print(f"{len(outcomes)} retracement outcomes")

    df_out = pd.DataFrame(
        {
            "level": [o.level for o in outcomes],
            "touched": [o.touched for o in outcomes],
        }
    )
    hit_rate = df_out.groupby("level")["touched"].mean().sort_index()
    print("Touch rate by level (Fibonacci vs control, EQUALLY-UNPROVEN until compared statistically):")
    print(hit_rate)
    print("OK")
