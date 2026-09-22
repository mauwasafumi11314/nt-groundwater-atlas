"""Mann-Kendall trend test and Sen's slope, implemented here rather than taken
from a dependency.

Groundwater hydrographs are strongly autocorrelated: consecutive monthly
readings are not independent draws. The textbook Mann-Kendall variance assumes
independence, and applying it to a monthly hydrograph inflates the test
statistic and reports significant trends almost everywhere. The default here is
therefore the Hamed & Rao (1998) variance correction, which rescales Var(S) by
the effective sample size implied by the rank autocorrelation.

The correction reduces the problem without removing it. On trendless AR(1)
series with phi=0.85 the uncorrected test rejects at roughly 51% against a
nominal 5%; corrected, that falls to about 13% at n=120 and 7% at n=240. A
p-value from a strongly autocorrelated hydrograph is therefore still optimistic,
which is why `autocorrelation_factor` and `effective_n` are carried into the
trend table rather than discarded - the phase-3 confidence layer needs them.

References
----------
Mann (1945); Kendall (1975); Sen (1968) for the slope estimator;
Hamed & Rao (1998) for the autocorrelation-corrected variance.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
from scipy import stats

VarianceMethod = Literal["classic", "hamed_rao"]


@dataclass(frozen=True)
class MannKendallResult:
    """Outcome of a Mann-Kendall test.

    `direction` is the direction of the tested series. Callers working in
    depth-to-water must flip it to reason about head - see `ntgw.trends.runner`.

    `effective_n` is n divided by the variance inflation factor: the number of
    independent observations this series is worth. It is carried through to the
    trend table so the phase-3 confidence layer can downweight hydrographs whose
    p-value rests on very few effective degrees of freedom.
    """

    n: int
    s: float
    var_s: float
    z: float
    p_value: float
    tau: float
    variance_method: VarianceMethod
    autocorrelation_factor: float
    effective_n: float
    significant: bool
    direction: Literal["increasing", "decreasing", "no_trend"]


def _tie_correction(values: np.ndarray) -> float:
    """sum over tie groups of t(t-1)(2t+5)."""
    _, counts = np.unique(values, return_counts=True)
    tied = counts[counts > 1].astype(float)
    return float(np.sum(tied * (tied - 1.0) * (2.0 * tied + 5.0)))


def kendall_s(x: np.ndarray) -> float:
    """The Mann-Kendall S statistic: sum of sign(x_j - x_i) over all i < j."""
    n = x.size
    idx_i, idx_j = np.triu_indices(n, k=1)
    return float(np.sum(np.sign(x[idx_j] - x[idx_i])))


def classic_variance(x: np.ndarray) -> float:
    """Var(S) under independence, corrected for ties in the data."""
    n = float(x.size)
    return (n * (n - 1.0) * (2.0 * n + 5.0) - _tie_correction(x)) / 18.0


def hamed_rao_factor(x: np.ndarray, slope: float, alpha: float = 0.05) -> float:
    """Variance inflation factor n/n* from rank autocorrelation.

    The series is first detrended with `slope` so that the trend itself does not
    masquerade as autocorrelation. Only autocorrelations significant at `alpha`
    contribute, per Hamed & Rao.
    """
    n = x.size
    if n < 4:
        return 1.0

    t = np.arange(n, dtype=float)
    detrended = x - slope * t
    ranks = stats.rankdata(detrended)
    ranks = ranks - ranks.mean()

    denom = float(np.sum(ranks**2))
    if denom == 0.0:
        return 1.0

    # Autocorrelation of the detrended ranks, lags 1..n-2.
    max_lag = n - 2
    acf = np.array(
        [float(np.sum(ranks[: n - k] * ranks[k:]) / denom) for k in range(1, max_lag + 1)]
    )

    # Anderson (1942) bounds for the sample ACF of a random series, which are
    # lag-dependent; the flat +/- z/sqrt(n) bound is too lenient and measurably
    # over-rejects.
    #
    # Summation stops at the first lag that is not significant, rather than
    # running to n-2 over every significant lag. Accumulating all lags is
    # unstable: the sample ACF of a finite series turns negative at long lags,
    # and those terms carry enough weight to cancel the real short-lag
    # structure. On one AR(1) path with phi=0.85 the all-lag factor came out as
    # 2.79, 0.96 and 3.26 for n = 120, 200 and 400 - the middle one *deflating*
    # the variance of a strongly autocorrelated series. Truncating gives 5.06,
    # 5.41 and 5.53 on the same paths, and a materially better false-positive
    # rate (see tests/test_mannkendall.py).
    z = stats.norm.ppf(1.0 - alpha / 2.0)
    total = 0.0
    for k in range(1, max_lag + 1):
        span = n - k
        if span < 3:
            break
        r = acf[k - 1]
        lo = (-1.0 - z * np.sqrt(span - 1.0)) / span
        hi = (-1.0 + z * np.sqrt(span - 1.0)) / span
        if lo < r < hi:
            break
        total += span * (span - 1.0) * (span - 2.0) * r

    factor = 1.0 + (2.0 / (n * (n - 1.0) * (n - 2.0))) * total
    # A factor at or below zero is not physically meaningful; clamp to a
    # minimum that keeps the variance positive rather than silently producing
    # an infinite Z.
    return float(max(factor, 1e-6))


def sens_slope(
    x: np.ndarray, t: np.ndarray | None = None, alpha: float = 0.05
) -> tuple[float, float, float]:
    """Sen's slope with a distribution-free confidence interval.

    Returns (slope, lower, upper) in units of x per unit of t.
    """
    n = x.size
    if t is None:
        t = np.arange(n, dtype=float)

    idx_i, idx_j = np.triu_indices(n, k=1)
    dt = t[idx_j] - t[idx_i]
    valid = dt != 0
    if not np.any(valid):
        return float("nan"), float("nan"), float("nan")

    slopes = np.sort((x[idx_j] - x[idx_i])[valid] / dt[valid])
    slope = float(np.median(slopes))

    # Normal-approximation CI on the rank of the ordered slopes.
    n_slopes = slopes.size
    c_alpha = stats.norm.ppf(1.0 - alpha / 2.0) * np.sqrt(classic_variance(x))
    lower_rank = int(np.floor((n_slopes - c_alpha) / 2.0))
    upper_rank = int(np.ceil((n_slopes + c_alpha) / 2.0))
    lower_rank = min(max(lower_rank, 0), n_slopes - 1)
    upper_rank = min(max(upper_rank, 0), n_slopes - 1)
    return slope, float(slopes[lower_rank]), float(slopes[upper_rank])


def mann_kendall(
    x_in,
    alpha: float = 0.05,
    variance_method: VarianceMethod = "hamed_rao",
) -> MannKendallResult:
    """Run the Mann-Kendall test on an evenly spaced series.

    `x_in` must not contain NaN; regularise and gap-handle upstream.
    """
    x = np.asarray(x_in, dtype=float)
    if x.ndim != 1:
        raise ValueError("mann_kendall expects a 1-D series")
    if np.isnan(x).any():
        raise ValueError("mann_kendall received NaN; regularise the series first")

    n = x.size
    if n < 3:
        raise ValueError(f"mann_kendall needs at least 3 points, got {n}")

    s = kendall_s(x)
    var_s = classic_variance(x)

    factor = 1.0
    if variance_method == "hamed_rao":
        slope, _, _ = sens_slope(x)
        factor = hamed_rao_factor(x, slope, alpha=alpha)
        var_s = var_s * factor
    elif variance_method != "classic":
        raise ValueError(f"unknown variance_method {variance_method!r}")

    if var_s <= 0:
        z = 0.0
    elif s > 0:
        z = (s - 1.0) / np.sqrt(var_s)
    elif s < 0:
        z = (s + 1.0) / np.sqrt(var_s)
    else:
        z = 0.0

    p_value = float(2.0 * (1.0 - stats.norm.cdf(abs(z))))

    # Kendall's tau-b, accounting for ties in the data (time has no ties).
    n0 = n * (n - 1) / 2.0
    _, counts = np.unique(x, return_counts=True)
    tied = counts[counts > 1].astype(float)
    n1 = float(np.sum(tied * (tied - 1.0) / 2.0))
    tau_denom = np.sqrt((n0 - n1) * n0)
    tau = float(s / tau_denom) if tau_denom > 0 else 0.0

    significant = p_value < alpha
    if not significant:
        direction: Literal["increasing", "decreasing", "no_trend"] = "no_trend"
    elif s > 0:
        direction = "increasing"
    else:
        direction = "decreasing"

    return MannKendallResult(
        n=n,
        s=s,
        var_s=float(var_s),
        z=float(z),
        p_value=p_value,
        tau=tau,
        variance_method=variance_method,
        autocorrelation_factor=float(factor),
        effective_n=float(n / factor) if factor > 0 else float("nan"),
        significant=significant,
        direction=direction,
    )
