"""EPSG:7853 everywhere, and GDA94 only ever via the NTv2 grid.

The rule this file exists for is not "warn if the CRS looks wrong" but "fail".
"""

from __future__ import annotations

import geopandas as gpd
import pytest
from shapely.geometry import Point

from fixtures.synthetic import MGA53_ENVELOPE, WCD_ENVELOPE, synthetic_bores
from ntgw import crs as C
from ntgw.db import geometry_columns, require_atlas_crs, stored_srids
from ntgw.export.gpkg import verify_gpkg, write_layers


# --------------------------------------------------------------------------
# The NTv2 grid rule
# --------------------------------------------------------------------------
def test_helmert_fallback_is_not_silently_accepted():
    """The specific failure this module exists to prevent.

    PROJ offers a 7-parameter Helmert for GDA94 -> GDA2020 that is always
    available and carries a 0.01 m stated accuracy. It is not a ballpark
    transform, so `allow_ballpark=False` does not reject it, and PROJ ranks it
    as the best *available* operation, so `only_best=True` does not either.
    Anything relying on those two flags alone would silently ship Helmert
    coordinates. `transformer_to_atlas` must not.
    """
    status = C.grid_status()
    if status.available:
        transformer = C.transformer_to_atlas(4283)
        assert C.transformer_uses_grid(transformer, C.DEFAULT_GRID), (
            "grid is installed but the returned transformer does not use it"
        )
        assert "helmert" not in transformer.to_proj4().lower()
    else:
        with pytest.raises(C.MissingNTv2GridError):
            C.transformer_to_atlas(4283)


@pytest.mark.parametrize("epsg", [4283, 28353])
def test_gda94_requires_the_grid(epsg, grid_installed):
    if grid_installed:
        assert C.transformer_uses_grid(C.transformer_to_atlas(epsg), C.DEFAULT_GRID)
    else:
        with pytest.raises(C.MissingNTv2GridError):
            C.transformer_to_atlas(epsg)


def test_missing_grid_message_is_actionable():
    if C.grid_status().available:
        pytest.skip("grid installed; the missing-grid message cannot be raised")
    with pytest.raises(C.MissingNTv2GridError) as excinfo:
        C.transformer_to_atlas(4283)
    message = str(excinfo.value)
    assert C.DEFAULT_GRID in message
    assert "proj-data" in message
    assert "Helmert" in message


def test_gda2020_source_needs_no_grid():
    """GDA2020 -> MGA53 is a projection, not a datum shift."""
    transformer = C.transformer_to_atlas(7844)
    x, y = transformer.transform(-21.0, 134.0)
    assert MGA53_ENVELOPE["min_x"] < x < MGA53_ENVELOPE["max_x"]
    assert MGA53_ENVELOPE["min_y"] < y < MGA53_ENVELOPE["max_y"]


def test_unknown_datum_is_refused_not_ballparked():
    with pytest.raises(C.UnsupportedSourceDatumError):
        C.transformer_to_atlas(4326)


@pytest.mark.needs_grid
def test_grid_transform_differs_from_helmert(grid_installed):
    """With the grid installed, the grid result must differ from the Helmert one."""
    if not grid_installed:
        pytest.skip("ICSM NTv2 grid not installed (proj-data)")
    from pyproj import CRS, Transformer

    grid_t = C.transformer_to_atlas(4283)
    helmert_t = Transformer.from_crs(CRS.from_epsg(4283), CRS.from_epsg(C.ATLAS_EPSG))
    gx, gy = grid_t.transform(-21.0, 134.0)
    hx, hy = helmert_t.transform(-21.0, 134.0)
    assert (gx, gy) != (hx, hy)


# --------------------------------------------------------------------------
# EPSG:7853 everywhere
# --------------------------------------------------------------------------
@pytest.mark.parametrize("epsg", [4283, 4326, 28353, 7844, 3857])
def test_assert_atlas_crs_rejects_everything_else(epsg):
    with pytest.raises(C.WrongCrsError):
        C.assert_atlas_crs(epsg, f"EPSG:{epsg}")


def test_assert_atlas_crs_accepts_7853():
    C.assert_atlas_crs(7853, "atlas")


def test_missing_crs_is_rejected_not_assumed():
    """A frame with no CRS must not be written; PostGIS would relabel it."""
    gdf = gpd.GeoDataFrame({"id": [1]}, geometry=[Point(400_000, 7_600_000)], crs=None)
    with pytest.raises(C.WrongCrsError):
        require_atlas_crs(gdf, "unlabelled frame")


def test_every_database_geometry_column_is_7853(engine):
    columns = geometry_columns(engine)
    assert columns, "no geometry columns found - schema did not apply"
    wrong = [(t, c, s) for t, c, s in columns if s != C.ATLAS_EPSG]
    assert not wrong, f"geometry columns not in EPSG:{C.ATLAS_EPSG}: {wrong}"


def test_every_stored_geometry_is_7853(engine):
    """Declared SRID is not enough; check what is actually in the rows."""
    for table, column, _ in geometry_columns(engine):
        srids = stored_srids(engine, table, column)
        wrong = [s for s in srids if s != C.ATLAS_EPSG]
        assert not wrong, f"{table}.{column} holds geometry with SRID {wrong}"


def test_geopackage_output_is_7853(tmp_path):
    bores = synthetic_bores()
    gdf = gpd.GeoDataFrame(
        bores,
        geometry=[Point(xy) for xy in zip(bores.x, bores.y, strict=True)],
        crs=f"EPSG:{C.ATLAS_EPSG}",
    )
    out = write_layers(tmp_path / "atlas.gpkg", {"bore": gdf})
    verify_gpkg(out)


def test_geopackage_export_refuses_wrong_crs(tmp_path):
    bores = synthetic_bores()
    gdf = gpd.GeoDataFrame(
        bores,
        geometry=[Point(xy) for xy in zip(bores.x, bores.y, strict=True)],
        crs="EPSG:28353",
    )
    with pytest.raises(C.WrongCrsError):
        write_layers(tmp_path / "bad.gpkg", {"bore": gdf})


def test_synthetic_bores_fall_inside_zone_53():
    """Catches wrong-zone loads and swapped lat/lon, which stay 'valid' otherwise."""
    bores = synthetic_bores()
    assert (bores.x > MGA53_ENVELOPE["min_x"]).all()
    assert (bores.x < MGA53_ENVELOPE["max_x"]).all()
    assert (bores.y > MGA53_ENVELOPE["min_y"]).all()
    assert (bores.y < MGA53_ENVELOPE["max_y"]).all()
    assert (bores.x > WCD_ENVELOPE["min_x"]).all()
    assert (bores.y > WCD_ENVELOPE["min_y"]).all()
