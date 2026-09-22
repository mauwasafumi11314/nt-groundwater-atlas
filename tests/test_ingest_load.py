"""The mapping-agnostic half of ingest.

Every case here is one where getting it wrong produces a clean-looking dataset
that is quietly in the wrong place or the wrong order. None of them can be
resolved by a default, so all of them raise.
"""

from __future__ import annotations

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Point

from ntgw.crs import ATLAS_EPSG, MissingNTv2GridError, OutsideZoneError, grid_status
from ntgw.ingest.load import (
    AmbiguousDateError,
    AmbiguousSourceError,
    load_spatial,
    load_table,
    resolve_source_crs,
)
from ntgw.ingest.source import SourceSpec
from ntgw.inspect import date_ambiguity


def _points(crs, coords):
    return gpd.GeoDataFrame(
        {"id": list(range(len(coords)))},
        geometry=[Point(*c) for c in coords],
        crs=crs,
    )


# --------------------------------------------------------------------------
# CRS resolution
# --------------------------------------------------------------------------
def test_no_crs_anywhere_is_refused(tmp_path):
    spec = SourceSpec(path=tmp_path / "x.shp")
    with pytest.raises(AmbiguousSourceError, match="declares no CRS"):
        resolve_source_crs(None, spec)


def test_file_crs_is_used_when_the_spec_is_silent(tmp_path):
    spec = SourceSpec(path=tmp_path / "x.shp")
    assert resolve_source_crs("EPSG:28353", spec).to_epsg() == 28353


def test_spec_crs_is_used_when_the_file_is_silent(tmp_path):
    spec = SourceSpec(path=tmp_path / "x.shp", declared_crs="EPSG:28353")
    assert resolve_source_crs(None, spec).to_epsg() == 28353


def test_disagreeing_crs_declarations_are_refused_not_reconciled(tmp_path):
    """Preferring either one silently relocates the data."""
    spec = SourceSpec(path=tmp_path / "x.shp", declared_crs="EPSG:7853")
    with pytest.raises(AmbiguousSourceError, match="Refusing to pick one"):
        resolve_source_crs("EPSG:28353", spec)


def test_agreeing_crs_declarations_are_fine(tmp_path):
    spec = SourceSpec(path=tmp_path / "x.shp", declared_crs="EPSG:28353")
    assert resolve_source_crs("EPSG:28353", spec).to_epsg() == 28353


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------
def test_atlas_crs_source_loads_unchanged(tmp_path):
    path = tmp_path / "bores.gpkg"
    _points(f"EPSG:{ATLAS_EPSG}", [(400_000, 7_600_000), (410_000, 7_610_000)]).to_file(
        path, layer="bore", driver="GPKG"
    )
    out = load_spatial(SourceSpec(path=path))
    assert out.crs.to_epsg() == ATLAS_EPSG
    assert len(out) == 2


def test_crsless_file_is_refused(tmp_path):
    path = tmp_path / "wcd.shp"
    gdf = _points(f"EPSG:{ATLAS_EPSG}", [(400_000, 7_600_000)])
    gdf.to_file(path)
    (tmp_path / "wcd.prj").unlink()
    with pytest.raises(AmbiguousSourceError, match="declares no CRS"):
        load_spatial(SourceSpec(path=path))


def test_crsless_file_loads_once_the_spec_supplies_one(tmp_path):
    path = tmp_path / "wcd.shp"
    _points(f"EPSG:{ATLAS_EPSG}", [(400_000, 7_600_000)]).to_file(path)
    (tmp_path / "wcd.prj").unlink()
    out = load_spatial(
        SourceSpec(path=path, declared_crs=f"EPSG:{ATLAS_EPSG}", provenance="confirmed by supplier")
    )
    assert out.crs.to_epsg() == ATLAS_EPSG


def test_multi_layer_file_will_not_pick_a_layer(tmp_path):
    path = tmp_path / "multi.gpkg"
    pts = _points(f"EPSG:{ATLAS_EPSG}", [(400_000, 7_600_000)])
    pts.to_file(path, layer="first", driver="GPKG")
    pts.to_file(path, layer="second", driver="GPKG")
    with pytest.raises(AmbiguousSourceError, match="set SourceSpec.layer"):
        load_spatial(SourceSpec(path=path))


def test_named_layer_loads_from_a_multi_layer_file(tmp_path):
    path = tmp_path / "multi.gpkg"
    _points(f"EPSG:{ATLAS_EPSG}", [(400_000, 7_600_000)]).to_file(
        path, layer="first", driver="GPKG"
    )
    _points(f"EPSG:{ATLAS_EPSG}", [(401_000, 7_601_000), (402_000, 7_602_000)]).to_file(
        path, layer="second", driver="GPKG"
    )
    assert len(load_spatial(SourceSpec(path=path, layer="second"))) == 2


