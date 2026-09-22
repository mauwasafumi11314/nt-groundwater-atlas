"""Reading raw files into the atlas CRS, refusing anything ambiguous.

This is the half of ingest that does not depend on knowing what any column
means: open the file, establish its CRS honestly, transform it through the
NTv2 grid, and prove the result landed where the Northern Territory is. The
column mapping is the other half and cannot be written yet.

Every check here exists because its failure mode is silent:

  * a file with no CRS is not assumed to be anything
  * a file whose declared CRS disagrees with the spec is not resolved by
    preferring one of them
  * a wrong declaration transforms cleanly, so the *result* is checked against
    the zone 53 envelope rather than the declaration being trusted
  * dd/mm and mm/dd dates that cannot be told apart are not guessed; an
    explicit format is required
"""

from __future__ import annotations

import geopandas as gpd
import pandas as pd
from pyproj import CRS

from ntgw.crs import ATLAS_EPSG, CrsPolicyError, assert_within_zone53, transformer_to_atlas
from ntgw.ingest.source import SourceSpec
from ntgw.inspect import date_ambiguity


class AmbiguousSourceError(CrsPolicyError):
    """The file cannot be read without a decision the data does not contain."""


class AmbiguousDateError(Exception):
    """A date column's day/month order cannot be inferred and was not declared."""


def may_hold_text(series: pd.Series) -> bool:
    """Whether `series` could contain date strings worth checking.

    Written as "not definitely something else" rather than "is text". pandas 2
    reads string columns as `object` and pandas 3 as `str`, so testing *for* a
    text dtype silently disables the ambiguous-date guard on whichever version
    the test environment is not running - the kind of difference that passes
    locally and lets bad dates through in production.
    """
    return not (
        pd.api.types.is_numeric_dtype(series)
        or pd.api.types.is_datetime64_any_dtype(series)
        or pd.api.types.is_bool_dtype(series)
    )


def resolve_source_crs(file_crs, spec: SourceSpec) -> CRS:
    """Decide the source CRS, or refuse.

    Never falls back to a default. A file that declares nothing and a spec that
    declares nothing is an open question, not an EPSG:7853 dataset.
    """
    parsed_file = CRS.from_user_input(file_crs) if file_crs else None
    parsed_spec = CRS.from_user_input(spec.declared_crs) if spec.declared_crs else None

    if parsed_file is None and parsed_spec is None:
        raise AmbiguousSourceError(
            f"{spec.name} declares no CRS and none was supplied. Establish it from the "
            f"supplier or the accompanying metadata and set SourceSpec.declared_crs; "
            f"assuming one would put the data somewhere it may not belong."
        )
    if parsed_file is not None and parsed_spec is not None and not parsed_file.equals(parsed_spec):
        raise AmbiguousSourceError(
            f"{spec.name} declares {parsed_file.name!r} but SourceSpec says "
            f"{parsed_spec.name!r}. Refusing to pick one. Resolve which is correct - "
            f"if the file's own .prj is wrong, say so explicitly in the spec's provenance "
            f"and remove the file's CRS, rather than overriding it silently."
        )
    return parsed_file or parsed_spec


def load_spatial(spec: SourceSpec, validate_zone: bool = True) -> gpd.GeoDataFrame:
    """Read a spatial file and return it in EPSG:7853.

    The transform goes through `ntgw.crs.transformer_to_atlas`, so a GDA94
    source with no NTv2 grid installed raises rather than using the Helmert
    approximation.
    """
    import pyogrio

    layers = [row[0] for row in pyogrio.list_layers(str(spec.path))]
    if spec.layer is None and len(layers) > 1:
        raise AmbiguousSourceError(
            f"{spec.name} has {len(layers)} layers ({layers}); set SourceSpec.layer "
            f"rather than loading whichever comes first."
        )
    layer = spec.layer or (layers[0] if layers else None)

    gdf = gpd.read_file(spec.path, layer=layer)
    source_crs = resolve_source_crs(gdf.crs, spec)

    if source_crs.to_epsg() == ATLAS_EPSG:
        out = gdf.set_crs(source_crs, allow_override=True)
    else:
        # Resolve the transformer first: this is what raises on a missing grid,
        # and it should raise before any coordinates move.
        transformer_to_atlas(source_crs)
        out = gdf.set_crs(source_crs, allow_override=True).to_crs(epsg=ATLAS_EPSG)

    if validate_zone and not out.empty and out.geometry.notna().any():
        assert_within_zone53(out.total_bounds, f"{spec.name} (layer {layer!r})")
    return out


def load_table(spec: SourceSpec, **read_csv_kwargs) -> pd.DataFrame:
    """Read a delimited text file, refusing ambiguous dates.

    Columns listed in `spec.date_formats` are parsed with the format given.
    Any other column that looks like a slash date whose order cannot be
    inferred raises: parsing it either way succeeds and silently reorders the
    record.
    """
    frame = pd.read_csv(spec.path, **read_csv_kwargs)

    unresolved: list[tuple[str, str]] = []
    for column in frame.columns:
        if column in spec.date_formats:
            continue
        series = frame[column]
        if not may_hold_text(series):
            continue
        verdict = date_ambiguity(series)
        if verdict and verdict.startswith("AMBIGUOUS"):
            unresolved.append((str(column), verdict))

    if unresolved:
        detail = "\n".join(f"  {name}: {verdict}" for name, verdict in unresolved)
        raise AmbiguousDateError(
            f"{spec.name} has date column(s) whose day/month order cannot be inferred:\n"
            f"{detail}\n"
            f"Set SourceSpec.date_formats for each (e.g. {{'MEAS_DATE': '%d/%m/%Y'}}) "
            f"after confirming with the supplier. Parsing succeeds either way and "
            f"silently reorders the series, so this cannot be left to a default."
        )

    for column, fmt in spec.date_formats.items():
        if column in frame.columns:
            frame[column] = pd.to_datetime(frame[column], format=fmt)
    return frame
