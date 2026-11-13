"""MySQL engine factory (Slice 2; NFR-03, NFR-06).

Every pooled connection is forced to UTC and strict SQL mode so timestamps are UTC and invalid enum/length/NOT NULL
values are rejected regardless of server defaults. Passwords are never rendered: SQLAlchemy URLs mask them in repr/str.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import URL, Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from release_api.settings import Settings

SESSION_SQL_MODE = (
    "STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION"
)
SESSION_INIT_STATEMENTS = (
    "SET time_zone = '+00:00'",
    f"SET SESSION sql_mode = '{SESSION_SQL_MODE}'",
)


def mysql_url(*, user: str, password: str, host: str, port: int, database: str) -> URL:
    return URL.create(
        drivername="mysql+pymysql",
        username=user,
        password=password,
        host=host,
        port=port,
        database=database,
        query={"charset": "utf8mb4"},
    )


def database_url(settings: Settings) -> URL:
    """Runtime identity URL built from Release API settings."""
    host, database, user = settings.mysql_host, settings.mysql_database, settings.mysql_user
    if not (host and database and user):
        missing = [
            name
            for name, value in (("MYSQL_HOST", host), ("MYSQL_DATABASE", database), ("MYSQL_USER", user))
            if not value
        ]
        raise ValueError(f"database settings missing: {', '.join(missing)}")
    return mysql_url(
        user=user,
        password=settings.mysql_password.get_secret_value(),
        host=host,
        port=settings.mysql_port,
        database=database,
    )


def apply_session_defaults(dbapi_connection: Any, _connection_record: Any) -> None:
    cursor = dbapi_connection.cursor()
    try:
        for statement in SESSION_INIT_STATEMENTS:
            cursor.execute(statement)
    finally:
        cursor.close()


def create_db_engine(url: URL, **kwargs: Any) -> Engine:
    engine = create_engine(url, pool_pre_ping=True, **kwargs)
    event.listen(engine, "connect", apply_session_defaults)
    return engine


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)
