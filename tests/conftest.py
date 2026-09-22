from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return ROOT


def _database_available() -> bool:
    try:
        from sqlalchemy import text

        from ntgw.db import get_engine

        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


@pytest.fixture(scope="session")
def engine():
    """A PostGIS engine with the schema applied, or skip."""
    if os.environ.get("NTGW_SKIP_DB"):
        pytest.skip("NTGW_SKIP_DB set")
    if not _database_available():
        pytest.skip(
            "no PostGIS reachable at NTGW_DATABASE_URL - run `make db-up` "
            "(docker compose) before the database tests"
        )
    from ntgw.db import apply_schema, get_engine

    eng = get_engine()
    apply_schema(eng, str(ROOT / "sql" / "001_schema.sql"))
    return eng


@pytest.fixture(scope="session")
def grid_installed() -> bool:
    from ntgw.crs import grid_status

    return grid_status().available
