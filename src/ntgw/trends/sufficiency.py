"""Whether a hydrograph may be tested for trend at all.

This module exists to keep one project rule honest: too little data is
`insufficient_data`, never `no_trend` and never "stable". The distinction is
not cosmetic. `no_trend` is a statement about the aquifer - the test ran and
did not reject. `insufficient_data` is a statement about the monitoring
network. Collapsing the second into the first turns an absence of evidence
into evidence of absence, and on a stress atlas that reads as reassurance
about exactly the bores nobody has been watching.

Sufficiency is therefore assessed *before* the test runs, and a series that
fails never reaches Mann-Kendall.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ntgw.trends.deseason import MonthlySeries, months_covered


@dataclass(frozen=True)
class SufficiencyThresholds:
    """Minimum record required before a trend may be reported.

    Defaults are hydrological judgement, not tuning: a Central Australian
    hydrograph needs to span enough years to see past multi-year rainfall
    variability before a monotonic trend means anything.
    """

    min_span_years: float = 8.0
    min_observations: int = 20
    min_distinct_years: int = 5
    max_gap_fraction: float = 0.40
    #: Separate, looser bar for de-seasonalising. Failing this does not make a
    #: series insufficient; it makes it untestable *seasonally*, and the runner
    #: records that the series was tested raw.
    min_years_for_climatology: int = 3
    min_months_for_climatology: int = 8


@dataclass(frozen=True)
class Sufficiency:
    """Verdict on one hydrograph."""

    sufficient: bool
    reasons: tuple[str, ...] = field(default=())
    can_deseasonalise: bool = False
    n_observations: int = 0
    n_months_present: int = 0
    span_years: float = 0.0
    distinct_years: int = 0
    gap_fraction: float = 1.0
    longest_gap_months: int = 0
    months_covered: int = 0

    @property
    def reason_text(self) -> str | None:
        return "; ".join(self.reasons) if self.reasons else None


def assess(
    monthly: MonthlySeries,
    thresholds: SufficiencyThresholds | None = None,
) -> Sufficiency:
    """Decide whether `monthly` supports a trend test.

    Every failed criterion is reported, not just the first, so the trend table
    says *why* a bore is grey rather than only that it is.
    """
    th = thresholds or SufficiencyThresholds()
    values = monthly.values
    observed = values.dropna() if len(values) else values

    distinct_years = int(observed.index.year.nunique()) if len(observed) else 0
    covered = months_covered(values) if len(values) else 0
    reasons: list[str] = []

    if monthly.n_observations < th.min_observations:
        reasons.append(f"only {monthly.n_observations} observations (need {th.min_observations})")
    if monthly.span_years < th.min_span_years:
        reasons.append(
            f"record spans {monthly.span_years:.1f} years (need {th.min_span_years:.0f})"
        )
    if distinct_years < th.min_distinct_years:
        reasons.append(f"only {distinct_years} distinct years (need {th.min_distinct_years})")
    if monthly.gap_fraction > th.max_gap_fraction:
        reasons.append(
            f"{monthly.gap_fraction:.0%} of months missing (limit {th.max_gap_fraction:.0%})"
        )

    can_deseasonalise = (
        distinct_years >= th.min_years_for_climatology and covered >= th.min_months_for_climatology
    )

    return Sufficiency(
        sufficient=not reasons,
        reasons=tuple(reasons),
        can_deseasonalise=can_deseasonalise,
        n_observations=monthly.n_observations,
        n_months_present=monthly.n_months_present,
        span_years=monthly.span_years,
        distinct_years=distinct_years,
        gap_fraction=monthly.gap_fraction,
        longest_gap_months=monthly.longest_gap_months,
        months_covered=covered,
    )
