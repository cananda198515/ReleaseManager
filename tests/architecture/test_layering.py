"""Layering: Agents -> Release MCP -> Release API -> MySQL. Agents and MCP never touch MySQL (NFR-06, NFR-03).

Only services/release-api and db/migrations may depend on database libraries.
"""

from __future__ import annotations

import re
import tomllib

from tests._repo import (
    REPO_ROOT,
    files_under,
    imported_top_level_modules,
    python_files,
    read_text,
    rel,
    repo_files,
    text_files,
)

DB_MODULES = frozenset({"sqlalchemy", "pymysql", "MySQLdb", "mysql", "aiomysql", "asyncmy", "alembic"})
DB_DISTRIBUTIONS = frozenset(
    {"sqlalchemy", "pymysql", "mysqlclient", "mysql-connector-python", "aiomysql", "asyncmy", "alembic"}
)
DB_ALLOWED_ROOTS = ("services/release-api", "db/migrations", "tests")
DB_REFERENCE = re.compile(
    r"\bmysql(?:\+\w+)?://|\bMYSQL_(?:HOST|PORT|USER|PASSWORD|DATABASE)\b|\bpymysql\b|\bsqlalchemy\b",
    re.IGNORECASE,
)


def _distribution_name(requirement: str) -> str:
    return re.split(r"[\s<>=!~;\[]", requirement, maxsplit=1)[0].strip().lower().replace("_", "-")


def test_mcp_has_no_database_dependency() -> None:
    files = python_files(files_under("services/release-mcp"))
    assert files, "services/release-mcp has no Python sources"
    violations = {
        rel(p): sorted(imported_top_level_modules(p) & (DB_MODULES | {"release_api"})) for p in files
    }
    assert not {k: v for k, v in violations.items() if v}, f"MCP must reach data only via the Release API: {violations}"


def test_mcp_dependencies_exclude_db_drivers() -> None:
    pyproject = tomllib.loads(read_text(REPO_ROOT / "services/release-mcp/pyproject.toml"))
    deps = {_distribution_name(d) for d in pyproject["project"]["dependencies"]}
    assert not deps & DB_DISTRIBUTIONS, f"MCP declares database dependencies: {sorted(deps & DB_DISTRIBUTIONS)}"


def test_agents_skills_hooks_have_no_database_dependency() -> None:
    for directory in ("agents", "skills", "hooks"):
        assert (REPO_ROOT / directory).is_dir(), f"missing directory: {directory}"
    files = files_under("agents", "skills", "hooks")
    import_violations = {rel(p): sorted(imported_top_level_modules(p) & DB_MODULES) for p in python_files(files)}
    text_violations = [rel(p) for p in text_files(files) if DB_REFERENCE.search(read_text(p))]
    assert not {k: v for k, v in import_violations.items() if v}, import_violations
    assert not text_violations, f"agents/skills/hooks reference MySQL directly: {text_violations}"


def test_only_release_api_and_migrations_use_db() -> None:
    allowed = [(REPO_ROOT / r).resolve() for r in DB_ALLOWED_ROOTS]
    violations = {}
    for path in python_files(repo_files()):
        if any(path.resolve().is_relative_to(root) for root in allowed):
            continue
        used = imported_top_level_modules(path) & DB_MODULES
        if used:
            violations[rel(path)] = sorted(used)
    assert not violations, f"database libraries imported outside the Release API: {violations}"


def test_db_reference_detector_flags_connection_strings() -> None:
    assert DB_REFERENCE.search("url = " + "mysql+pymysql" + "://host/db")
    assert DB_REFERENCE.search("MYSQL_" + "HOST")
    assert not DB_REFERENCE.search("Agents never touch the database.")
