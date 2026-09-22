"""Coordinate reference system policy for the atlas.

Two rules are enforced here, both from CLAUDE.md:

1.  Everything is EPSG:7853 (GDA2020 / MGA zone 53).
2.  GDA94 -> GDA2020 goes through the ICSM NTv2 grid, never a Helmert
    approximation, and a missing grid is a loud failure.

Rule 2 needs more than it looks like it needs. PROJ knows three GDA94 ->
GDA2020 operations: a 7-parameter Helmert ("GDA94 to GDA2020 (1)") and two
grid-based ones. The Helmert is always available because it carries no grid,
and PROJ ranks it as usable with a stated accuracy of 0.01 m, so:

    Transformer.from_crs(4283, 7853, only_best=True, allow_ballpark=False)

returns the *Helmert* and raises nothing at all when the grid is absent. It is
not a ballpark transform, so `allow_ballpark=False` does not see it, and PROJ
considers it the best *available* operation, so `only_best=True` does not see
it either. Neither guard catches the case this module exists to catch.

The only reliable enforcement is to name the grid we require, locate the
operation that uses it, and refuse to proceed if that grid is not installed.
That is what `transformer_to_atlas` does.
"""

from __future__ import annotations

from dataclasses import dataclass

from pyproj import CRS
from pyproj.transformer import Transformer, TransformerGroup

#: Every table, every export, every intermediate.
ATLAS_EPSG = 7853

#: Coordinates that are plausibly MGA zone 53, used to catch a wrongly declared
#: source CRS. A bad declaration transforms without error and lands the data
#: somewhere absurd, so the check is on the result, not the declaration.
#:
#: Derived, not guessed: zone 53 spans 132-138E, widened by the one-degree
#: overlap real data uses, over NT latitudes 26S-10S, then rounded outward.
MGA53_ENVELOPE = {
    "min_x": 60_000.0,
    "max_x": 940_000.0,
    "min_y": 7_100_000.0,
    "max_y": 8_900_000.0,
}

#: ICSM GDA94 -> GDA2020 grids, as PROJ names them. PROJ >= 7 distributes the
#: NTv2 grids repackaged as GeoTIFF; the legacy .gsb names are accepted too so
#: that a hand-installed ICSM download is still recognised.
CONFORMAL_GRID = "au_icsm_GDA94_GDA2020_conformal"
CONFORMAL_DISTORTION_GRID = "au_icsm_GDA94_GDA2020_conformal_and_distortion"

#: Project default. Conformal is the right choice unless the coordinates were
#: propagated from AGD66/AGD84, in which case conformal+distortion applies.
DEFAULT_GRID = CONFORMAL_GRID

_GDA94_DATUM_KEYS = ("GDA94", "Geocentric Datum of Australia 1994")
_GDA2020_DATUM_KEYS = ("GDA2020", "Geocentric Datum of Australia 2020")


class CrsPolicyError(Exception):
    """Base class for CRS policy violations."""


class MissingNTv2GridError(CrsPolicyError):
    """The required ICSM NTv2 grid is not installed."""


class UnsupportedSourceDatumError(CrsPolicyError):
    """Source datum has no approved path to the atlas CRS."""


class WrongCrsError(CrsPolicyError):
    """Something is not in EPSG:7853."""


class OutsideZoneError(CrsPolicyError):
    """Transformed coordinates do not fall in MGA zone 53."""


def _grid_names(operation) -> list[str]:
    return [g.short_name for g in getattr(operation, "grids", []) or []]


def _stem(name: str) -> str:
    """Strip a grid file extension so .tif and .gsb spellings compare equal."""
    for ext in (".tif", ".tiff", ".gsb"):
        if name.lower().endswith(ext):
            return name[: -len(ext)]
    return name


def _datum_family(crs: CRS) -> str:
    """Return 'GDA94', 'GDA2020' or 'other' for a CRS."""
    names = [crs.name]
    datum = crs.datum
    if datum is not None:
        names.append(datum.name)
    geodetic = crs.geodetic_crs
    if geodetic is not None:
        names.append(geodetic.name)
        if geodetic.datum is not None:
            names.append(geodetic.datum.name)
    blob = " | ".join(n for n in names if n)
    # GDA2020 first: "GDA2020" contains no "GDA94" substring, but check the
    # more specific label first regardless so ordering never matters.
    if any(k in blob for k in _GDA2020_DATUM_KEYS):
        return "GDA2020"
    if any(k in blob for k in _GDA94_DATUM_KEYS):
        return "GDA94"
    return "other"


@dataclass(frozen=True)
class GridStatus:
    """What PROJ can see of a named grid, for diagnostics and for tests."""

    grid: str
    available: bool
    operation: str | None
    candidates: tuple[str, ...]

    def describe(self) -> str:
        if self.available:
            return f"{self.grid}: available via {self.operation!r}"
        return f"{self.grid}: NOT INSTALLED (PROJ knows of it but cannot load it)"


def grid_status(grid: str = DEFAULT_GRID, source_epsg: int = 4283) -> GridStatus:
    """Report whether `grid` is installed, without raising.

    Looks at both available and unavailable operations so the caller can tell
    "PROJ has never heard of this grid" apart from "the grid exists but is not
    downloaded".
    """
    group = TransformerGroup(CRS.from_epsg(source_epsg), CRS.from_epsg(ATLAS_EPSG))
    want = _stem(grid)
    seen: list[str] = []

    for transformer in group.transformers:
        for op in getattr(transformer, "operations", []) or []:
            for name in _grid_names(op):
                seen.append(name)
                if _stem(name) == want:
                    return GridStatus(grid, True, transformer.description, tuple(seen))

    for op in group.unavailable_operations:
        for name in _grid_names(op):
            seen.append(name)
            if _stem(name) == want:
                return GridStatus(grid, False, op.name, tuple(seen))

    return GridStatus(grid, False, None, tuple(seen))


