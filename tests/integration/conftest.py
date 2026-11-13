"""MySQL integration fixtures (Slice 2; NFR-06).

Tests run against a disposable database whose name must end in ``_test``. Schema changes and cleanup use the migration
identity; least-privilege checks use the runtime identity. Without the variables below the tests skip with an
explicit reason: CI has no MySQL service yet (specs/slices.md open question #28).
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import URL, Engine, text

from release_api.db.engine import create_db_engine, mysql_url
from tests._repo import REPO_ROOT

MIGRATOR_VARS = ("MYSQL_HOST", "MYSQL_TEST_DATABASE", "MIGRATION_MYSQL_USER", "MIGRATION_MYSQL_PASSWORD")
RUNTIME_VARS = ("MYSQL_USER", "MYSQL_PASSWORD")
TABLES_CHILD_FIRST = (
    "release_transition",
    "release_evidence",
    "release_approval",
    "release_component",
    "idempotency_record",
    "application_config",
    "release_request",
)


def _require(names: tuple[str, ...]) -> None:
    missing = [name for name in names if not os.environ.get(name)]
    if missing:
        pytest.skip(
            f"MySQL integration test skipped: set {', '.join(missing)} (README 'Integration tests'); "
            "CI has no MySQL service yet (specs/slices.md open question #28)"
        )


def _url(user_var: str, password_var: str) -> URL:
    return mysql_url(
        user=os.environ[user_var],
        password=os.environ[password_var],
        host=os.environ["MYSQL_HOST"],
        port=int(os.environ.get("MYSQL_PORT", "3306")),
        database=os.environ["MYSQL_TEST_DATABASE"],
    )


def run_alembic(engine: Engine, action: Callable[[Config, str], None], revision: str) -> None:
    config = Config(str(REPO_ROOT / "db" / "migrations" / "alembic.ini"))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        action(config, revision)


def clear_tables(engine: Engine) -> None:
    with engine.begin() as connection:
        for table in TABLES_CHILD_FIRST:
            connection.execute(text(f"DELETE FROM {table}"))  # noqa: S608 - fixed table names, no input


@pytest.fixture(scope="session")
def migrator_engine() -> Iterator[Engine]:
    _require(MIGRATOR_VARS)
    database = os.environ["MYSQL_TEST_DATABASE"]
    if not database.endswith("_test"):
        pytest.fail(f"MYSQL_TEST_DATABASE must end with '_test'; refusing to migrate/clear {database!r}")
    engine = create_db_engine(_url("MIGRATION_MYSQL_USER", "MIGRATION_MYSQL_PASSWORD"))
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def migrated(migrator_engine: Engine) -> Engine:
    run_alembic(migrator_engine, command.upgrade, "head")
    return migrator_engine


@pytest.fixture
def db(migrated: Engine) -> Iterator[Engine]:
    clear_tables(migrated)
    yield migrated
    clear_tables(migrated)


@pytest.fixture(scope="session")
def runtime_engine(migrated: Engine) -> Iterator[Engine]:
    _require(RUNTIME_VARS)
    engine = create_db_engine(_url("MYSQL_USER", "MYSQL_PASSWORD"))
    yield engine
    engine.dispose()
