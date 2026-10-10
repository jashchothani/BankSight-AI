"""
src/backtest.py

Reconstructed from the calling contract used throughout the
BankSight-AI-analysis-reproducibility-package (run_train.py, compute_stats.py,
compute_stats2.py, compute_stats3_bugfix.py). This file is NOT present in
either of the two files that were uploaded (the reproducibility package or the
LaTeX-source zip) -- only scripts that `from src.backtest import ...` it. The
functions below implement exactly the signatures and return shapes those
scripts assume, and the fold-boundary / baseline semantics the paper describes
in Sections V, VI-C, and VIII-D/G.

NOT included here, because the reproducibility scripts implement them
locally rather than importing them from this module (contrary to some of the
paper's prose, e.g. Section VIII-H's "We extend src/backtest.py..."):
  - the Diebold-Mariano / Clark-West loss-comparison tests
  - the cost-adjusted long/short/flat backtest + Sharpe/Sortino/MaxDD/Calmar
  - the hyperparameter sweep and bank-cluster bootstrap
  - get_nse_session_dates() / generate_fold_table() (Table 4) and the
    test_fold_table_matches_real_nse_calendar test referenced in Section IX --
    no such functions or test file appear anywhere in the uploaded materials.
"""
import numpy as np


def generate_walk_forward_folds(dates, train_min_days=504, step=252, embargo_days=7):
    """
    Rolling-origin (walk-forward) fold generator (Section VI-C).

    Parameters
    ----------
    dates : 1-D array-like of sorted, unique trading dates.
    train_min_days : int
        Number of sessions in the initial training window before the first
        fold is evaluated (paper default: 504, ~2 years).
    step : int
        Number of sessions the test window advances at each fold
        (paper default: 252, ~1 year).
    embargo_days : int
        Purge/embargo gap, in sessions, enforced between the end of the
        training window and the start of the test window (paper default: 7,
        the longest forecast horizon), so that no training row's
        forward-looking target can reach into the following out-of-sample
        window.

    Returns
    -------
    list[dict] -- one entry per fold, each with:
        train_end_idx  : exclusive end index of the training window
                          (train = dates[:train_end_idx])
        test_start_idx : start index of the test window
        test_end_idx   : exclusive end index of the test window
                          (test = dates[test_start_idx:test_end_idx])

    Invariants asserted for every fold (mirrors the paper's description of
    generate_walk_forward_folds asserting max(train) < min(test) and an
    index-level gap >= embargo_days):
        dates[train_end_idx - 1] < dates[test_start_idx]
        test_start_idx - train_end_idx >= embargo_days
    """
    dates = np.asarray(dates)
    n = len(dates)
    folds = []
    test_start_idx = train_min_days
    while test_start_idx < n:
        test_end_idx = min(test_start_idx + step, n)
        train_end_idx = test_start_idx - embargo_days
        if train_end_idx <= 0:
            test_start_idx += step
            continue
        assert dates[train_end_idx - 1] < dates[test_start_idx], (
            "purge/embargo violation: training window reaches into test window"
        )
        assert (test_start_idx - train_end_idx) >= embargo_days, (
            "purge/embargo violation: gap smaller than embargo_days"
        )
        folds.append({
            "train_end_idx": int(train_end_idx),
            "test_start_idx": int(test_start_idx),
            "test_end_idx": int(test_end_idx),
        })
        test_start_idx += step
    return folds


def naive_baselines(y_true):
    """
    Naive directional-accuracy baselines for a continuous return series
    (Section VIII-B/D).

    Returns
    -------
    dict with keys:
        always_up     : accuracy of a constant "return will be positive" call
        always_down   : accuracy of a constant "return will be negative" call
        previous_sign : accuracy of predicting sign(y_true[t]) == sign(y_true[t-1]),
                         np.nan if fewer than 2 observations

    NOTE (see compute_stats3_bugfix.py): previous_sign compares each row only
    to the row immediately before it *in the array as passed in*. If the
    array is not sorted by (symbol, date) -- e.g. it is still in
    fold-construction order, where consecutive rows can be different banks on
    the same trading day -- this measures same-day cross-bank sign agreement,
    not genuine next-day persistence, and at h > 1 it is additionally
    inflated by the mechanical overlap between consecutive h-day windows
    (Section VIII-D). Callers are responsible for sorting by (symbol, date)
    and/or de-overlapping (keeping every h-th row per symbol) before calling
    this function if they want the corrected figures reported in the paper.
    """
    y_true = np.asarray(y_true, dtype=float)
    n = len(y_true)
    always_up = float(np.mean(y_true > 0)) if n else float("nan")
    always_down = float(np.mean(y_true < 0)) if n else float("nan")
    if n < 2:
        previous_sign = float("nan")
    else:
        prev_sign = np.sign(y_true[:-1])
        curr_sign = np.sign(y_true[1:])
        previous_sign = float(np.mean(prev_sign == curr_sign))
    return {
        "always_up": always_up,
        "always_down": always_down,
        "previous_sign": previous_sign,
    }


def excess_directional_accuracy(dir_acc, y_true):
    """
    Compares a model's pooled directional accuracy against the best-fitting
    (highest-accuracy) naive baseline for the same series (Table 6/10).

    Returns
    -------
    dict with keys: best_baseline_name, best_baseline, excess_accuracy
    """
    baselines = naive_baselines(y_true)
    valid = {k: v for k, v in baselines.items() if not np.isnan(v)}
    if not valid:
        return {"best_baseline_name": None, "best_baseline": float("nan"),
                "excess_accuracy": float("nan")}
    best_name = max(valid, key=valid.get)
    best_val = valid[best_name]
    return {
        "best_baseline_name": best_name,
        "best_baseline": best_val,
        "excess_accuracy": float(dir_acc - best_val),
    }


def block_bootstrap_ci(y_true, y_pred, block_size=20, n_boot=2000, random_state=42, ci=0.95):
    """
    Moving-block bootstrap confidence interval on directional accuracy
    (Section VIII-G, Table 10), preserving short-range serial dependence by
    resampling contiguous blocks rather than individual rows.

    Returns
    -------
    (point_estimate, ci_low, ci_high)
    """
    y_true = np.asarray(y_true)
    y_pred = np.asarray(y_pred)
    correct = (np.sign(y_true) == np.sign(y_pred)).astype(float)
    n = len(correct)
    if n == 0:
        return float("nan"), float("nan"), float("nan")
    point = float(correct.mean())
    rng = np.random.default_rng(random_state)
    n_blocks = int(np.ceil(n / block_size))
    boot = np.empty(n_boot)
    for b in range(n_boot):
        starts = rng.integers(0, max(1, n - block_size + 1), size=n_blocks)
        sample = np.concatenate([correct[s:s + block_size] for s in starts])[:n]
        boot[b] = sample.mean()
    alpha = (1 - ci) / 2
    lo, hi = np.quantile(boot, [alpha, 1 - alpha])
    return point, float(lo), float(hi)