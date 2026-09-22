"""Monthly regularisation and seasonal removal."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ntgw.trends.deseason import (
    deseasonalise,
    month_climatology,
    months_covered,
    to_monthly,
)
from ntgw.trends.mannkendall import sens_slope


def test_monthly_median_collapses_multiple_readings():
    ts = pd.to_datetime(["2020-03-02", "2020-03-15", "2020-03-28", "2020-04-10"])
    monthly = to_monthly(ts, [10.0, 12.0, 100.0, 5.0])
    assert monthly.values.iloc[0] == 12.0  # median, not mean: outlier ignored
    assert monthly.n_observations == 4


def test_gaps_are_preserved_not_interpolated():
    ts = pd.to_datetime(["2020-01-15", "2020-06-15"])
    monthly = to_monthly(ts, [1.0, 2.0])
    assert monthly.n_months_total == 6
    assert monthly.n_months_present == 2
    assert monthly.values.isna().sum() == 4
    assert monthly.longest_gap_months == 4
    assert monthly.gap_fraction == pytest.approx(4 / 6)


def test_empty_input_is_handled():
    monthly = to_monthly([], [])
    assert monthly.n_observations == 0
    assert monthly.gap_fraction == 1.0


def test_climatology_indexes_all_twelve_months():
    idx = pd.date_range("2015-01-01", periods=36, freq="MS")
    clim = month_climatology(pd.Series(np.arange(36.0), index=idx))
    assert list(clim.index) == list(range(1, 13))


def test_months_covered_counts_distinct_calendar_months():
    idx = pd.date_range("2015-01-01", periods=5, freq="MS")
    assert months_covered(pd.Series(np.ones(5), index=idx)) == 5


def test_two_pass_removes_sawtooth():
    """Estimating the climatology from a trending series leaks the trend into it.

    Per-month medians of a trending series sit at each month's own position in
    the record, so subtracting them reintroduces a sawtooth of amplitude
    ~ slope x 11 months. At 0.05 m/month that artifact has a standard deviation
    of about 0.17 m - comparable to the signal. The two-pass estimate must
    remove the season without leaving it behind.
    """
    idx = pd.date_range("2010-01-01", periods=120, freq="MS")
    t = np.arange(120.0)
    true_slope = -0.05
    values = 100.0 + true_slope * t + 2.0 * np.sin(2 * np.pi * idx.month / 12.0)
    series = to_monthly(idx, values).values

    deseasonalised, _ = deseasonalise(series)
    residual = deseasonalised.to_numpy() - true_slope * t

    assert residual.std() < 0.01, f"seasonal artifact remains: std {residual.std():.4f}"
    assert sens_slope(deseasonalised.to_numpy())[0] == pytest.approx(true_slope, abs=1e-6)


def test_deseasonalising_does_not_change_the_slope():
    idx = pd.date_range("2010-01-01", periods=144, freq="MS")
    rng = np.random.default_rng(4)
    t = np.arange(144.0)
    values = 50.0 - 0.02 * t + 3.0 * np.sin(2 * np.pi * idx.month / 12.0) + rng.normal(0, 0.05, 144)
    series = to_monthly(idx, values).values
    before = sens_slope(series.to_numpy())[0]
    after = sens_slope(deseasonalise(series)[0].to_numpy())[0]
    assert after == pytest.approx(before, abs=0.005)


def test_purely_seasonal_series_has_no_trend_after_deseasonalising():
    idx = pd.date_range("2010-01-01", periods=120, freq="MS")
    values = 330.0 + 4.0 * np.sin(2 * np.pi * idx.month / 12.0)
    series = to_monthly(idx, values).values
    deseasonalised, _ = deseasonalise(series)
    assert abs(sens_slope(deseasonalised.to_numpy())[0]) < 1e-6
