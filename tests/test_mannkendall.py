"""Mann-Kendall and Sen's slope, including how badly they behave on
autocorrelated data if left uncorrected."""

from __future__ import annotations

import numpy as np
import pytest

from ntgw.trends.mannkendall import (
    classic_variance,
    kendall_s,
    mann_kendall,
    sens_slope,
)


def _ar1(n: int, phi: float, rng) -> np.ndarray:
    e = rng.normal(0, 1, n)
    x = np.zeros(n)
    for i in range(1, n):
        x[i] = phi * x[i - 1] + e[i]
    return x


def test_s_statistic_on_monotonic_series():
    n = 10
    assert kendall_s(np.arange(n, dtype=float)) == n * (n - 1) / 2
    assert kendall_s(np.arange(n, 0, -1, dtype=float)) == -n * (n - 1) / 2


def test_s_statistic_is_zero_for_all_ties():
    assert kendall_s(np.full(8, 3.0)) == 0.0


def test_tie_correction_reduces_variance():
    distinct = np.arange(20, dtype=float)
    tied = np.repeat(np.arange(5, dtype=float), 4)
    assert classic_variance(tied) < classic_variance(distinct)


def test_sens_slope_recovers_a_known_slope():
    t = np.arange(100, dtype=float)
    x = 5.0 + 0.37 * t
    slope, lower, upper = sens_slope(x, t)
    assert slope == pytest.approx(0.37, abs=1e-9)
    assert lower <= slope <= upper


def test_sens_slope_is_robust_to_outliers():
    """A least-squares fit would move; the median of pairwise slopes should not."""
    t = np.arange(60, dtype=float)
    x = 10.0 + 0.2 * t
    contaminated = x.copy()
    contaminated[[5, 17, 40]] += 50.0
    assert sens_slope(contaminated, t)[0] == pytest.approx(0.2, abs=0.02)


def test_sens_slope_handles_uneven_time_spacing():
    t = np.array([0.0, 0.5, 3.0, 3.25, 9.0, 14.5])
    x = 100.0 - 0.4 * t
    assert sens_slope(x, t)[0] == pytest.approx(-0.4, abs=1e-9)


def test_detects_a_real_trend():
    rng = np.random.default_rng(0)
    x = np.arange(80) * 0.05 + rng.normal(0, 0.1, 80)
    result = mann_kendall(x)
    assert result.direction == "increasing"
    assert result.p_value < 0.01


def test_reports_no_trend_on_white_noise():
    rng = np.random.default_rng(5)
    result = mann_kendall(rng.normal(0, 1, 120))
    assert result.direction == "no_trend"


def test_rejects_nan():
    with pytest.raises(ValueError, match="NaN"):
        mann_kendall(np.array([1.0, np.nan, 3.0, 4.0]))


def test_rejects_too_few_points():
    with pytest.raises(ValueError, match="at least 3"):
        mann_kendall(np.array([1.0, 2.0]))


def test_autocorrelation_inflates_variance_and_lowers_effective_n():
    rng = np.random.default_rng(12)
    x = _ar1(200, 0.85, rng)
    classic = mann_kendall(x, variance_method="classic")
    corrected = mann_kendall(x, variance_method="hamed_rao")
    assert corrected.var_s > classic.var_s
    assert corrected.autocorrelation_factor > 1.0
    assert corrected.effective_n < corrected.n
    assert abs(corrected.z) < abs(classic.z)


@pytest.mark.slow
def test_false_positive_rate_is_reduced_but_not_eliminated():
    """The honest bound on what the correction buys.

    On strongly autocorrelated trendless series the uncorrected test rejects
    far more often than its nominal 5%. Hamed & Rao cuts that substantially but
    does not reach nominal - a documented limitation of the method, not a bug
    here. This test pins both halves of that claim so neither is quietly lost:
    if a future change makes the correction look perfect, it is wrong.
    """
    rng = np.random.default_rng(99)
    trials, n, phi = 200, 120, 0.85
    classic_fp = corrected_fp = 0
    for _ in range(trials):
        x = _ar1(n, phi, rng)
        classic_fp += mann_kendall(x, variance_method="classic").significant
        corrected_fp += mann_kendall(x, variance_method="hamed_rao").significant

    classic_rate = classic_fp / trials
    corrected_rate = corrected_fp / trials

    assert classic_rate > 0.30, f"uncorrected MK should over-reject badly, got {classic_rate:.1%}"
    assert corrected_rate < classic_rate * 0.75, "correction should materially reduce rejections"
    assert corrected_rate > 0.05, (
        f"corrected rate {corrected_rate:.1%} is at or below nominal - that is not what "
        "Hamed & Rao achieves at this autocorrelation, so something is wrong"
    )
