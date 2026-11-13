"""Dev/test seed for application configuration only (Slice 2; BR-15, NFR-06, NFR-09).

Usage (dev/test only, runtime identity from environment variables):
    python -m release_api.db.seed --file db/seed/dev.yaml

Seed files hold placeholder application_config rows; release, approval, evidence and audit data are never seeded.
The file's ``appEnv`` must match ``APP_ENV`` and both must be dev or test.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import Connection
from sqlalchemy.dialects.mysql import insert

from release_api.db.engine import create_db_engine, database_url
from release_api.db.models import Base
from release_api.settings import Settings

SEED_TABLE = "application_config"
ALLOWED_SEED_ENVIRONMENTS = frozenset({"dev", "test"})
REQUIRED_SEED_COLUMNS = ("application_key", "display_name")


class SeedError(ValueError):
    pass


def load_seed_rows(path: Path, *, app_env: str) -> list[dict[str, Any]]:
    if app_env not in ALLOWED_SEED_ENVIRONMENTS:
        raise SeedError(f"seeding is allowed only in dev/test, not {app_env!r}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or set(data) != {"appEnv", SEED_TABLE}:
        raise SeedError(f"seed file must contain exactly 'appEnv' and '{SEED_TABLE}'")
    if data["appEnv"] != app_env:
        raise SeedError(f"seed file appEnv {data['appEnv']!r} does not match APP_ENV {app_env!r}")
    rows = data[SEED_TABLE]
    if not isinstance(rows, list) or not rows:
        raise SeedError(f"'{SEED_TABLE}' must be a non-empty list")
    columns = set(Base.metadata.tables[SEED_TABLE].columns.keys())
    for row in rows:
        if not isinstance(row, dict):
            raise SeedError(f"each '{SEED_TABLE}' entry must be a mapping")
        unknown = sorted(set(row) - columns)
        if unknown:
            raise SeedError(f"unknown {SEED_TABLE} columns: {', '.join(unknown)}")
        absent = [c for c in REQUIRED_SEED_COLUMNS if not row.get(c)]
        if absent:
            raise SeedError(f"{SEED_TABLE} entry missing: {', '.join(absent)}")
    return rows


def apply_seed(connection: Connection, rows: Sequence[dict[str, Any]]) -> int:
    """Idempotent upsert keyed by application_key."""
    table = Base.metadata.tables[SEED_TABLE]
    for row in rows:
        statement = insert(table).values(**row)
        updates = {k: statement.inserted[k] for k in row if k != "application_key"}
        connection.execute(statement.on_duplicate_key_update(**updates))
    return len(rows)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--file", type=Path, required=True)
    args = parser.parse_args(argv)
    settings = Settings()
    rows = load_seed_rows(args.file, app_env=settings.app_env)
    engine = create_db_engine(database_url(settings))
    try:
        with engine.begin() as connection:
            count = apply_seed(connection, rows)
    finally:
        engine.dispose()
    print(f"seeded {count} {SEED_TABLE} row(s) for {settings.app_env}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
