"""Database connection and the write-side CRS guard.

The `geometry(..., 7853)` column types stop a wrong-SRID geometry from being
stored, but they do not stop the more dangerous case: geometry offered with no
SRID at all. PostGIS treats SRID 0 as "unknown" and coerces it to the column's
declared SRID, so coordinates that were never transformed out of GDA94 are
silently relabelled as GDA2020 and land about 1.8 m from where they belong.
Nothing downstream can detect that afterwards - the table looks perfectly
consistent. `require_atlas_crs` is therefore the guard that matters, and it
runs before anything is written.
"""

from __future__ import annotations

import os

import geopandas as gpd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from ntgw.crs import ATLAS_EPSG, WrongCrsError, assert_atlas_crs

DEFAULT_URL = "postgresql+psycopg2://ntgw:ntgw@127.0.0.1:5432/ntgw"


def database_url() -> str:
    """Connection URL, from NTGW_DATABASE_URL or the docker-compose default."""
    return os.environ.get("NTGW_DATABASE_URL", DEFAULT_URL)


def get_engine(url: str | None = None) -> Engine:
    return create_engine(url or database_url(), future=True)


def require_atlas_crs(gdf: gpd.GeoDataFrame, what: str = "GeoDataFrame") -> None:
    """Refuse a frame that is not explicitly EPSG:7853.

    A missing CRS is rejected outright rather than assumed: assuming is exactly
    how untransformed coordinates get relabelled.
    """
    if gdf.crs is None:
        raise WrongCrsError(
            f"{what} has no CRS set. Refusing to write it: PostGIS would coerce the "
            f"unknown SRID to {ATLAS_EPSG} and silently relabel untransformed "
            f"coordinates. Set the source CRS and transform via "
            f"ntgw.crs.transformer_to_atlas."
        )
    assert_atlas_crs(gdf.crs, what)


def geometry_columns(engine: Engine) -> list[tuple[str, str, int]]:
    """Every geometry column PostGIS knows about: (table, column, declared srid)."""
    sql = text(
        """
        SELECT f_table_name, f_geometry_column, srid
        FROM geometry_columns
        WHERE f_table_schema = current_schema()
        ORDER BY f_table_name, f_geometry_column
        """
    )
    with engine.connect() as conn:
        return [(r[0], r[1], int(r[2])) for r in conn.execute(sql)]


def stored_srids(engine: Engine, table: str, column: str) -> list[int]:
    """Distinct SRIDs actually present in the stored rows of one column."""
    sql = text(f'SELECT DISTINCT ST_SRID("{column}") FROM "{table}" WHERE "{column}" IS NOT NULL')
    with engine.connect() as conn:
        return sorted(int(r[0]) for r in conn.execute(sql))


def apply_schema(engine: Engine, path: str = "sql/001_schema.sql") -> None:
    with open(path) as fh:
        ddl = fh.read()
    with engine.begin() as conn:
        conn.execute(text(ddl))
