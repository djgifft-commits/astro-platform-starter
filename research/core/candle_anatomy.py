"""
Phase 6 — Candlestick intelligence.

Deterministic OHLC geometry features + pattern recognizer. Patterns are
FEATURES, not signals — see RESEARCH_CARDS.md card J: academic evidence on
candlestick profitability is mixed and market-inconsistent, so nothing
here is treated as a standalone entry trigger. Strategy modules must test
pattern + context combinations explicitly (Phase 20 ablation).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from research.core.atr import atr


def compute_anatomy(df: pd.DataFrame, atr_period: int = 14) -> pd.DataFrame:
    o, h, l, c = df["open"], df["high"], df["low"], df["close"]
    rng = (h - l).replace(0, np.nan)

    body = (c - o).abs()
    upper_wick = h - pd.concat([o, c], axis=1).max(axis=1)
    lower_wick = pd.concat([o, c], axis=1).min(axis=1) - l
    direction = np.sign(c - o)

    close_location = ((c - l) / rng).fillna(0.5)  # 0 = at low, 1 = at high
    open_location = ((o - l) / rng).fillna(0.5)

    prev_close = c.shift(1)
    gap = (o - prev_close)

    a = atr(df, atr_period)

    out = pd.DataFrame(
        {
            "body": body,
            "range": (h - l),
            "upper_wick": upper_wick,
            "lower_wick": lower_wick,
            "direction": direction,
            "body_to_range": (body / rng).fillna(0.0),
            "wick_to_body": (upper_wick + lower_wick) / body.replace(0, np.nan),
            "wick_asymmetry": (upper_wick - lower_wick) / rng.replace(0, np.nan),
            "close_location": close_location,
            "open_location": open_location,
            "gap": gap,
            "atr_normalized_range": ((h - l) / a).rename("atr_normalized_range"),
        },
        index=df.index,
    )
    out["wick_to_body"] = out["wick_to_body"].fillna(np.inf)
    return out


def _shift_bool(cond: pd.Series, n: int) -> pd.Series:
    return cond.shift(n).fillna(False).astype(bool)


def recognize_patterns(df: pd.DataFrame, anatomy: pd.DataFrame | None = None) -> pd.DataFrame:
    """Deterministic, threshold-based pattern flags. Every pattern is
    computed only from bars <= current index (single/two/three-bar
    patterns look strictly backward), so this is causal by construction."""
    if anatomy is None:
        anatomy = compute_anatomy(df)

    o, h, l, c = df["open"], df["high"], df["low"], df["close"]
    body = anatomy["body"]
    rng = anatomy["range"].replace(0, np.nan)
    uw = anatomy["upper_wick"]
    lw = anatomy["lower_wick"]
    body_ratio = anatomy["body_to_range"]
    bullish = c > o
    bearish = c < o

    patterns = pd.DataFrame(index=df.index)

    small_body = body_ratio < 0.10
    patterns["doji"] = small_body
    patterns["dragonfly_doji"] = small_body & (lw > 2 * body.replace(0, 1e-12)) & (uw < 0.1 * rng)
    patterns["gravestone_doji"] = small_body & (uw > 2 * body.replace(0, 1e-12)) & (lw < 0.1 * rng)
    patterns["long_legged_doji"] = small_body & (uw > 0.3 * rng) & (lw > 0.3 * rng)

    long_lower = lw >= 2 * body
    long_upper = uw >= 2 * body
    small_upper = uw <= 0.25 * body.replace(0, np.nan).fillna(1e-12)
    small_lower = lw <= 0.25 * body.replace(0, np.nan).fillna(1e-12)

    patterns["hammer"] = long_lower & small_upper & (body_ratio < 0.4) & bullish
    patterns["hanging_man"] = long_lower & small_upper & (body_ratio < 0.4) & bearish
    patterns["inverted_hammer"] = long_upper & small_lower & (body_ratio < 0.4) & bullish
    patterns["shooting_star"] = long_upper & small_lower & (body_ratio < 0.4) & bearish

    patterns["marubozu"] = (body_ratio > 0.90)
    patterns["spinning_top"] = (body_ratio.between(0.10, 0.35)) & (uw > 0.2 * rng) & (lw > 0.2 * rng)

    prev_o, prev_c = o.shift(1), c.shift(1)
    prev_bullish = _shift_bool(bullish, 1)
    prev_bearish = _shift_bool(bearish, 1)

    patterns["bullish_engulfing"] = bullish & prev_bearish & (o <= prev_c) & (c >= prev_o)
    patterns["bearish_engulfing"] = bearish & prev_bullish & (o >= prev_c) & (c <= prev_o)

    prev_high, prev_low = h.shift(1), l.shift(1)
    patterns["inside_bar"] = (h <= prev_high) & (l >= prev_low)
    patterns["outside_bar"] = (h >= prev_high) & (l <= prev_low)

    inside_body = pd.concat([o, c], axis=1).max(axis=1) <= pd.concat([prev_o, prev_c], axis=1).max(axis=1)
    inside_body &= pd.concat([o, c], axis=1).min(axis=1) >= pd.concat([prev_o, prev_c], axis=1).min(axis=1)
    patterns["harami"] = inside_body & (prev_bullish != bullish)

    patterns["pin_bar"] = (long_lower & small_upper | long_upper & small_lower) & (body_ratio < 0.30)

    o2, c2 = o.shift(2), c.shift(2)
    o1, c1 = o.shift(1), c.shift(1)
    mid1 = (o1 + c1) / 2.0
    small_mid = (c1 - o1).abs() < 0.4 * (c2 - o2).abs().replace(0, np.nan)
    patterns["morning_star"] = (
        _shift_bool(bearish, 2)
        & small_mid.fillna(False)
        & bullish
        & (c > mid1)
    )
    patterns["evening_star"] = (
        _shift_bool(bullish, 2)
        & small_mid.fillna(False)
        & bearish
        & (c < mid1)
    )

    up1, up2, up3 = bullish, _shift_bool(bullish, 1), _shift_bool(bullish, 2)
    higher_closes = (c > c1) & (c1 > c2)
    patterns["three_white_soldiers"] = up1 & up2 & up3 & higher_closes & (body_ratio > 0.5)

    dn1, dn2, dn3 = bearish, _shift_bool(bearish, 1), _shift_bool(bearish, 2)
    lower_closes = (c < c1) & (c1 < c2)
    patterns["three_black_crows"] = dn1 & dn2 & dn3 & lower_closes & (body_ratio > 0.5)

    return patterns.fillna(False)


if __name__ == "__main__":
    from research.data.synthetic import generate_multi_symbol_dataset

    ds = generate_multi_symbol_dataset(["EURUSD"], n_days=20)
    m5 = ds["EURUSD"].bars.resample("5min").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}
    ).dropna()
    anatomy = compute_anatomy(m5)
    patterns = recognize_patterns(m5, anatomy)
    print(anatomy.describe().T[["mean", "min", "max"]])
    print(patterns.sum().sort_values(ascending=False))
    assert (anatomy["body_to_range"].dropna() <= 1.0001).all()
    assert (anatomy["body_to_range"].dropna() >= -0.0001).all()
    print("OK")
