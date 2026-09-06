"""
SYNTHETIC_DATA generator.

There is no MT5, broker, or live/historical market data connection in this
project (see research/config.py DATA DISCLOSURE). This module generates a
labeled, regime-switching random-walk FX price process with session and
volatility structure, used ONLY to validate that the causal feature/
strategy/backtest ENGINE behaves correctly (no look-ahead, correct
statistics, correct exposure accounting, etc).

No result derived from this data may be interpreted as evidence about real
market behavior. Every consumer of this module must propagate that label.

Hidden "ground truth" regime segments are exposed separately
(`ground_truth_regime`) and must NEVER be fed into any causal classifier,
strategy, or backtest decision. They exist only so this project can report
a diagnostic such as "the causal regime classifier agreed with the
generating regime X% of the time" as an ENGINE VALIDATION metric.
"""
from __future__ import annotations

import dataclasses
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

from research.config import BASELINE_SPREAD_PIPS, PIP_SIZE, RANDOM_SEED, UTC

# Regime definitions: (name, mean_duration_minutes, annualized_drift, annualized_vol_mult)
# Mean durations are set in multi-day units (not hours) so that a persistent
# trend regime is long relative to typical H1-level trend-detection lookback
# windows (tens of hours) -- otherwise a causal classifier that must confirm
# persistence over ~50 H1 bars would rarely see a "clean" trend segment
# uncontaminated by a regime switch, and every trend-dependent strategy
# would starve for setups by construction of the generator, not because of
# anything about the strategy itself. This is a synthetic-data calibration
# choice (Phase 0/2 disclosure applies), not a claim about real regime
# persistence in actual FX markets.
REGIME_STATES: List[Tuple[str, float, float, float]] = [
    ("STRONG_UPTREND", 60 * 24 * 3.0, 0.45, 1.0),
    ("UP_TREND", 60 * 24 * 2.5, 0.22, 0.9),
    ("WEAK_UPTREND", 60 * 24 * 1.5, 0.08, 0.8),
    ("RANGE", 60 * 24 * 2.0, 0.0, 0.6),
    ("WEAK_DOWNTREND", 60 * 24 * 1.5, -0.08, 0.8),
    ("DOWN_TREND", 60 * 24 * 2.5, -0.22, 0.9),
    ("STRONG_DOWNTREND", 60 * 24 * 3.0, -0.45, 1.0),
    ("HIGH_VOLATILITY", 60 * 24 * 0.75, 0.0, 2.2),
]

MINUTES_PER_YEAR = 365 * 24 * 60


@dataclasses.dataclass
class SyntheticDataset:
    symbol: str
    bars: pd.DataFrame  # OHLC + spread, tz-aware UTC index, M1
    ground_truth_regime: pd.Series  # SYNTHETIC_GROUND_TRUTH_NOT_FOR_CAUSAL_USE


def _trading_minute_index(start: pd.Timestamp, n_days: int) -> pd.DatetimeIndex:
    """Weekday-only minute index (Mon 00:00 UTC - Fri 23:59 UTC each week).

    Simplification: real FX has a short weekly close/rollover; this project
    does not model that gap since it is irrelevant to the causal-engine
    questions under test here. Documented in audit report data limitations.
    """
    days = pd.bdate_range(start=start.normalize(), periods=n_days, freq="B", tz=UTC)
    idx = []
    for d in days:
        idx.append(pd.date_range(d, d + pd.Timedelta(hours=23, minutes=59), freq="min", tz=UTC))
    return pd.DatetimeIndex(np.concatenate([i.values for i in idx])).tz_localize(None).tz_localize(UTC)


def _session_vol_multiplier(idx: pd.DatetimeIndex) -> np.ndarray:
    """Approximate liquidity/volatility-by-hour curve (UTC hour bucket).

    This is a coarse generator-side approximation used only to make the
    synthetic data have plausible session structure; it is NOT the causal
    session classifier (see research/core/sessions.py), which does correct
    timezone/DST-aware session labeling on the resulting timestamps.
    """
    hour = idx.hour.values.astype(float)
    # low vol in Asia-quiet hours, ramps up London, peak London/NY overlap, tapers NY afternoon
    mult = (
        0.55
        + 0.35 * np.exp(-0.5 * ((hour - 8) / 3.0) ** 2)   # London open bump
        + 0.55 * np.exp(-0.5 * ((hour - 13.5) / 2.0) ** 2)  # London/NY overlap peak
        + 0.20 * np.exp(-0.5 * ((hour - 1) / 3.0) ** 2)    # Tokyo open bump
    )
    return mult


