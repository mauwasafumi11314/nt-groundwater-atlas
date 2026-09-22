"""Levels are m AHD, and a bore without a collar RL is flagged, not dropped."""

from __future__ import annotations

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Point
from sqlalchemy import text

from fixtures.synthetic import hydrograph, synthetic_bores
from ntgw.crs import ATLAS_EPSG
from ntgw.levels import DATUM_MISSING, datum_summary, derive_levels
from ntgw.trends.runner import analyse_bore


@pytest.fixture
def bores() -> pd.DataFrame:
    return synthetic_bores()


@pytest.fixture
def readings(bores) -> pd.DataFrame:
    rows = []
    for bore_id in bores.bore_id:
        ts, values = hydrograph("falling", seed=abs(hash(bore_id)) % 1000)
        rows.append(
            pd.DataFrame(
                {
                    "bore_id": bore_id,
                    "observed_at": ts,
                    # depth below collar, so the mirror image of head
                    "depth_to_water_m": 40.0 - (values - values.mean()),
                }
            )
        )
    return pd.concat(rows, ignore_index=True)


def test_fixture_actually_contains_bores_without_collar_rl(bores):
    assert bores.collar_rl_m_ahd.isna().sum() >= 2, "fixture must exercise the rule"


def test_no_reading_is_dropped_for_a_missing_collar_rl(bores, readings):
    derived = derive_levels(readings, bores)
    assert len(derived) == len(readings)
    for bore_id in bores.bore_id:
        assert (derived.bore_id == bore_id).sum() == (readings.bore_id == bore_id).sum()


def test_missing_collar_rl_yields_null_ahd_but_keeps_depth(bores, readings):
    derived = derive_levels(readings, bores)
    no_rl = derived[derived.datum_status == DATUM_MISSING]
    assert len(no_rl) > 0
    assert no_rl.level_m_ahd.isna().all(), "level must be null, not guessed"
    assert no_rl.depth_to_water_m.notna().all(), "the measured depth must survive"


def test_level_is_collar_rl_minus_depth(bores, readings):
    derived = derive_levels(readings, bores)
    known = derived[derived.datum_status != DATUM_MISSING].iloc[0]
    collar = bores.set_index("bore_id").loc[known.bore_id, "collar_rl_m_ahd"]
    assert known.level_m_ahd == pytest.approx(collar - known.depth_to_water_m)


def test_datum_summary_reports_both_populations(bores, readings):
    summary = datum_summary(derive_levels(readings, bores))
    assert summary["readings_total"] == len(readings)
    assert summary["readings_without_collar_rl"] > 0
    assert (
        summary["readings_with_ahd"] + summary["readings_without_collar_rl"]
        == summary["readings_total"]
    )


def test_a_bore_without_collar_rl_still_gets_a_trend():
    """Flagged, not excluded: it is analysed in depth-to-water instead."""
    ts, head = hydrograph("falling")
    depth = 40.0 - (head - head.mean())
    result = analyse_bore("NO-RL", ts, depth, "depth_to_water_m")
    assert result.trend_class != "insufficient_data"
    assert result.basis == "depth_to_water_m"


def test_depth_basis_reports_a_falling_water_table_as_falling():
    """Sign convention: deepening water is a falling level, however it is measured."""
    ts, head = hydrograph("falling")
    depth = 40.0 - (head - head.mean())
    by_head = analyse_bore("H", ts, head, "head_m_ahd")
    by_depth = analyse_bore("D", ts, depth, "depth_to_water_m")
    assert by_head.trend_class == "falling"
    assert by_depth.trend_class == "falling"
    assert by_depth.sens_slope_m_per_year < 0
    assert by_head.sens_slope_m_per_year == pytest.approx(by_depth.sens_slope_m_per_year, abs=0.02)


def test_bores_without_collar_rl_survive_the_database_load(engine, bores):
    """The rule has to hold through PostGIS, not just in pandas."""
    gdf = gpd.GeoDataFrame(
        bores,
        geometry=[Point(xy) for xy in zip(bores.x, bores.y, strict=True)],
        crs=f"EPSG:{ATLAS_EPSG}",
    )
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM bore"))
        for row in gdf.itertuples():
            conn.execute(
                text(
                    "INSERT INTO bore (bore_id, geom, collar_rl_m_ahd, collar_rl_source, "
                    "datum_status, source_file, source_crs) VALUES "
                    "(:bid, ST_SetSRID(ST_MakePoint(:x, :y), :srid), :rl, :rls, :ds, :sf, :sc)"
                ),
                {
                    "bid": row.bore_id,
                    "x": row.x,
                    "y": row.y,
                    "srid": ATLAS_EPSG,
                    "rl": None if pd.isna(row.collar_rl_m_ahd) else float(row.collar_rl_m_ahd),
                    "rls": row.collar_rl_source,
                    "ds": row.datum_status,
                    "sf": row.source_file,
                    "sc": row.source_crs,
                },
            )

    with engine.connect() as conn:
        loaded = conn.execute(text("SELECT count(*) FROM bore")).scalar_one()
        flagged = conn.execute(
            text("SELECT count(*) FROM bore WHERE datum_status = :ds"), {"ds": DATUM_MISSING}
        ).scalar_one()

    assert loaded == len(bores), "bores were lost on load"
    assert flagged == int(bores.collar_rl_m_ahd.isna().sum())


def test_database_rejects_a_bore_claiming_an_rl_it_does_not_have(engine):
    """The flag cannot drift away from the data it describes."""
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO bore (bore_id, geom, collar_rl_m_ahd, datum_status, "
                "source_file, source_crs) VALUES "
                "('LIAR', ST_SetSRID(ST_MakePoint(400000, 7600000), 7853), NULL, "
                "'collar_rl_known', 'synthetic', 'EPSG:7853')"
            )
        )
