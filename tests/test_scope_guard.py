"""Scope rules, enforced rather than described.

Two exclusions from CLAUDE.md: no spring/soakage/sacred-site layers, and no FME
workspaces. Both are checked at runtime where a layer is written, and swept for
across the repository here so an accidental addition fails the build.
"""

from __future__ import annotations

import re

import geopandas as gpd
import pytest
from shapely.geometry import Point

from ntgw.crs import ATLAS_EPSG
from ntgw.export.gpkg import write_layers
from ntgw.scope import EXCLUDED_EXTENSIONS, ExcludedLayerError, check_layer_names, excluded_theme

SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".ruff_cache", "data"}


def _repo_files(root):
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        yield path


@pytest.mark.parametrize(
    "name", ["springs", "spring_points", "soakages", "sacred_sites", "SacredSite", "soak"]
)
def test_excluded_layer_names_are_recognised(name):
    assert excluded_theme(name) is not None


@pytest.mark.parametrize(
    "name", ["bore", "water_level", "licence", "wcd_boundary", "offspring_survey", "springfield_rd"]
)
def test_ordinary_layer_names_are_not_caught(name):
    """The guard must not fire on words that merely contain an excluded token."""
    assert excluded_theme(name) is None


def test_check_layer_names_raises_on_excluded():
    with pytest.raises(ExcludedLayerError):
        check_layer_names(["bore", "sacred_sites"])


def test_geopackage_export_refuses_an_excluded_layer(tmp_path):
    gdf = gpd.GeoDataFrame(
        {"id": [1]}, geometry=[Point(400_000, 7_600_000)], crs=f"EPSG:{ATLAS_EPSG}"
    )
    with pytest.raises(ExcludedLayerError):
        write_layers(tmp_path / "out.gpkg", {"springs": gdf})


def test_no_fme_workspaces_in_the_repository(repo_root):
    offenders = [
        p.relative_to(repo_root)
        for p in _repo_files(repo_root)
        if p.suffix.lower() in EXCLUDED_EXTENSIONS
    ]
    assert not offenders, f"FME workspaces are out of scope: {offenders}"


def test_no_excluded_themes_in_filenames(repo_root):
    offenders = [
        p.relative_to(repo_root)
        for p in _repo_files(repo_root)
        if excluded_theme(p.stem) and "scope" not in p.stem
    ]
    assert not offenders, f"files naming excluded themes: {offenders}"


def test_no_excluded_themes_among_database_objects(repo_root):
    """Sweep the DDL for table/view names in an excluded theme."""
    offenders = []
    for path in _repo_files(repo_root):
        if path.suffix.lower() != ".sql":
            continue
        for match in re.finditer(
            r"CREATE\s+(?:OR\s+REPLACE\s+)?(?:TABLE|VIEW|MATERIALIZED\s+VIEW)\s+"
            r"(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z_][A-Za-z0-9_]*)",
            path.read_text(),
            re.IGNORECASE,
        ):
            name = match.group(1)
            if excluded_theme(name):
                offenders.append(f"{path.name}:{name}")
    assert not offenders, f"database objects in excluded themes: {offenders}"


def test_excluded_themes_are_not_silently_widened():
    """Changing the exclusion list should be a deliberate, visible edit."""
    from ntgw.scope import EXCLUDED_THEMES

    assert set(EXCLUDED_THEMES) == {"spring", "soakage", "sacred"}
