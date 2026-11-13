"""Alembic environment (Slice 1 skeleton; the section 4.1 schema arrives in Slice 2). NFR-03, NFR-06.

The connection URL is built at runtime from environment variables populated by the approved secret provider; no
credentials live in this repository. Migrations run under a separate identity from the Release API runtime (Slice 2).
"""

from __future__ import annotations

import os

from alembic import context
from sqlalchemy import URL, MetaData, create_engine, pool

target_metadata: MetaData | None = None


def _database_url() -> URL:
    return URL.create(
        drivername="mysql+pymysql",
        username=os.environ["MYSQL_USER"],
        password=os.environ["MYSQL_PASSWORD"],
        host=os.environ["MYSQL_HOST"],
        port=int(os.environ.get("MYSQL_PORT", "3306")),
        database=os.environ["MYSQL_DATABASE"],
        query={"charset": "utf8mb4"},
    )


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url().render_as_string(hide_password=True),
        target_metadata=target_metadata,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_database_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