def _install_hint(grid: str) -> str:
    return (
        f"The ICSM NTv2 grid {grid!r} is required to transform GDA94 to GDA2020 "
        f"but is not installed.\n"
        f"  conda-forge:  conda install -c conda-forge proj-data\n"
        f"  or:           python -m pyproj sync --source-id au_icsm\n"
        f"Refusing to fall back to the 7-parameter Helmert transform "
        f"('GDA94 to GDA2020 (1)'), which PROJ would otherwise use silently."
    )


def require_ntv2_grid(grid: str = DEFAULT_GRID) -> GridStatus:
    """Raise `MissingNTv2GridError` unless `grid` is installed."""
    status = grid_status(grid)
    if not status.available:
        raise MissingNTv2GridError(_install_hint(grid))
    return status


def transformer_uses_grid(transformer: Transformer, grid: str) -> bool:
    """True if `transformer`'s resolved pipeline actually loads `grid`.

    Checks the operation metadata and the PROJ pipeline string, because a
    pipeline built by hand carries `+grids=` but no operation metadata.
    """
    want = _stem(grid)
    for op in getattr(transformer, "operations", []) or []:
        if any(_stem(n) == want for n in _grid_names(op)):
            return True
    try:
        proj4 = transformer.to_proj4()
    except Exception:  # pragma: no cover - some pipelines cannot be serialised
        return False
    return proj4 is not None and want in proj4


def transformer_to_atlas(source_crs: CRS | int | str, grid: str = DEFAULT_GRID) -> Transformer:
    """Return a transformer from `source_crs` to EPSG:7853, grid-backed.

    GDA94 sources must go through the NTv2 grid; a missing grid raises rather
    than degrading to the Helmert transform. GDA2020 sources need no datum
    shift and are projected directly. Any other datum raises, rather than
    being quietly ballparked into the atlas.
    """
    src = source_crs if isinstance(source_crs, CRS) else CRS.from_user_input(source_crs)
    dst = CRS.from_epsg(ATLAS_EPSG)
    family = _datum_family(src)

    if family == "GDA2020":
        return Transformer.from_crs(src, dst, allow_ballpark=False)

    if family != "GDA94":
        raise UnsupportedSourceDatumError(
            f"Source CRS {src.name!r} is neither GDA94 nor GDA2020. There is no approved "
            f"transformation to EPSG:{ATLAS_EPSG} for it, and guessing one would put an "
            f"unquantified datum shift into the atlas. Declare the correct source CRS, or "
            f"extend ntgw.crs with a reviewed transformation path."
        )

    require_ntv2_grid(grid)

    group = TransformerGroup(src, dst)
    want = _stem(grid)
    for transformer in group.transformers:
        for op in getattr(transformer, "operations", []) or []:
            if any(_stem(n) == want for n in _grid_names(op)):
                return transformer

    # The grid reported as available but no operation used it: refuse rather
    # than hand back PROJ's default (Helmert) pick.
    raise MissingNTv2GridError(
        f"Grid {grid!r} reports as available but no GDA94 -> GDA2020 operation uses it. "
        f"Refusing to fall back to a non-grid transformation.\n" + _install_hint(grid)
    )


def assert_atlas_crs(crs: CRS | int | str | None, what: str = "object") -> None:
    """Raise `WrongCrsError` unless `crs` is EPSG:7853."""
    if crs is None:
        raise WrongCrsError(f"{what} has no CRS; expected EPSG:{ATLAS_EPSG}")
    parsed = crs if isinstance(crs, CRS) else CRS.from_user_input(crs)
    epsg = parsed.to_epsg()
    if epsg != ATLAS_EPSG:
        raise WrongCrsError(
            f"{what} is EPSG:{epsg if epsg else parsed.name!r}, expected EPSG:{ATLAS_EPSG} "
            f"(GDA2020 / MGA zone 53)"
        )


def assert_within_zone53(bounds, what: str = "layer") -> None:
    """Raise `OutsideZoneError` if `bounds` is not plausibly MGA zone 53.

    `bounds` is (minx, miny, maxx, maxy) in EPSG:7853. This catches the failure
    a CRS check cannot: a source whose declared CRS is simply wrong transforms
    cleanly and produces coordinates that are nowhere near the Northern
    Territory, with nothing downstream to notice.
    """
    minx, miny, maxx, maxy = bounds
    e = MGA53_ENVELOPE
    if minx < e["min_x"] or maxx > e["max_x"] or miny < e["min_y"] or maxy > e["max_y"]:
        raise OutsideZoneError(
            f"{what} lands outside MGA zone 53 after transformation: "
            f"x {minx:.6g}..{maxx:.6g}, y {miny:.6g}..{maxy:.6g}, expected "
            f"x {e['min_x']:.6g}..{e['max_x']:.6g}, y {e['min_y']:.6g}..{e['max_y']:.6g}. "
            f"The declared source CRS is probably wrong - a wrong declaration "
            f"transforms without error."
        )
