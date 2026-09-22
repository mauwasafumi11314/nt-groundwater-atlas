"""The raw-file inspector.

Its job is to produce evidence, never to interpret it: the two things that
silently corrupt a load if guessed - an absent or disagreeing CRS, and dd/mm vs
mm/dd dates - must be reported as open questions rather than resolved.
"""

from __future__ import annotations

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Point, box

from ntgw.inspect import _crs_verdict, _date_ambiguity, inspect_path


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        (["25/03/2005", "01/04/2005", "13/05/2005"], "day-first"),
        (["03/25/2005", "04/01/2005", "05/13/2005"], "month-first"),
        (["2005-03-01", "2005-04-13", "2005-05-02"], "year-first"),
    ],
)
def test_unambiguous_date_orders_are_identified(values, expected):
    verdict = _date_ambiguity(pd.Series(values))
    assert verdict is not None and expected in verdict


def test_ambiguous_dates_are_flagged_not_guessed():
    """No field over 12: the order genuinely cannot be inferred, so say so."""
    verdict = _date_ambiguity(pd.Series(["01/03/2005", "05/06/2005", "02/11/2005"]))
    assert verdict is not None
    assert "AMBIGUOUS" in verdict
    assert "Confirm with the supplier" in verdict


@pytest.mark.parametrize(
    "values",
    [["DIPPER", "LOGGER", "DIPPER"], ["n/a", "", "--"], ["1.5", "2.5", "3.5"]],
)
def test_non_dates_are_not_flagged(values):
    assert _date_ambiguity(pd.Series(values)) is None


def test_too_few_values_to_judge_returns_nothing():
    """Below a handful of parseable values the pattern is noise, not evidence."""
    assert _date_ambiguity(pd.Series(["01/03/2005", "05/06/2005"])) is None


def test_missing_crs_is_reported_as_a_blocker():
    notes = "\n".join(_crs_verdict(None, (400_000, 7_600_000, 410_000, 7_610_000)))
    assert "NONE DECLARED" in notes


def test_gda94_source_is_flagged_as_needing_the_grid():
    notes = "\n".join(_crs_verdict("EPSG:4283", (133.0, -22.0, 135.0, -20.0)))
    assert "NTv2 grid REQUIRED" in notes


def test_atlas_crs_is_reported_as_needing_no_transform():
    notes = "\n".join(_crs_verdict("EPSG:7853", (400_000, 7_600_000, 410_000, 7_610_000)))
    assert "no transform needed" in notes


def test_coordinates_disagreeing_with_units_are_called_out():
    """Degrees declared as metres, or vice versa, is the classic silent failure."""
    geographic = "\n".join(_crs_verdict("EPSG:4283", (133.0, -22.0, 135.0, -20.0)))
    assert "lon/lat degrees" in geographic
    projected = "\n".join(_crs_verdict("EPSG:7853", (400_000, 7_600_000, 410_000, 7_610_000)))
    assert "MGA metres" in projected


def test_missing_directory_is_reported_not_raised(tmp_path):
    report = "\n".join(inspect_path(tmp_path / "nope", show_values=True))
    assert "does not exist" in report


def test_empty_directory_is_reported(tmp_path):
    report = "\n".join(inspect_path(tmp_path, show_values=True))
    assert "is empty" in report


def test_out_of_scope_files_are_listed_but_not_opened(tmp_path):
    gpd.GeoDataFrame({"n": [1]}, geometry=[Point(134, -21)], crs="EPSG:4283").to_file(
        tmp_path / "sacred_sites.shp"
    )
    report = "\n".join(inspect_path(tmp_path, show_values=True))
    assert "OUT OF SCOPE" in report
    assert "not opened" in report


def test_shapefile_sidecars_are_grouped_with_their_shp(tmp_path):
    gpd.GeoDataFrame({"n": [1]}, geometry=[Point(400_000, 7_600_000)], crs="EPSG:7853").to_file(
        tmp_path / "bores.shp"
    )
    report = "\n".join(inspect_path(tmp_path, show_values=True))
    assert "bores.shp" in report
    assert "bores.dbf" not in report
    assert "bores.prj" not in report


def test_attribute_nulls_are_profiled(tmp_path):
    """A field's null fraction decides mappings more often than its type does."""
    gdf = gpd.GeoDataFrame(
        {"COLLAR_RL": [320.0, None, 340.0, None], "STATUS": ["A", "A", "B", "B"]},
        geometry=[box(i, i, i + 1, i + 1) for i in range(4)],
        crs="EPSG:7853",
    )
    gdf.to_file(tmp_path / "bores.gpkg", layer="bore", driver="GPKG")
    report = "\n".join(inspect_path(tmp_path, show_values=True))
    assert "COLLAR_RL" in report
    assert "50.0%" in report


def test_low_cardinality_columns_have_their_code_list_shown(tmp_path):
    (tmp_path / "levels.csv").write_text("RN,QUAL_CODE\nRN1,G\nRN2,S\nRN3,P\nRN4,G\n")
    report = "\n".join(inspect_path(tmp_path, show_values=True))
    assert "QUAL_CODE" in report
    assert "'G'" in report and "'S'" in report and "'P'" in report


def test_no_values_mode_omits_sample_values(tmp_path):
    (tmp_path / "levels.csv").write_text("RN,QUAL_CODE\nRN1,G\nRN2,S\n")
    report = "\n".join(inspect_path(tmp_path, show_values=False))
    assert "QUAL_CODE" in report
    assert "values:" not in report
