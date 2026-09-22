#!/usr/bin/env python
"""End-to-end phase-1 pipeline on synthetic data.

This exists so the pipeline can be demonstrated and smoke-tested before any
real extract is available. Everything it loads is generated; nothing here is NT
data. When the raw files arrive, the ingest layer replaces `_synthetic_inputs`
and the rest of this script stays as it is.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import geopandas as gpd  # noqa: E402
import pandas as pd  # noqa: E402
from shapely.geometry import Point  # noqa: E402
from sqlalchemy import text  # noqa: E402

from fixtures.synthetic import hydrograph, synthetic_bores, synthetic_wcd_polygon  # noqa: E402
from ntgw.crs import ATLAS_EPSG  # noqa: E402
from ntgw.db import apply_schema, get_engine  # noqa: E402
from ntgw.export.gpkg import write_layers  # noqa: E402
from ntgw.levels import datum_summary, derive_levels  # noqa: E402
from ntgw.trends.runner import analyse_bore  # noqa: E402

# Which synthetic hydrograph each bore gets, chosen to exercise every outcome.
SHAPES = ["falling", "rising", "flat", "short", "autocorrelated_flat", "sparse"]


def _synthetic_inputs():
    bores = synthetic_bores(n=len(SHAPES))
    frames = []
    for shape, bore_id in zip(SHAPES, bores.bore_id, strict=True):
        ts, head = hydrograph(shape, seed=abs(hash(bore_id)) % 997)
        frames.append(
            pd.DataFrame(
                {
                    "bore_id": bore_id,
                    "observed_at": ts,
                    # stored as measured: depth below collar
                    "depth_to_water_m": 40.0 - (head - head.mean()),
                    "shape": shape,
                }
            )
        )
    return bores, pd.concat(frames, ignore_index=True)


def main() -> int:
    bores, readings = _synthetic_inputs()
    print(f"synthetic inputs: {len(bores)} bores, {len(readings)} readings\n")

    engine = get_engine()
    apply_schema(engine, str(ROOT / "sql" / "001_schema.sql"))

    # --- load bores -------------------------------------------------------
    with engine.begin() as conn:
        for row in bores.itertuples():
            conn.execute(
                text(
                    "INSERT INTO bore (bore_id, geom, collar_rl_m_ahd, collar_rl_source, "
                    "datum_status, source_file, source_crs) VALUES (:bid, "
                    "ST_SetSRID(ST_MakePoint(:x,:y),:srid), :rl, :rls, :ds, :sf, :sc)"
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

    # --- derive m AHD, keeping no-collar-RL bores -------------------------
    derived = derive_levels(readings, bores)
    summary = datum_summary(derived)
    print("datum status:")
    print(f"  readings total              {summary['readings_total']:>6}")
    print(f"  with m AHD                  {summary['readings_with_ahd']:>6}")
    print(f"  no collar RL (flagged, kept){summary['readings_without_collar_rl']:>6}\n")

    with engine.begin() as conn:
        for row in derived.itertuples():
            conn.execute(
                text(
                    "INSERT INTO water_level (bore_id, observed_at, depth_to_water_m, "
                    "level_m_ahd, source_file) VALUES (:bid,:ts,:dtw,:ahd,'synthetic') "
                    "ON CONFLICT (bore_id, observed_at) DO NOTHING"
                ),
                {
                    "bid": row.bore_id,
                    "ts": row.observed_at,
                    "dtw": float(row.depth_to_water_m),
                    "ahd": None if pd.isna(row.level_m_ahd) else float(row.level_m_ahd),
                },
            )

    # --- trends -----------------------------------------------------------
    results = []
    for bore in bores.itertuples():
        rows = derived[derived.bore_id == bore.bore_id]
        has_rl = not pd.isna(bore.collar_rl_m_ahd)
        basis = "head_m_ahd" if has_rl else "depth_to_water_m"
        values = rows.level_m_ahd if has_rl else rows.depth_to_water_m
        results.append(analyse_bore(bore.bore_id, rows.observed_at, values, basis))

    with engine.begin() as conn:
        for r in results:
            row = r.as_row()
            cols = ", ".join(row)
            binds = ", ".join(f":{k}" for k in row)
            conn.execute(text(f"INSERT INTO bore_trend ({cols}) VALUES ({binds})"), row)

    # --- report -----------------------------------------------------------
    shapes = dict(zip(bores.bore_id, SHAPES, strict=True))
    print(
        f"{'bore':<8} {'shape':<20} {'basis':<17} {'class':<18} "
        f"{'slope m/yr':>11} {'p':>9} {'eff n':>7}"
    )
    print("-" * 96)
    for r in results:
        slope = f"{r.sens_slope_m_per_year:+.4f}" if r.sens_slope_m_per_year is not None else "-"
        p = f"{r.p_value:.3g}" if r.p_value is not None else "-"
        eff = f"{r.effective_n:.0f}/{r.n_months_present}" if r.effective_n else "-"
        print(
            f"{r.bore_id:<8} {shapes[r.bore_id]:<20} {r.basis:<17} {r.trend_class:<18} "
            f"{slope:>11} {p:>9} {eff:>7}"
        )
        if r.insufficient_reason:
            print(f"{'':<8} -> {r.insufficient_reason}")

    # --- export -----------------------------------------------------------
    with engine.connect() as conn:
        trend_gdf = gpd.GeoDataFrame.from_postgis(
            "SELECT * FROM bore_trend_geom", conn, geom_col="geom"
        )
    wcd = gpd.GeoDataFrame(
        {"wcd_id": ["SYN-WD"], "name": ["Synthetic pilot rectangle"]},
        geometry=[synthetic_wcd_polygon()],
        crs=f"EPSG:{ATLAS_EPSG}",
    )
    bore_gdf = gpd.GeoDataFrame(
        bores,
        geometry=[Point(xy) for xy in zip(bores.x, bores.y, strict=True)],
        crs=f"EPSG:{ATLAS_EPSG}",
    )
    out = write_layers(
        ROOT / "outputs" / "atlas_phase1_synthetic.gpkg",
        {"bore": bore_gdf, "bore_trend": trend_gdf, "wcd_boundary": wcd},
    )
    print(f"\nGeoPackage written: {out.relative_to(ROOT)}")

    import pyogrio

    for name, *_ in pyogrio.list_layers(str(out)):
        info = pyogrio.read_info(str(out), layer=name)
        epsg = info["crs"].split(":")[-1] if info.get("crs") else "?"
        print(f"  layer {name:<14} features={info['features']:<4} CRS=EPSG:{epsg}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
