"""Structural inspection of raw source files.

CLAUDE.md forbids writing a mapping against a schema nobody has seen. This
module is how the seeing gets done: it reports what a file actually contains -
layers, fields, dtypes, null fractions, declared CRS, value ranges and code
lists - without interpreting any of it. Nothing here writes a mapping; it only
produces the evidence a mapping would have to be written from.

Two things it flags rather than resolves, because both silently corrupt data
when guessed wrong:

  * a declared CRS that disagrees with the coordinates, or is absent entirely
  * dd/mm vs mm/dd dates, which are indistinguishable until some day exceeds 12

`scripts/inspect_raw.py` is the command-line wrapper.
"""

from __future__ import annotations

import re
from pathlib import Path

from ntgw.scope import excluded_theme

OGR_SUFFIXES = {".shp", ".gpkg", ".geojson", ".json", ".kml", ".kmz", ".gml", ".gdb", ".tab"}
TABULAR_SUFFIXES = {".csv", ".tsv", ".txt", ".psv"}
EXCEL_SUFFIXES = {".xlsx", ".xls", ".xlsm"}
ARCHIVE_SUFFIXES = {".zip", ".7z", ".tar", ".gz", ".tgz"}

#: Shapefile sidecars: reported with the .shp, not as files in their own right.
SIDECARS = {".shx", ".dbf", ".prj", ".sbn", ".sbx", ".cpg", ".qix", ".qpj", ".xml"}

MAX_DISTINCT = 12  # columns with no more distinct values than this get them listed
SAMPLE_VALUES = 3

#: dd/mm/yyyy and mm/dd/yyyy are indistinguishable until a day exceeds 12.
#: Australian sources are normally day-first; pandas guesses month-first. Getting
#: this wrong silently reorders a hydrograph instead of failing, so any column
#: that looks like a slash date is flagged for an explicit format at load time.
_SLASH_DATE = re.compile(r"^\s*(\d{1,4})[/-](\d{1,2})[/-](\d{1,4})")


def date_ambiguity(series) -> str | None:
    """Flag slash/dash dates whose day-vs-month order cannot be inferred."""
    sample = series.dropna().astype(str).head(2000)
    parts = [m.groups() for m in (_SLASH_DATE.match(v) for v in sample) if m]
    if len(parts) < max(3, 0.8 * len(sample)):
        return None
    try:
        first = max(int(a) for a, _, _ in parts)
        second = max(int(b) for _, b, _ in parts)
    except ValueError:
        return None

    # Whichever field exceeds 12 must be the day (or, above 31, the year).
    if first > 31:
        return "year-first (yyyy-mm-dd), unambiguous"
    if first > 12:
        return "day-first (dd/mm/yyyy) - first field exceeds 12"
    if second > 12:
        return "month-first (mm/dd/yyyy) - second field exceeds 12"
    return (
        "AMBIGUOUS: no field exceeds 12, so dd/mm and mm/dd cannot be told apart. "
        "Confirm with the supplier and pass an explicit format at load time"
    )


def _human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024.0
    return f"{n:.1f}GB"


def _describe_series(name, series, show_values: bool) -> str:
    import pandas as pd

    n = len(series)
    nulls = int(series.isna().sum())
    null_pct = (nulls / n * 100.0) if n else 0.0
    dtype = str(series.dtype)
    bits = [f"    {name:<28} {dtype:<16} null {null_pct:5.1f}%"]

    non_null = series.dropna()
    if non_null.empty:
        bits.append("  (all null)")
        return "".join(bits)

    if pd.api.types.is_numeric_dtype(non_null):
        bits.append(
            f"  min {non_null.min():.6g}  median {non_null.median():.6g}  max {non_null.max():.6g}"
        )
    elif pd.api.types.is_datetime64_any_dtype(non_null):
        bits.append(f"  {non_null.min()} .. {non_null.max()}")
    else:
        distinct = non_null.nunique()
        bits.append(f"  distinct {distinct}")
        ambiguity = date_ambiguity(non_null)
        if ambiguity:
            bits.append(f"\n      ^ date format: {ambiguity}")
        if show_values:
            if distinct <= MAX_DISTINCT:
                values = sorted(str(v) for v in non_null.unique())
                bits.append(f"  values: {values}")
            else:
                sample = [str(v) for v in non_null.head(SAMPLE_VALUES)]
                bits.append(f"  e.g. {sample}")
    return "".join(bits)


def _crs_verdict(crs_wkt, bounds) -> list[str]:
    """Say what the declared CRS is and whether the coordinates agree with it."""
    notes = []
    if not crs_wkt:
        notes.append("    CRS: NONE DECLARED  <-- must be established before loading")
    else:
        try:
            from pyproj import CRS as PyCRS

            crs = PyCRS.from_user_input(crs_wkt)
            epsg = crs.to_epsg()
            notes.append(
                f"    CRS: {crs.name}" + (f" (EPSG:{epsg})" if epsg else " (no EPSG code)")
            )
            if epsg == 7853:
                notes.append("         already the atlas CRS; no transform needed")
            elif crs.is_geographic:
                notes.append("         geographic: will need projecting to EPSG:7853")
            if "GDA94" in crs.name or (crs.datum and "1994" in crs.datum.name):
                notes.append("         GDA94 datum: NTv2 grid REQUIRED (see ntgw.crs)")
        except Exception as exc:
            notes.append(f"    CRS: unparseable ({type(exc).__name__})")

    if bounds is not None and len(bounds) == 4:
        minx, miny, maxx, maxy = bounds
        notes.append(f"    bounds: x {minx:.4g}..{maxx:.4g}  y {miny:.4g}..{maxy:.4g}")
        looks_geographic = -180 <= minx <= 180 and -90 <= miny <= 90 and abs(maxx) <= 180
        looks_mga = 100_000 <= minx <= 900_000 and 6_000_000 <= miny <= 8_000_000
        if looks_geographic:
            notes.append("         coordinates look like lon/lat degrees")
        elif looks_mga:
            notes.append("         coordinates look like MGA metres")
        else:
            notes.append("         coordinates match neither lon/lat nor MGA - check the CRS")
    return notes


