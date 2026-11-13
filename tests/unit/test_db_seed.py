"""Seed loads only application configuration, only in dev/test (Slice 2; BR-15, NFR-06, NFR-09)."""

from __future__ import annotations

from pathlib import Path

import pytest

from release_api.db.seed import ALLOWED_SEED_ENVIRONMENTS, SeedError, load_seed_rows
from tests._repo import REPO_ROOT

VALID_ROW = "  - application_key: app-a\n    display_name: App A\n"


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "seed.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def test_seed_environments_are_dev_and_test_only() -> None:
    assert frozenset({"dev", "test"}) == ALLOWED_SEED_ENVIRONMENTS


@pytest.mark.parametrize("app_env", sorted(ALLOWED_SEED_ENVIRONMENTS))
def test_repository_seed_files_load(app_env: str) -> None:
    rows = load_seed_rows(REPO_ROOT / "db" / "seed" / f"{app_env}.yaml", app_env=app_env)
    assert rows
    assert all(row["application_key"] and row["display_name"] for row in rows)


@pytest.mark.parametrize("app_env", ["prod", "production", "staging", ""])
def test_seed_refuses_non_dev_test_environments(tmp_path: Path, app_env: str) -> None:
    path = _write(tmp_path, f"appEnv: {app_env or 'x'}\napplication_config:\n{VALID_ROW}")
    with pytest.raises(SeedError, match="dev"):
        load_seed_rows(path, app_env=app_env)


def test_seed_refuses_file_for_other_environment(tmp_path: Path) -> None:
    path = _write(tmp_path, f"appEnv: test\napplication_config:\n{VALID_ROW}")
    with pytest.raises(SeedError, match="appEnv"):
        load_seed_rows(path, app_env="dev")


def test_seed_refuses_other_tables(tmp_path: Path) -> None:
    body = f"appEnv: dev\napplication_config:\n{VALID_ROW}release_request:\n  - release_id: REL-20260101-0001\n"
    with pytest.raises(SeedError, match="application_config"):
        load_seed_rows(_write(tmp_path, body), app_env="dev")


def test_seed_refuses_unknown_columns(tmp_path: Path) -> None:
    body = f"appEnv: dev\napplication_config:\n{VALID_ROW}    approve_all: true\n"
    with pytest.raises(SeedError, match="approve_all"):
        load_seed_rows(_write(tmp_path, body), app_env="dev")


def test_seed_requires_key_and_display_name(tmp_path: Path) -> None:
    body = "appEnv: dev\napplication_config:\n  - application_key: app-a\n"
    with pytest.raises(SeedError, match="display_name"):
        load_seed_rows(_write(tmp_path, body), app_env="dev")


def test_seed_requires_rows(tmp_path: Path) -> None:
    with pytest.raises(SeedError):
        load_seed_rows(_write(tmp_path, "appEnv: dev\napplication_config: []\n"), app_env="dev")
