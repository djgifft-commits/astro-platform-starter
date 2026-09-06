"""
Phase 21 — Statistical validation.

Implements: chronological train/validation/test splitting, walk-forward
folds, bootstrap confidence intervals, a permutation-based negative
control, Benjamini-Hochberg false-discovery-rate correction across the
full set of tested cells, and a verdict labeler that a result must earn
rather than be assumed to deserve.

RESEARCH_CARDS.md card T (Bailey & Lopez de Prado, 2014) is the basis for
BH-FDR correction across every strategy x regime x entry x exit cell
tested -- this project logs every cell it runs (see
research/run_experiments.py), not just the ones that looked good, so the
correction's trial count is honest.
"""
from __future__ import annotations

import dataclasses
from typing import Callable, Dict, List, Tuple

import numpy as np
import pandas as pd

from research.risk.exit_models import TradeResult

MIN_SAMPLE_FOR_ANY_VERDICT = 30
MIN_SAMPLE_FOR_ROBUST = 100


def chronological_split(trades: List[TradeResult], train_frac: float = 0.5, val_frac: float = 0.25):
    ordered = sorted(trades, key=lambda t: t.entry_ts)
    n = len(ordered)
    n_train = int(n * train_frac)
    n_val = int(n * val_frac)
    return ordered[:n_train], ordered[n_train:n_train + n_val], ordered[n_train + n_val:]


def walk_forward_folds(trades: List[TradeResult], n_folds: int = 5) -> List[Tuple[List[TradeResult], List[TradeResult]]]:
    """Expanding-window walk-forward: fold k tests on the k-th contiguous
    chronological block using everything before it as the (unused, in this
    project's non-parametric strategies) training context. Since none of
    this project's strategies optimize parameters on a training fold, this
    reports each block's OUT-OF-SAMPLE-RELATIVE-TO-EARLIER-DATA performance
    dispersion across folds, which is what Phase 21 asks for: "report
    walk-forward fold count and per-fold dispersion, not just the average."
    """
    ordered = sorted(trades, key=lambda t: t.entry_ts)
    n = len(ordered)
    if n < n_folds:
        return []
    fold_size = n // n_folds
    folds = []
    for k in range(n_folds):
        start = k * fold_size
        end = (k + 1) * fold_size if k < n_folds - 1 else n
        train = ordered[:start]
        test = ordered[start:end]
        if test:
            folds.append((train, test))
    return folds


@dataclasses.dataclass
class PurgedFold:
    fold_index: int
    fold_start: pd.Timestamp
    fold_end: pd.Timestamp
    train: List[TradeResult]
    test: List[TradeResult]
    n_purged: int
    n_embargoed: int


def purged_embargoed_folds(
    trades: List[TradeResult],
    n_folds: int = 5,
    embargo: pd.Timedelta = pd.Timedelta(hours=24),
) -> List[PurgedFold]:
    """Phase 8W / RESEARCH_CARDS.md purged-CV card (Lopez de Prado 2017):
    time-based (not count-based) fold boundaries; PURGE removes any
    would-be training trade whose outcome window [entry_ts, exit_ts]
    overlaps the test fold's time span; EMBARGO additionally removes
    training trades entered within `embargo` after the test fold ends.

    None of this project's strategies fit parameters on a training set
    (they are fixed, hand-specified rules), so purging/embargoing the
    TRAIN set changes nothing about what gets reported for the TEST set
    -- what it protects is the INTERPRETATION of "N independent folds":
    without it, two adjacent folds' trades can share overlapping outcome
    windows across the boundary, making them less independent evidence
    than a naive fold count implies. This function's practical output is
    therefore the purge/embargo COUNTS (a diagnostic on how much boundary
    overlap exists in the data) alongside the same per-fold test stats
    Phase 7's `walk_forward_folds` already reports.
    """
    if len(trades) < n_folds:
        return []
    ordered = sorted(trades, key=lambda t: t.entry_ts)
    start = ordered[0].entry_ts
    end = max((t.exit_ts or t.entry_ts) for t in ordered)
    if start >= end:
        return []
    edges = pd.date_range(start, end, periods=n_folds + 1)

    folds: List[PurgedFold] = []
    for i in range(n_folds):
        fold_start, fold_end = edges[i], edges[i + 1]
        test = [t for t in ordered if fold_start <= t.entry_ts < fold_end]

        would_be_train = [t for t in ordered if not (fold_start <= t.entry_ts < fold_end)]
        overlaps_test_window = lambda t: t.entry_ts < fold_end and (t.exit_ts or t.entry_ts) > fold_start
        purged = [t for t in would_be_train if overlaps_test_window(t)]
        train_after_purge = [t for t in would_be_train if not overlaps_test_window(t)]

        in_embargo = lambda t: fold_end <= t.entry_ts < (fold_end + embargo)
        embargoed = [t for t in train_after_purge if in_embargo(t)]
        train_final = [t for t in train_after_purge if not in_embargo(t)]

        folds.append(PurgedFold(
            fold_index=i, fold_start=fold_start, fold_end=fold_end,
            train=train_final, test=test, n_purged=len(purged), n_embargoed=len(embargoed),
        ))
    return folds


