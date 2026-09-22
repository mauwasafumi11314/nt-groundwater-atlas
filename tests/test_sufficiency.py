"""Too little data is 'insufficient_data' - never 'no_trend', never 'stable'.

This is the rule most likely to be eroded by a later change, because
`insufficient_data` is the inconvenient answer. These tests pin it.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from fixtures.synthetic import hydrograph
from ntgw.trends.deseason import to_monthly
from ntgw.trends.runner import TREND_CLASSES, analyse_bore
from ntgw.trends.sufficiency import SufficiencyThresholds, assess


def test_trend_classes_are_exactly_the_four_allowed():
    assert set(TREND_CLASSES) == {"rising", "falling", "no_trend", "insufficient_data"}


@pytest.mark.parametrize("forbidden", ["stable", "low_stress", "no_stress", "unknown", "none"])
def test_reassuring_labels_are_not_trend_classes(forbidden):
    """'low stress' and 'stable' must never be reachable as a trend outcome."""
    assert forbidden not in TREND_CLASSES


def test_short_record_is_insufficient_not_no_trend():
    ts, values = hydrograph("short")
    result = analyse_bore("SHORT", ts, values, "head_m_ahd")
    assert result.trend_class == "insufficient_data"
    assert result.trend_class != "no_trend"
    assert result.insufficient_reason
    assert result.p_value is None
    assert result.sens_slope_m_per_year is None


def test_sparse_record_over_a_long_span_is_insufficient():
    """A long span is not enough on its own; a blind gap in the middle is fatal."""
    ts, values = hydrograph("sparse")
    result = analyse_bore("SPARSE", ts, values, "head_m_ahd")
    assert result.trend_class == "insufficient_data"
    assert "missing" in result.insufficient_reason


def test_insufficient_verdict_lists_every_failed_criterion():
    ts = pd.date_range("2022-01-01", periods=4, freq="MS")
    verdict = assess(to_monthly(ts, np.arange(4.0)))
    assert not verdict.sufficient
    assert len(verdict.reasons) >= 3
    assert any("observations" in r for r in verdict.reasons)
    assert any("years" in r for r in verdict.reasons)


def test_a_genuinely_flat_long_record_is_no_trend_not_insufficient():
    """The counterpart: when the test can run and does not reject, say so."""
    ts, values = hydrograph("flat")
    result = analyse_bore("FLAT", ts, values, "head_m_ahd")
    assert result.trend_class == "no_trend"
    assert result.insufficient_reason is None
    assert result.p_value is not None


def test_sufficient_record_reports_a_direction():
    for kind, expected in (("falling", "falling"), ("rising", "rising")):
        ts, values = hydrograph(kind)
        result = analyse_bore(kind.upper(), ts, values, "head_m_ahd")
        assert result.trend_class == expected


def test_thresholds_are_explicit_and_overridable():
    ts, values = hydrograph("short")
    strict = analyse_bore("S", ts, values, "head_m_ahd")
    assert strict.trend_class == "insufficient_data"

    permissive = analyse_bore(
        "S",
        ts,
        values,
        "head_m_ahd",
        thresholds=SufficiencyThresholds(
            min_span_years=0.5, min_observations=8, min_distinct_years=1
        ),
    )
    assert permissive.trend_class != "insufficient_data"


def test_sufficiency_is_decided_before_the_test_runs():
    """An insufficient series must never reach Mann-Kendall at all."""
    import ntgw.trends.runner as runner

    calls = []
    original = runner.mann_kendall

    def spy(*args, **kwargs):
        calls.append(args)
        return original(*args, **kwargs)

    runner.mann_kendall = spy
    try:
        ts, values = hydrograph("short")
        runner.analyse_bore("SHORT", ts, values, "head_m_ahd")
    finally:
        runner.mann_kendall = original
    assert calls == [], "Mann-Kendall was run on a series that failed the sufficiency gate"


def test_seasonal_only_record_is_not_reported_as_a_trend():
    ts, values = hydrograph("seasonal_only")
    result = analyse_bore("SEASON", ts, values, "head_m_ahd")
    assert result.trend_class == "no_trend"
    assert result.deseasonalised


def test_autocorrelated_flat_record_is_not_a_trend():
    """The case uncorrected Mann-Kendall gets wrong about half the time."""
    ts, values = hydrograph("autocorrelated_flat")
    result = analyse_bore("AR1", ts, values, "head_m_ahd")
    assert result.trend_class == "no_trend"
    assert result.autocorrelation_factor > 1.0
    assert result.effective_n < result.n_months_present
