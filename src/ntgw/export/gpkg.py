"""GeoPackage export for QGIS.

Every layer is checked against the atlas CRS on the way out and read back and
re-checked afterwards, because a writer that silently drops or rewrites a CRS
would otherwise produce a file that only looks right until someone opens it.
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd

from ntgw.crs import assert_atlas_crs
from ntgw.db import require_atlas_crs
from ntgw.scope import check_layer_names


def write_layers(path: str | Path, layers: dict[str, gpd.GeoDataFrame]) -> Path:
    """Write `layers` to a GeoPackage, verifying CRS before and after."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()

    if not layers:
        raise ValueError("no layers to write")

    check_layer_names(layers.keys())

    for name, gdf in layers.items():
        require_atlas_crs(gdf, f"layer {name!r}")

    for name, gdf in layers.items():
        gdf.to_file(target, layer=name, driver="GPKG")

    verify_gpkg(target)
    return target


def gpkg_layer_crs(path: str | Path) -> dict[str, object]:
    """Map every layer in a GeoPackage to the CRS it was actually written with."""
    import pyogrio

    out: dict[str, object] = {}
    for info in pyogrio.list_layers(str(path)):
        layer = info[0]
        meta = pyogrio.read_info(str(path), layer=layer)
        crs = meta.get("crs")
        out[layer] = crs
    return out


def verify_gpkg(path: str | Path) -> None:
    """Raise unless every layer in the file is EPSG:7853."""
    for layer, crs in gpkg_layer_crs(path).items():
        assert_atlas_crs(crs, f"GeoPackage layer {layer!r} in {Path(path).name}")