def bootstrap_mean_ci(values: np.ndarray, n_boot: int = 2000, alpha: float = 0.05, seed: int = 0) -> Dict[str, float]:
    if len(values) < 2:
        return {"mean": float("nan"), "ci_low": float("nan"), "ci_high": float("nan"), "excludes_zero": False}
    rng = np.random.default_rng(seed)
    boots = np.empty(n_boot)
    n = len(values)
    for i in range(n_boot):
        sample = values[rng.integers(0, n, size=n)]
        boots[i] = sample.mean()
    lo, hi = np.quantile(boots, [alpha / 2, 1 - alpha / 2])
    return {"mean": float(values.mean()), "ci_low": float(lo), "ci_high": float(hi), "excludes_zero": bool(lo > 0 or hi < 0)}


def permutation_negative_control(values: np.ndarray, n_perm: int = 2000, seed: int = 0) -> Dict[str, float]:
    """Negative control: if we randomly flip the SIGN of each trade's R
    multiple (simulating 'this strategy has no real directional
    information, only symmetric noise'), how often does the shuffled mean
    exceed the actual observed mean? A strategy with genuine information
    should clear this bar; one that doesn't is NO_INFORMATION_DEMONSTRATED
    regardless of how good the raw number looks."""
    if len(values) < 2:
        return {"observed_mean": float("nan"), "p_value": float("nan")}
    rng = np.random.default_rng(seed)
    observed = values.mean()
    signs = rng.choice([-1, 1], size=(n_perm, len(values)))
    perm_means = (signs * values).mean(axis=1)
    p_value = float((np.abs(perm_means) >= abs(observed)).mean())
    return {"observed_mean": float(observed), "p_value": p_value}


def benjamini_hochberg(pvalues: List[float], alpha: float = 0.05) -> List[bool]:
    """Returns a same-length list of booleans: True where the hypothesis
    survives BH-FDR correction at level `alpha`."""
    m = len(pvalues)
    if m == 0:
        return []
    order = np.argsort(pvalues)
    sorted_p = np.array(pvalues)[order]
    thresholds = (np.arange(1, m + 1) / m) * alpha
    passed = sorted_p <= thresholds
    if not passed.any():
        cutoff_rank = -1
    else:
        cutoff_rank = np.max(np.where(passed)[0])
    result = np.zeros(m, dtype=bool)
    if cutoff_rank >= 0:
        result[order[: cutoff_rank + 1]] = True
    return result.tolist()


@dataclasses.dataclass
class ValidationVerdict:
    verdict: str
    n: int
    reasons: List[str]


def label_verdict(
    n: int,
    ci: Dict[str, float],
    permutation: Dict[str, float],
    walk_forward_fold_stats: List[Dict[str, float]],
    bh_survives: bool,
    alpha: float = 0.05,
) -> ValidationVerdict:
    reasons = []
    if n < MIN_SAMPLE_FOR_ANY_VERDICT:
        return ValidationVerdict("INSUFFICIENT_SAMPLE", n, [f"n={n} < minimum {MIN_SAMPLE_FOR_ANY_VERDICT}"])

    if not ci.get("excludes_zero", False):
        reasons.append("bootstrap CI for mean R includes zero")
        return ValidationVerdict("NO_INFORMATION_DEMONSTRATED", n, reasons)

    if permutation.get("p_value", 1.0) > alpha:
        reasons.append(f"permutation negative control p={permutation.get('p_value'):.3f} > {alpha}")
        return ValidationVerdict("NO_INFORMATION_DEMONSTRATED", n, reasons)

    if not bh_survives:
        reasons.append("does not survive Benjamini-Hochberg correction across all tested cells")
        return ValidationVerdict("INFORMATION_PRESENT", n, reasons)

    fold_means = [f["expectancy_r"] for f in walk_forward_fold_stats if f.get("n", 0) > 0]
    positive_folds = sum(1 for m in fold_means if m > 0)
    if len(fold_means) < 3:
        reasons.append(f"only {len(fold_means)} walk-forward folds with trades (need >=3 for robustness claim)")
        return ValidationVerdict("INFORMATION_PRESENT", n, reasons)

    if positive_folds / len(fold_means) < 0.6 or n < MIN_SAMPLE_FOR_ROBUST:
        reasons.append(f"{positive_folds}/{len(fold_means)} folds positive, n={n} (robust threshold n>={MIN_SAMPLE_FOR_ROBUST})")
        return ValidationVerdict("INFORMATION_PRESENT_BUT_NOT_ROBUST", n, reasons)

    reasons.append(f"CI excludes zero, survives permutation control (p={permutation['p_value']:.3f}) and BH-FDR, "
                    f"{positive_folds}/{len(fold_means)} walk-forward folds positive, n={n}")
    return ValidationVerdict("EDGE_ESTABLISHED", n, reasons)
