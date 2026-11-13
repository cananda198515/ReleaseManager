"""Repository layout matches the Slice 1 scaffold (specs/architecture.md section 4; NFR-09)."""

from __future__ import annotations

import pytest

from tests._repo import REPO_ROOT

REQUIRED_DIRECTORIES = [
    "services/release-api",
    "services/release-mcp",
    "policies",
    "config/environments",
    "db/migrations",
    "db/seed",
    "agents",
    "skills",
    "hooks/before-tool-call",
    "hooks/after-tool-call",
    "hooks/before-final-response",
    "hooks/on-error",
    "tests/unit",
    "tests/integration",
    "tests/policy",
    "tests/prompt-injection",
    "tests/golden",
    "tests/architecture",
    ".github/workflows",
    "scripts",
]

REQUIRED_FILES = [
    "README.md",
    ".env.example",
    ".pre-commit-config.yaml",
    "config/environments/dev.yaml",
    "config/environments/test.yaml",
    "config/environments/prod.yaml",
    "services/release-api/Dockerfile",
    "services/release-api/pyproject.toml",
    "services/release-mcp/Dockerfile",
    "services/release-mcp/pyproject.toml",
    "db/migrations/alembic.ini",
    "db/migrations/env.py",
    ".github/workflows/validate.yml",
    ".github/workflows/build.yml",
    ".github/workflows/security.yml",
    "scripts/bootstrap.ps1",
    "scripts/bootstrap.sh",
    "scripts/validate.ps1",
]


@pytest.mark.parametrize("relative_dir", REQUIRED_DIRECTORIES)
def test_required_directories_exist(relative_dir: str) -> None:
    assert (REPO_ROOT / relative_dir).is_dir(), f"missing directory: {relative_dir}"


@pytest.mark.parametrize("relative_file", REQUIRED_FILES)
def test_required_files_exist(relative_file: str) -> None:
    assert (REPO_ROOT / relative_file).is_file(), f"missing file: {relative_file}"
