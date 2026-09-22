#!/usr/bin/env python
"""Report whether this environment can actually run the atlas.

Exits non-zero if a hard requirement is missing. The NTv2 grid is a hard
requirement: without it, any GDA94 source is untransformable by the project's
own rules.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

OK, BAD, WARN = "  ok  ", " FAIL ", " warn "


def main() -> int:
    failures = 0

    import pyproj

    print(f"[{OK}] pyproj {pyproj.__version__} / PROJ {pyproj.proj_version_str}")

    from ntgw.crs import ATLAS_EPSG, DEFAULT_GRID, grid_status

    status = grid_status()
    if status.available:
        print(f"[{OK}] NTv2 grid {DEFAULT_GRID} available via {status.operation!r}")
    else:
        failures += 1
        print(f"[{BAD}] NTv2 grid {DEFAULT_GRID} NOT installed")
        print("         GDA94 sources cannot be transformed. Install it with:")
        print("           conda install -c conda-forge proj-data")
        print("         PROJ would otherwise fall back to a Helmert approximation,")
        print("         which this project refuses to use.")

    from pyproj import CRS

    print(f"[{OK}] atlas CRS EPSG:{ATLAS_EPSG} = {CRS.from_epsg(ATLAS_EPSG).name}")

    try:
        from sqlalchemy import text

        from ntgw.db import database_url, get_engine

        with get_engine().connect() as conn:
            version = conn.execute(text("SELECT postgis_version()")).scalar_one()
        print(f"[{OK}] PostGIS reachable ({version}) at {database_url().split('@')[-1]}")
    except Exception as exc:
        print(f"[{WARN}] PostGIS not reachable: {type(exc).__name__}")
        print("         run `make db-up` before the database tests")

    hook = Path(".git/hooks/pre-commit")
    if hook.exists():
        print(f"[{OK}] data-commit guard installed")
    else:
        failures += 1
        print(f"[{BAD}] pre-commit data guard missing - run `make install-hooks`")

    raw = Path("data/raw")
    files = sorted(p.name for p in raw.iterdir()) if raw.is_dir() else []
    if files:
        print(f"[{OK}] data/raw contains {len(files)} file(s)")
    else:
        print(f"[{WARN}] data/raw is empty - ingest mappings cannot be written yet")

    print()
    if failures:
        print(f"{failures} hard requirement(s) missing.")
    else:
        print("environment OK")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
