"""Per-bore trend analysis: regularise, gate, de-seasonalise, test, classify.

Sign convention is the thing to get right here. A trend is always reported as
a trend in *groundwater level* (head), because that is what a stress atlas is
about. Bores with a collar RL are analysed in m AHD and the direction carries
straight through. Bores without one are analysed in depth-to-water, where the
sign is inverted: water getting deeper is a falling water table. Those bores
are kept - dropping them would discard exactly the unmonitored-network signal
the atlas is meant to surface - and carry `basis='depth_to_water_m'` plus a
null slope in m AHD so the two are never averaged together by accident.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

import numpy as np

from ntgw.trends.deseason import deseasonalise, to_monthly
from ntgw.trends.mannkendall import VarianceMethod, mann_kendall, sens_slope
from ntgw.trends.sufficiency import Sufficiency, SufficiencyThresholds, assess

#: The only values `trend_class` may take. Mirrored by a CHECK constraint in
#: sql/001_schema.sql so the database rejects anything else.
TREND_CLASSES = ("rising", "falling", "no_trend", "insufficient_data")

TrendClass = Literal["rising", "falling", "no_trend", "insufficient_data"]
Basis = Literal["head_m_ahd", "depth_to_water_m"]

MONTHS_PER_YEAR = 12.0


@dataclass(frozen=True)
class BoreTrend:
    """One row of the `bore_trend` table."""

    bore_id: str
    basis: Basis
    trend_class: TrendClass
    insufficient_reason: str | None
    n_observations: int
    n_months_present: int
    span_years: float
    distinct_years: int
    gap_fraction: float
    longest_gap_months: int
    deseasonalised: bool
    sens_slope_m_per_year: float | None
    sens_slope_lower: float | None
    sens_slope_upper: float | None
    p_value: float | None
    tau: float | None
    z_score: float | None
    variance_method: str | None
    autocorrelation_factor: float | None
    effective_n: float | None

    def as_row(self) -> dict:
        return asdict(self)


def _insufficient(bore_id: str, basis: Basis, s: Sufficiency) -> BoreTrend:
    return BoreTrend(
        bore_id=bore_id,
        basis=basis,
        trend_class="insufficient_data",
        insufficient_reason=s.reason_text,
        n_observations=s.n_observations,
        n_months_present=s.n_months_present,
        span_years=s.span_years,
        distinct_years=s.distinct_years,
        gap_fraction=s.gap_fraction,
        longest_gap_months=s.longest_gap_months,
        deseasonalised=False,
        sens_slope_m_per_year=None,
        sens_slope_lower=None,
        sens_slope_upper=None,
        p_value=None,
        tau=None,
        z_score=None,
        variance_method=None,
        autocorrelation_factor=None,
        effective_n=None,
    )


def analyse_bore(
    bore_id: str,
    timestamps,
    values,
    basis: Basis,
    thresholds: SufficiencyThresholds | None = None,
    alpha: float = 0.05,
    variance_method: VarianceMethod = "hamed_rao",
) -> BoreTrend:
    """Analyse one bore's hydrograph.

    `values` are m AHD when `basis='head_m_ahd'`, metres below collar when
    `basis='depth_to_water_m'`. The returned slope and class are always
    expressed as change in groundwater *level*.
    """
    if basis not in ("head_m_ahd", "depth_to_water_m"):
        raise ValueError(f"unknown basis {basis!r}")

    monthly = to_monthly(timestamps, values)
    verdict = assess(monthly, thresholds)
    if not verdict.sufficient:
        return _insufficient(bore_id, basis, verdict)

    series = monthly.values
    if verdict.can_deseasonalise:
        series, _ = deseasonalise(series)
        deseasonalised = True
    else:
        deseasonalised = False

    observed = series.dropna()
    # Elapsed years from the first reading, so Sen's slope comes out per year
    # and gaps are handled by real time rather than by sequence position.
    t_years = (observed.index - observed.index[0]).days.to_numpy(dtype=float) / 365.25
    x = observed.to_numpy(dtype=float)

    result = mann_kendall(x, alpha=alpha, variance_method=variance_method)
    slope, lower, upper = sens_slope(x, t_years, alpha=alpha)

    # Flip into head terms when the series is a depth.
    if basis == "depth_to_water_m":
        slope, lower, upper = -slope, -upper, -lower
        direction = {
            "increasing": "decreasing",
            "decreasing": "increasing",
            "no_trend": "no_trend",
        }[result.direction]
    else:
        direction = result.direction

    trend_class: TrendClass = {
        "increasing": "rising",
        "decreasing": "falling",
        "no_trend": "no_trend",
    }[direction]

    return BoreTrend(
        bore_id=bore_id,
        basis=basis,
        trend_class=trend_class,
        insufficient_reason=None,
        n_observations=verdict.n_observations,
        n_months_present=verdict.n_months_present,
        span_years=verdict.span_years,
        distinct_years=verdict.distinct_years,
        gap_fraction=verdict.gap_fraction,
        longest_gap_months=verdict.longest_gap_months,
        deseasonalised=deseasonalised,
        sens_slope_m_per_year=float(slope) if np.isfinite(slope) else None,
        sens_slope_lower=float(lower) if np.isfinite(lower) else None,
        sens_slope_upper=float(upper) if np.isfinite(upper) else None,
        p_value=result.p_value,
        tau=result.tau,
        z_score=result.z,
        variance_method=result.variance_method,
        autocorrelation_factor=result.autocorrelation_factor,
        effective_n=result.effective_n,
    )