def test_gda94_source_requires_the_grid(tmp_path):
    """The rule holds through the loader, not just in ntgw.crs."""
    path = tmp_path / "bores_gda94.gpkg"
    _points("EPSG:4283", [(134.0, -21.0)]).to_file(path, layer="bore", driver="GPKG")
    spec = SourceSpec(path=path)
    if grid_status().available:
        out = load_spatial(spec)
        assert out.crs.to_epsg() == ATLAS_EPSG
    else:
        with pytest.raises(MissingNTv2GridError):
            load_spatial(spec)


def test_wrongly_declared_crs_is_caught_by_the_zone_check(tmp_path):
    """A wrong declaration transforms cleanly; only the result gives it away.

    These are MGA zone 53 coordinates mislabelled as zone 52, which is a plain
    typo and exactly the kind that survives every CRS check.
    """
    path = tmp_path / "bores.gpkg"
    _points("EPSG:7852", [(400_000, 7_600_000), (410_000, 7_610_000)]).to_file(
        path, layer="bore", driver="GPKG"
    )
    with pytest.raises(OutsideZoneError, match="outside MGA zone 53"):
        load_spatial(SourceSpec(path=path))


def test_zone_check_can_be_disabled_explicitly(tmp_path):
    path = tmp_path / "bores.gpkg"
    _points("EPSG:7852", [(400_000, 7_600_000)]).to_file(path, layer="bore", driver="GPKG")
    out = load_spatial(SourceSpec(path=path), validate_zone=False)
    assert out.crs.to_epsg() == ATLAS_EPSG


# --------------------------------------------------------------------------
# Dates
# --------------------------------------------------------------------------
def test_ambiguous_dates_are_refused(tmp_path):
    path = tmp_path / "levels.csv"
    path.write_text(
        "RN,MEAS_DATE,DTW\nRN1,01/03/2005,10.0\nRN2,05/06/2005,11.0\nRN3,02/11/2005,12.0\n"
    )
    with pytest.raises(AmbiguousDateError, match="day/month order"):
        load_table(SourceSpec(path=path))


def test_declaring_the_format_resolves_the_ambiguity(tmp_path):
    path = tmp_path / "levels.csv"
    path.write_text(
        "RN,MEAS_DATE,DTW\nRN1,01/03/2005,10.0\nRN2,05/06/2005,11.0\nRN3,02/11/2005,12.0\n"
    )
    frame = load_table(SourceSpec(path=path, date_formats={"MEAS_DATE": "%d/%m/%Y"}))
    assert pd.api.types.is_datetime64_any_dtype(frame["MEAS_DATE"])
    # day-first: 01/03 is 1 March, not 3 January
    assert frame["MEAS_DATE"].iloc[0] == pd.Timestamp("2005-03-01")


def test_declared_format_is_honoured_over_the_other_reading(tmp_path):
    path = tmp_path / "levels.csv"
    path.write_text("RN,MEAS_DATE\nRN1,01/03/2005\nRN2,05/06/2005\nRN3,02/11/2005\n")
    frame = load_table(SourceSpec(path=path, date_formats={"MEAS_DATE": "%m/%d/%Y"}))
    assert frame["MEAS_DATE"].iloc[0] == pd.Timestamp("2005-01-03")


def test_unambiguous_dates_need_no_declaration(tmp_path):
    path = tmp_path / "levels.csv"
    path.write_text("RN,MEAS_DATE\nRN1,25/03/2005\nRN2,01/04/2005\nRN3,13/05/2005\n")
    frame = load_table(SourceSpec(path=path))
    assert len(frame) == 3


def test_non_date_columns_do_not_trip_the_check(tmp_path):
    path = tmp_path / "levels.csv"
    path.write_text("RN,QUAL,DTW\nRN1,G,10.0\nRN2,S,11.0\nRN3,P,12.0\n")
    assert len(load_table(SourceSpec(path=path))) == 3


# --------------------------------------------------------------------------
# Version independence
# --------------------------------------------------------------------------
@pytest.mark.parametrize("dtype", ["object", "str"])
def test_date_check_examines_text_under_either_pandas_dtype(dtype):
    """pandas 2 gives strings 'object'; pandas 3 gives them 'str'.

    Testing *for* a text dtype silently disables the ambiguous-date guard on
    whichever version the developer is not running. This pins the inverted
    test that avoids that.
    """
    from ntgw.ingest.load import may_hold_text

    series = pd.Series(["01/03/2005", "05/06/2005", "02/11/2005"], dtype=dtype)
    assert may_hold_text(series)
    verdict = date_ambiguity(series)
    assert verdict is not None and verdict.startswith("AMBIGUOUS")


@pytest.mark.parametrize(
    "values",
    [[1.0, 2.0, 3.0], [1, 2, 3], [True, False, True], pd.to_datetime(["2005-01-01"] * 3)],
)
def test_non_text_columns_are_skipped(values):
    from ntgw.ingest.load import may_hold_text

    assert not may_hold_text(pd.Series(values))
