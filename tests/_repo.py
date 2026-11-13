"""Shared repository helpers for architecture tests (Slice 1; NFR-03, NFR-06, NFR-09)."""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent

SKIP_DIRS = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        "node_modules",
        "build",
        "dist",
    }
)
BINARY_SUFFIXES = frozenset({".pdf", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".zip", ".gz", ".whl", ".pyc"})


def _not_skipped(path: Path) -> bool:
    return path.is_file() and not (SKIP_DIRS & set(path.relative_to(REPO_ROOT).parts))


def repo_files() -> list[Path]:
    """Files git would track (tracked plus untracked-but-not-ignored); respects .gitignore."""
    try:
        out = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=REPO_ROOT,
            capture_output=True,
            check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return sorted(p for p in REPO_ROOT.rglob("*") if _not_skipped(p))
    return sorted({p for p in (REPO_ROOT / s for s in out.decode("utf-8").split("\0") if s) if _not_skipped(p)})


def files_under(*relative_dirs: str) -> list[Path]:
    roots = [(REPO_ROOT / d).resolve() for d in relative_dirs]
    return [p for p in repo_files() if any(p.resolve().is_relative_to(r) for r in roots)]


def text_files(files: list[Path] | None = None) -> list[Path]:
    return [p for p in (files if files is not None else repo_files()) if p.suffix.lower() not in BINARY_SUFFIXES]


def python_files(files: list[Path] | None = None) -> list[Path]:
    return [p for p in (files if files is not None else repo_files()) if p.suffix == ".py"]


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def imported_top_level_modules(path: Path) -> set[str]:
    tree = ast.parse(read_text(path), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.add(node.module.split(".")[0])
    return modules


def load_yaml(relative_path: str) -> Any:
    return yaml.safe_load(read_text(REPO_ROOT / relative_path))


def tool_allowlist() -> tuple[set[str], set[str]]:
    """Return (allowed tool names, forbidden tool names) from policies/tool-allowlist.yaml."""
    data = load_yaml("policies/tool-allowlist.yaml")
    allowed = {entry["name"] for entry in data["allowed"]}
    forbidden = set(data["forbidden"])
    return allowed, forbidden


def rel(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()
