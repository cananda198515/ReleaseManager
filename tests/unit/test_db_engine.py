"""Database engine: UTC, strict SQL mode, utf8mb4 and masked credentials (Slice 2; NFR-03, NFR-06)."""

from __future__ import annotations

import pytest
from pydantic import SecretStr
from sqlalchemy import event

from release_api.db.engine import (
    SESSION_INIT_STATEMENTS,
    apply_session_defaults,
    create_db_engine,
    database_url,
    mysql_url,
)
from release_api.settings import Settings

MASK_PROBE = "not-a-real-value-123"  # test-only value proving the password is masked


class _FakeCursor:
    def __init__(self) -> None:
        self.executed: list[str] = []
        self.closed = False

    def execute(self, statement: str) -> None:
        self.executed.append(statement)

    def close(self) -> None:
        self.closed = True


class _FakeConnection:
    def __init__(self) -> None:
        self.cursor_obj = _FakeCursor()

    def cursor(self) -> _FakeCursor:
        return self.cursor_obj


def _url_kwargs() -> dict[str, str | int]:
    return {"user": "release_api", "host": "127.0.0.1", "port": 3306, "database": "release_management"}


def test_mysql_url_uses_pymysql_and_utf8mb4() -> None:
    url = mysql_url(password=MASK_PROBE, **_url_kwargs())  # type: ignore[arg-type]
    assert url.drivername == "mysql+pymysql"
    assert url.query["charset"] == "utf8mb4"


def test_mysql_url_never_renders_password() -> None:
    url = mysql_url(password=MASK_PROBE, **_url_kwargs())  # type: ignore[arg-type]
    assert MASK_PROBE not in repr(url)
    assert MASK_PROBE not in str(url)


def test_database_url_from_settings_uses_runtime_identity() -> None:
    settings = Settings(
        mysql_host="127.0.0.1",
        mysql_database="release_management",
        mysql_user="release_api",
        mysql_password=SecretStr(MASK_PROBE),
    )
    url = database_url(settings)
    assert url.username == "release_api"
    assert url.database == "release_management"
    assert url.password == MASK_PROBE


@pytest.mark.parametrize("missing", ["mysql_host", "mysql_database", "mysql_user"])
def test_database_url_requires_connection_settings(missing: str, monkeypatch: pytest.MonkeyPatch) -> None:
    # Settings also reads the environment, so clear it to make the omitted value genuinely missing.
    monkeypatch.delenv(missing.upper(), raising=False)
    values: dict[str, str] = {
        "mysql_host": "127.0.0.1",
        "mysql_database": "release_management",
        "mysql_user": "release_api",
    }
    del values[missing]
    settings = Settings(mysql_password=SecretStr(MASK_PROBE), **values)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match=missing.upper()) as excinfo:
        database_url(settings)
    assert MASK_PROBE not in str(excinfo.value)


def test_session_defaults_force_utc_and_strict_mode() -> None:
    joined = " ".join(SESSION_INIT_STATEMENTS)
    assert "time_zone = '+00:00'" in joined
    assert "STRICT_TRANS_TABLES" in joined


def test_apply_session_defaults_executes_statements_and_closes_cursor() -> None:
    connection = _FakeConnection()
    apply_session_defaults(connection, None)
    assert connection.cursor_obj.executed == list(SESSION_INIT_STATEMENTS)
    assert connection.cursor_obj.closed


def test_create_db_engine_registers_session_defaults() -> None:
    engine = create_db_engine(mysql_url(password=MASK_PROBE, **_url_kwargs()))  # type: ignore[arg-type]
    try:
        assert event.contains(engine, "connect", apply_session_defaults)
        assert MASK_PROBE not in repr(engine)
    finally:
        engine.dispose()