def _regime_path(n_minutes: int, rng: np.random.Generator) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Build a segment-wise regime path. Returns (regime_idx, drift_per_min, vol_mult)."""
    regime_idx = np.empty(n_minutes, dtype=np.int16)
    drift = np.empty(n_minutes, dtype=np.float64)
    vol = np.empty(n_minutes, dtype=np.float64)

    pos = 0
    state = rng.integers(0, len(REGIME_STATES))
    while pos < n_minutes:
        name, mean_dur, ann_drift, vol_mult = REGIME_STATES[state]
        dur = int(max(15, rng.exponential(mean_dur)))
        dur = min(dur, n_minutes - pos)
        regime_idx[pos:pos + dur] = state
        drift[pos:pos + dur] = ann_drift / MINUTES_PER_YEAR
        vol[pos:pos + dur] = vol_mult
        pos += dur
        # transition: mostly move to an "adjacent" state (mean-reverting regime chain)
        if rng.random() < 0.8:
            step = rng.choice([-2, -1, 1, 2])
            state = int(np.clip(state + step, 0, len(REGIME_STATES) - 1))
        else:
            state = int(rng.integers(0, len(REGIME_STATES)))
    return regime_idx, drift, vol


def generate_multi_symbol_dataset(
    symbols: List[str],
    n_days: int = 180,
    start: str = "2024-01-01",
    seed: int = RANDOM_SEED,
    factor_loadings: Dict[str, float] | None = None,
    base_vol_annual: float = 0.08,
) -> Dict[str, SyntheticDataset]:
    """Generate a correlated, regime-switching synthetic FX dataset.

    factor_loadings: correlation of each symbol to a shared "market factor"
    in [-1, 1]. Symbols sharing a high positive loading move together;
    negative loading moves inversely. This is a DESIGNED parameter used to
    validate hedge/correlation mechanics (Phase 13) — it is not a claim
    about real FX correlation.
    """
    if factor_loadings is None:
        factor_loadings = {s: 0.5 for s in symbols}

    rng = np.random.default_rng(seed)
    idx = _trading_minute_index(pd.Timestamp(start, tz=UTC), n_days)
    n = len(idx)

    session_mult = _session_vol_multiplier(idx)
    regime_idx, drift_per_min, regime_vol_mult = _regime_path(n, rng)
    regime_names = np.array([s[0] for s in REGIME_STATES])[regime_idx]

    common_factor = rng.standard_normal(n)

    # occasional shock events (news-like): short vol spikes + spread widening
    shock_prob = 3.0 / (60 * 24)  # ~3 shocks/day expected, arrival-only marker
    shock_mask = rng.random(n) < shock_prob
    shock_intensity = np.zeros(n)
    decay = 0.0
    intensities = rng.uniform(2.0, 5.0, size=shock_mask.sum())
    k = 0
    for i in range(n):
        if shock_mask[i]:
            decay = intensities[k]
            k += 1
        shock_intensity[i] = decay
        decay *= 0.85  # exponential decay of shock effect

    per_minute_vol_base = base_vol_annual / np.sqrt(MINUTES_PER_YEAR)

    datasets: Dict[str, SyntheticDataset] = {}
    for sym in symbols:
        loading = float(np.clip(factor_loadings.get(sym, 0.5), -1.0, 1.0))
        idio = rng.standard_normal(n)
        shock_idio = rng.standard_normal(n)

        total_vol = per_minute_vol_base * regime_vol_mult * session_mult * (1.0 + 0.6 * shock_intensity)
        shared = loading * common_factor
        indiv = np.sqrt(max(0.0, 1.0 - loading ** 2)) * idio
        shock_component = 0.5 * shock_intensity * shock_idio  # extra idiosyncratic shock noise

        log_ret = drift_per_min + total_vol * (shared + indiv) + total_vol * shock_component * 0.3

        start_price = {"EURUSD": 1.0900, "GBPUSD": 1.2700, "USDJPY": 148.00,
                        "AUDUSD": 0.6600, "USDCAD": 1.3600, "USDCHF": 0.8800,
                        "NZDUSD": 0.6100, "XAUUSD": 2050.0}.get(sym, 1.0000)
        log_price = np.log(start_price) + np.cumsum(log_ret)
        close = np.exp(log_price)
        open_ = np.empty_like(close)
        open_[0] = start_price
        open_[1:] = close[:-1]

        # intrabar wick simulation: half-normal magnitude scaled by intrabar vol
        intrabar_vol = total_vol * close
        upper_wick = np.abs(rng.standard_normal(n)) * intrabar_vol * 0.9
        lower_wick = np.abs(rng.standard_normal(n)) * intrabar_vol * 0.9
        # occasionally suppress one side to allow marubozu/doji-like bars to emerge
        suppress = rng.random(n)
        upper_wick = np.where(suppress < 0.12, upper_wick * 0.05, upper_wick)
        lower_wick = np.where((suppress >= 0.88), lower_wick * 0.05, lower_wick)

        bar_high = np.maximum(open_, close) + upper_wick
        bar_low = np.minimum(open_, close) - lower_wick
        bar_low = np.minimum(bar_low, np.minimum(open_, close))  # safety
        bar_high = np.maximum(bar_high, np.maximum(open_, close))

        pip = PIP_SIZE.get(sym, 0.0001)
        base_spread = BASELINE_SPREAD_PIPS.get(sym, 1.5) * pip
        asia_wide = np.where(session_mult < 0.75, 1.6, 1.0)
        shock_wide = 1.0 + 2.0 * shock_intensity
        spread = base_spread * asia_wide * shock_wide

        bars = pd.DataFrame(
            {
                "open": open_,
                "high": bar_high,
                "low": bar_low,
                "close": close,
                "spread": spread,
            },
            index=idx,
        )
        bars.index.name = "timestamp"

        gt = pd.Series(regime_names, index=idx, name="ground_truth_regime__SYNTHETIC_DO_NOT_USE_CAUSALLY")

        datasets[sym] = SyntheticDataset(symbol=sym, bars=bars, ground_truth_regime=gt)

    return datasets


if __name__ == "__main__":
    ds = generate_multi_symbol_dataset(["EURUSD", "GBPUSD", "USDJPY"], n_days=10)
    for sym, d in ds.items():
        print(sym, d.bars.shape, d.bars.index.min(), d.bars.index.max())
        print(d.bars.head(3))
        assert (d.bars["high"] >= d.bars[["open", "close", "low"]].max(axis=1)).all()
        assert (d.bars["low"] <= d.bars[["open", "close", "high"]].min(axis=1)).all()
    print("OK")
