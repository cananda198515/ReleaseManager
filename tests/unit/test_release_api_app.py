"""Release API settings and app factory (Slice 1; NFR-03, NFR-09).

Settings load from environment variables only; MYSQL_PASSWORD is required (no default) and never exposed in
repr/str/serialization or logs.
"""

from __future__ import annotations

import logging

import pytest
from pydantic import ValidationError

SENTINEL = "sentinel-value-that-must-never-appear"


@pytest.fixture
def db_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("MYSQL_HOST", "db.internal")
    monkeypatch.setenv("MYSQL_PORT", "3307")
    monkeypatch.setenv("MYSQL_DATABASE", "release_management")
    monkeypatch.setenv("MYSQL_USER", "release_api")
    monkeypatch.setenv("MYSQL_PASSWORD", SENTINEL)


@pytest.mark.usefixtures("db_env")
def test_create_app_returns_fastapi() -> None:
    from fastapi import FastAPI

    from release_api.main import create_app

    assert isinstance(create_app(), FastAPI)


@pytest.mark.usefixtures("db_env")
def test_settings_read_from_environment() -> None:
    from release_api.settings import Settings

    settings = Settings()
    assert settings.app_env == "test"
    assert settings.log_level == "DEBUG"
    assert settings.mysql_host == "db.internal"
    assert settings.mysql_port == 3307
    assert settings.mysql_database == "release_management"
    assert settings.mysql_user == "release_api"
    assert settings.mysql_password.get_secret_value() == SENTINEL


def test_settings_do_not_read_dotenv_files() -> None:
    from release_api.settings import Settings

    assert Settings.model_config.get("env_file") is None


def test_mysql_password_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    from release_api.settings import Settings

    monkeypatch.delenv("MYSQL_PASSWORD", raising=False)
    with pytest.raises(ValidationError) as excinfo:
        Settings()
    assert "mysql_password" in str(excinfo.value).lower()


@pytest.mark.usefixtures("db_env")
def test_validation_errors_do_not_echo_password(monkeypatch: pytest.MonkeyPatch) -> None:
    from release_api.settings import Settings

    monkeypatch.setenv("MYSQL_PORT", "not-a-port")
    with pytest.raises(ValidationError) as excinfo:
        Settings()
    assert SENTINEL not in str(excinfo.value)
    assert SENTINEL not in repr(excinfo.value.errors())


@pytest.mark.usefixtures("db_env")
def test_mysql_password_is_masked() -> None:
    from release_api.settings import Settings

    settings = Settings()
    for rendered in (repr(settings), str(settings), settings.model_dump_json(), str(settings.model_dump())):
        assert SENTINEL not in rendered


@pytest.mark.usefixtures("db_env")
def test_mysql_password_never_logged(caplog: pytest.LogCaptureFixture) -> None:
    from fastapi.testclient import TestClient

    from release_api.main import create_app

    with caplog.at_level(logging.DEBUG):
        with TestClient(create_app()) as client:
            client.get("/health")
    assert SENTINEL not in caplog.text