def inspect_ogr(path: Path, show_values: bool) -> list[str]:
    import pyogrio

    out = []
    try:
        layers = pyogrio.list_layers(str(path))
    except Exception as exc:
        return [f"    could not open: {type(exc).__name__}: {exc}"]

    for row in layers:
        layer_name = row[0]
        geom_type = row[1] if len(row) > 1 else "?"
        theme = excluded_theme(str(layer_name))
        if theme:
            out.append(f"  layer {layer_name!r} [{theme} - OUT OF SCOPE, not inspected]")
            continue
        out.append(f"  layer {layer_name!r}  geometry={geom_type}")
        try:
            info = pyogrio.read_info(str(path), layer=layer_name)
            out.append(f"    features: {info.get('features', '?')}")
            out += _crs_verdict(info.get("crs"), info.get("total_bounds"))
            fields = list(info.get("fields", []))
            out.append(f"    fields ({len(fields)}):")
            try:
                # Profile the attributes the same way as a CSV: a field's null
                # fraction and value range decide mappings far more often than
                # its declared type does.
                frame = pyogrio.read_dataframe(
                    str(path), layer=layer_name, read_geometry=False, max_features=5000
                )
                for col in frame.columns:
                    out.append(_describe_series(str(col), frame[col], show_values))
            except Exception as exc:
                out.append(f"      (could not profile attributes: {type(exc).__name__})")
                dtypes = list(info.get("dtypes", [])) or ["?"] * len(fields)
                for fname, dtype in zip(fields, dtypes, strict=False):
                    out.append(f"      {fname:<28} {dtype}")
        except Exception as exc:
            out.append(f"    could not read info: {type(exc).__name__}: {exc}")
    return out


def inspect_tabular(path: Path, show_values: bool) -> list[str]:
    import pandas as pd

    out = []
    try:
        head = pd.read_csv(path, nrows=5000, sep=None, engine="python")
    except Exception as exc:
        return [f"    could not parse: {type(exc).__name__}: {exc}"]

    try:
        total = sum(1 for _ in path.open("rb")) - 1
    except Exception:
        total = None
    out.append(
        f"    rows: {total if total is not None else '?'}"
        f"{'  (profiled on first 5000)' if total and total > 5000 else ''}"
    )
    out.append(f"    columns ({len(head.columns)}):")
    for col in head.columns:
        out.append(_describe_series(col, head[col], show_values))
    return out


def inspect_excel(path: Path, show_values: bool) -> list[str]:
    import pandas as pd

    out = []
    try:
        book = pd.ExcelFile(path)
    except Exception as exc:
        return [f"    could not open: {type(exc).__name__}: {exc}"]
    for sheet in book.sheet_names:
        out.append(f"  sheet {sheet!r}")
        try:
            frame = book.parse(sheet, nrows=5000)
        except Exception as exc:
            out.append(f"    could not parse: {type(exc).__name__}")
            continue
        out.append(f"    columns ({len(frame.columns)}):")
        for col in frame.columns:
            out.append(_describe_series(str(col), frame[col], show_values))
    return out


def inspect_path(root: Path, show_values: bool) -> list[str]:
    lines = [f"raw data inventory: {root}", "=" * 72]
    if not root.exists():
        lines.append(f"{root} does not exist - nothing to inspect.")
        return lines

    files = sorted(p for p in root.rglob("*") if p.is_file())
    if not files:
        lines.append(f"{root} is empty - nothing to inspect.")
        return lines

    shp_stems = {p.with_suffix("") for p in files if p.suffix.lower() == ".shp"}
    considered = [
        p for p in files if not (p.suffix.lower() in SIDECARS and p.with_suffix("") in shp_stems)
    ]
    lines.append(f"{len(files)} file(s), {len(considered)} after grouping shapefile sidecars\n")

    for path in considered:
        rel = path.relative_to(root)
        suffix = path.suffix.lower()
        lines.append(f"- {rel}  [{_human(path.stat().st_size)}]")

        theme = excluded_theme(path.stem)
        if theme:
            lines.append(f"    {theme} - OUT OF SCOPE, not opened")
            lines.append("")
            continue

        if suffix in OGR_SUFFIXES:
            lines += inspect_ogr(path, show_values)
        elif suffix in TABULAR_SUFFIXES:
            lines += inspect_tabular(path, show_values)
        elif suffix in EXCEL_SUFFIXES:
            lines += inspect_excel(path, show_values)
        elif suffix in ARCHIVE_SUFFIXES:
            lines.append("    archive - extract it in place, then re-run")
        else:
            lines.append(f"    unrecognised extension {suffix!r} - not opened")
        lines.append("")
    return lines
