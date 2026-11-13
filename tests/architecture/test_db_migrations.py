"""Migrations reproduce the section 4.1 schema verbatim under a separate identity (Slice 2; NFR-03, NFR-06).

Separate migration and runtime database accounts (specs/security.md section 3); seed holds only placeholder
application configuration.
"""

from __future__ import annotations

import re

from alembic.config import Config
from alembic.script import ScriptDirectory

from tests._repo import REPO_ROOT, files_under, python_files, read_text, rel, text_files

TABLE_OPTIONS = "ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci"
CREATE_TABLE = re.compile(r"CREATE TABLE \w+ \(.*?\n\);", re.DOTALL)
FORBIDDEN_DDL = re.compile(r"\b(?:GRANT|REVOKE|CREATE\s+USER|ALTER\s+USER|IDENTIFIED\s+BY|CREATE\s+DATABASE)\b", re.I)
RUNTIME_ENV_KEY = re.compile(r"[\"']MYSQL_(?:USER|PASSWORD)[\"']")
EMAIL = re.compile(r"[\w.+-]+@[\w.-]+")


def _normalize(sql: str) -> str:
    return " ".join(sql.split())


def _spec_create_tables() -> list[str]:
    spec = read_text(REPO_ROOT / "specs" / "architecture.md")
    block = spec.split("### 5.1 Core schema", 1)[1].split("```sql", 1)[1].split("```", 1)[0]
    return CREATE_TABLE.findall(block)


def _migration_sources() -> str:
    files = python_files(files_under("db/migrations/versions"))
    assert files, "db/migrations/versions has no migrations"
    return "\n".join(read_text(p) for p in files)


def test_spec_defines_seven_tables() -> None:
    assert len(_spec_create_tables()) == 7


def test_alembic_discovers_single_linear_head() -> None:
    # Guards against silent no-op migrations (e.g. version paths split on spaces in the checkout path).
    script = ScriptDirectory.from_config(Config(str(REPO_ROOT / "db" / "migrations" / "alembic.ini")))
    revisions = list(script.walk_revisions())
    assert script.get_heads() == ["0001"]
    assert [r.revision for r in revisions][-1] == "0001"
    assert revisions[-1].down_revision is None


def test_migrations_create_section_4_1_tables_verbatim_as_innodb_utf8mb4() -> None:
    migrations = _normalize(_migration_sources())
    for statement in _spec_create_tables():
        expected = _normalize(statement.removesuffix(";")) + " " + TABLE_OPTIONS
        assert expected in migrations, f"migration does not reproduce: {statement.splitlines()[0]}"


def test_migrations_have_no_credentials_grants_or_database_creation() -> None:
    violations = [rel(p) for p in text_files(files_under("db/migrations")) if FORBIDDEN_DDL.search(read_text(p))]
    assert not violations, f"identities and databases are provisioned by a DBA, not migrations: {violations}"


def test_migrations_connect_with_migration_identity() -> None:
    env = read_text(REPO_ROOT / "db" / "migrations" / "env.py")
    assert "MIGRATION_MYSQL_USER" in env
    assert "MIGRATION_MYSQL_PASSWORD" in env
    assert not RUNTIME_ENV_KEY.search(env), "migrations must not run as the Release API runtime identity"


def test_release_api_never_uses_migration_identity() -> None:
    files = text_files(files_under("services"))
    violations = [rel(p) for p in files if "MIGRATION_MYSQL" in read_text(p)]
    assert not violations, f"runtime code must not reference the migration identity: {violations}"


def test_env_example_separates_runtime_and_migration_identities() -> None:
    entries = {
        key.strip(): value.strip()
        for key, _, value in (line.partition("=") for line in read_text(REPO_ROOT / ".env.example").splitlines())
        if key.strip() and not key.strip().startswith("#")
    }
    runtime, migrator = entries.get("MYSQL_USER", ""), entries.get("MIGRATION_MYSQL_USER", "")
    assert runtime and migrator, ".env.example must name both identities"
    assert runtime != migrator
    assert "root" not in {runtime.lower(), migrator.lower()}
    assert entries.get("MYSQL_TEST_DATABASE", "").endswith("_test")


def test_seed_files_use_placeholder_addresses_only() -> None:
    files = text_files(files_under("db/seed"))
    assert any(p.suffix == ".yaml" for p in files), "db/seed has no seed files"
    addresses = {rel(p): EMAIL.findall(read_text(p)) for p in files}
    violations = {k: [a for a in v if not a.endswith("@example.com")] for k, v in addresses.items()}
    assert not {k: v for k, v in violations.items() if v}, f"seed must use example.com placeholders: {violations}"
