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


# ---------------------------------------------------------------------------
# Strict skips
#
# Skips are how this suite handles an environment that cannot provide something
# - no NTv2 grid, no PostGIS. That is correct locally and dangerous anywhere the
# environment is supposed to be complete: a stopped database silently turned
# four enforcement tests into skips while the suite still reported green.
#
# `--strict-skips` makes any skip a failure, so CI and a provisioned dev machine
# assert that every check actually ran. `make test` stays lenient;
# `make test-strict` does not.
# ---------------------------------------------------------------------------

_SKIPPED: list[tuple[str, str]] = []


def pytest_addoption(parser):
    parser.addoption(
        "--strict-skips",
        action="store_true",
        default=False,
        help="treat any skipped test as a failure (use where the environment is complete)",
    )


def pytest_runtest_logreport(report):
    if report.skipped:
        reason = ""
        if isinstance(report.longrepr, tuple) and len(report.longrepr) == 3:
            reason = str(report.longrepr[2]).removeprefix("Skipped: ")
        _SKIPPED.append((report.nodeid, reason))


def pytest_sessionfinish(session, exitstatus):
    if not session.config.getoption("--strict-skips") or not _SKIPPED:
        return
    writer = session.config.pluginmanager.get_plugin("terminalreporter")
    if writer is not None:
        writer.write_line("")
        writer.write_line(
            f"STRICT SKIPS: {len(_SKIPPED)} test(s) did not run, and this environment "
            "is supposed to be able to run all of them:",
            red=True,
        )
        for nodeid, reason in _SKIPPED:
            writer.write_line(f"  {nodeid}")
            writer.write_line(f"    {reason}")
        writer.write_line("Run `make doctor` to see which requirement is missing.", red=True)
    session.exitstatus = 1
