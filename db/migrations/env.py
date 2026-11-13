"""Alembic environment for the section 4.1 schema (Slice 2; NFR-03, NFR-06).

Migrations run under the dedicated migration identity (MIGRATION_MYSQL_USER / MIGRATION_MYSQL_PASSWORD), never the
Release API runtime identity, which has no DDL privileges. Values come from environment variables populated by the
approved secret provider; no credentials live in this repository. Sessions are forced to UTC and strict SQL mode.
Tests may supply an open connection through ``config.attributes["connection"]``.
"""

from __future__ import annotations

import os

from alembic import context
from sqlalchemy import URL, Connection, pool

from release_api.db.engine import create_db_engine, mysql_url
from release_api.db.models import Base

target_metadata = Base.metadata


def _database_url() -> URL:
    return mysql_url(
        user=os.environ["MIGRATION_MYSQL_USER"],
        password=os.environ["MIGRATION_MYSQL_PASSWORD"],
        host=os.environ["MYSQL_HOST"],
        port=int(os.environ.get("MYSQL_PORT", "3306")),
        database=os.environ["MYSQL_DATABASE"],
    )


def _run(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url().render_as_string(hide_password=True),
        target_metadata=target_metadata,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    supplied = context.config.attributes.get("connection")
    if supplied is not None:
        _run(supplied)
        return
    engine = create_db_engine(_database_url(), poolclass=pool.NullPool)
    try:
        with engine.connect() as connection:
            _run(connection)
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
