"""The state-machine/gate domain is pure: no web, database, HTTP, LLM, MCP or API-layer dependencies (Slice 3).

Gates and transitions live in deterministic code (AGENTS.md rule b; section 18.2). The domain may import only the
standard library, PyYAML (policy loading) and its own package.
Requirements: NFR-01, NFR-02, NFR-03; AC-RM-04.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from tests._repo import REPO_ROOT, read_text, rel

DOMAIN_DIR = REPO_ROOT / "services" / "release-api" / "src" / "release_api" / "domain"
FORBIDDEN_TOP_LEVEL = frozenset(
    {"fastapi", "starlette", "sqlalchemy", "pymysql", "alembic", "httpx", "requests", "aiohttp", "urllib3",
     "openai", "anthropic", "langchain", "semantic_kernel", "pydantic_settings"}
)
FORBIDDEN_PREFIXES = ("release_api.api", "release_api.mcp", "release_api.db", "release_api.services",
                      "release_api.main", "release_api.settings", "app.api", "app.mcp")
ALLOWED_THIRD_PARTY = frozenset({"yaml"})
OWN_PACKAGE = "release_api.domain"


def imported_modules(source: str, filename: str = "<src>") -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(ast.parse(source, filename=filename)):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                modules.add(OWN_PACKAGE)
            elif node.module:
                modules.add(node.module)
                modules.update(f"{node.module}.{alias.name}" for alias in node.names)
    return modules


def violations(modules: set[str]) -> set[str]:
    bad: set[str] = set()
    for module in modules:
        top = module.split(".")[0]
        if top in FORBIDDEN_TOP_LEVEL or "mcp" in module.lower().split(".")[0]:
            bad.add(module)
        elif any(module == p or module.startswith(f"{p}.") for p in FORBIDDEN_PREFIXES):
            bad.add(module)
        elif top == "release_api" and not (module == OWN_PACKAGE or module.startswith(f"{OWN_PACKAGE}.")):
            bad.add(module)
        elif top not in sys.stdlib_module_names and top not in ALLOWED_THIRD_PARTY and top != "release_api":
            bad.add(module)
    return bad


def _domain_files() -> list[Path]:
    return sorted(DOMAIN_DIR.rglob("*.py"))


def test_domain_package_exists() -> None:
    names = {p.name for p in _domain_files()}
    assert {"__init__.py", "state_machine.py", "gates.py"} <= names


def test_domain_imports_are_pure() -> None:
    found = {rel(p): sorted(violations(imported_modules(read_text(p), str(p)))) for p in _domain_files()}
    assert not {k: v for k, v in found.items() if v}, f"impure domain imports: {found}"


def test_domain_has_no_dynamic_imports() -> None:
    for path in _domain_files():
        text = read_text(path)
        assert "importlib" not in text and "__import__" not in text, rel(path)


def test_detector_flags_forbidden_imports() -> None:
    sample = "\n".join(
        [
            "import fastapi", "from sqlalchemy.orm import Session", "import httpx", "import requests",
            "from openai import OpenAI", "import mcp", "from mcp.server import Server", "import release_mcp",
            "from release_api.db import models", "from release_api.api.routes import r", "from app.mcp import tools",
            "import numpy",
        ]
    )
    flagged = {m.split(".")[0] for m in violations(imported_modules(sample))}
    assert flagged >= {"fastapi", "sqlalchemy", "httpx", "requests", "openai", "mcp", "release_mcp", "release_api",
                       "app", "numpy"}
    assert not violations(imported_modules("import yaml\nfrom dataclasses import dataclass\nfrom . import gates"))
