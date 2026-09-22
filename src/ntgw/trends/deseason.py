"""Regularisation to a monthly step and removal of the seasonal signal.

Nothing here fabricates an observation. Months with no reading stay missing:
interpolating across them would manufacture the very data the project is meant
to be honest about lacking. Downstream code drops the missing months and keeps
the real timestamps, so Sen's slope is computed against elapsed time rather
than against a position in an assumed-regular sequence.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

#: Months of the year that must be represented before a climatology is
#: considered estimable at all.
MIN_MONTHS_FOR_CLIMATOLOGY = 8


@dataclass(frozen=True)
class MonthlySeries:
    """A bore hydrograph on a regular monthly index, gaps included as NaN."""

    values: pd.Series  # indexed by month-start Timestamp, may contain NaN
    n_observations: int  # raw readings that went in
    n_months_present: int
    n_months_total: int

    @property
    def gap_fraction(self) -> float:
        if self.n_months_total == 0:
            return 1.0
        return 1.0 - (self.n_months_present / self.n_months_total)

    @property
    def span_years(self) -> float:
        if self.n_months_total <= 1:
            return 0.0
        return (self.n_months_total - 1) / 12.0

    @property
    def longest_gap_months(self) -> int:
        present = self.values.notna().to_numpy()
        longest = run = 0
        for ok in present:
            run = 0 if ok else run + 1
            longest = max(longest, run)
        return longest


def to_monthly(timestamps, values) -> MonthlySeries:
    """Collapse irregular readings onto a regular monthly index by median.

    The median (not the mean) so that a single spurious reading in a month does
    not drag the monthly value.
    """
    ts = pd.to_datetime(pd.Series(list(timestamps)), errors="raise")
    vals = pd.Series(np.asarray(values, dtype=float))
    frame = pd.DataFrame({"ts": ts, "value": vals}).dropna(subset=["value"])
    if frame.empty:
        empty = pd.Series(dtype=float)
        return MonthlySeries(empty, 0, 0, 0)

    frame["month"] = frame["ts"].dt.to_period("M")
    monthly = frame.groupby("month")["value"].median()

    full_index = pd.period_range(monthly.index.min(), monthly.index.max(), freq="M")
    monthly = monthly.reindex(full_index)
    monthly.index = monthly.index.to_timestamp()

    return MonthlySeries(
        values=monthly,
        n_observations=int(len(frame)),
        n_months_present=int(monthly.notna().sum()),
        n_months_total=int(len(monthly)),
    )


def month_climatology(series: pd.Series) -> pd.Series:
    """Median value per calendar month, over whatever years are present.

    Returned indexed 1..12; months never observed are NaN.
    """
    observed = series.dropna()
    if observed.empty:
        return pd.Series(np.nan, index=range(1, 13), dtype=float)
    by_month = observed.groupby(observed.index.month).median()
    return by_month.reindex(range(1, 13))


def deseasonalise(series: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Subtract the month-of-year climatology from `series`, in two passes.

    Returns (deseasonalised, climatology).

    The climatology is estimated from a *detrended* copy of the series, not
    from the series itself. Taking per-month medians of a trending series lets
    the trend leak into the seasonal estimate: each calendar month's median
    lands at that month's own position in the record, and subtracting it
    reintroduces a sawtooth of amplitude ~ slope x 11 months. With a 0.05 m/mo
    trend that artifact has a standard deviation of 0.17 m - the same order as
    the signal being measured. Detrending first removes it completely
    (tests/test_deseason.py::test_two_pass_removes_sawtooth).

    Subtracting a per-month constant leaves the long-term slope unchanged, so
    Sen's slope on the result is still in the original units per unit time.

    A month whose climatology could not be estimated keeps its original value;
    it is the sufficiency rules, not this function, that decide whether such a
    series may be tested at all.
    """
    # Local import: mannkendall imports nothing from this module, but keeping
    # the dependency at call time makes the one-way relationship obvious.
    from ntgw.trends.mannkendall import sens_slope

    observed = series.dropna()
    if len(observed) >= 3:
        positions = np.arange(len(series), dtype=float)
        mask = series.notna().to_numpy()
        slope, _, _ = sens_slope(observed.to_numpy(), positions[mask])
        detrended = series - slope * positions if np.isfinite(slope) else series
    else:
        detrended = series

    climatology = month_climatology(detrended)
    offsets = pd.Series(series.index.month, index=series.index).map(climatology)
    offsets = offsets.fillna(0.0)
    return series - offsets, climatology


def months_covered(series: pd.Series) -> int:
    """How many distinct calendar months have at least one observation."""
    observed = series.dropna()
    if observed.empty:
        return 0
    return int(observed.index.month.nunique())
