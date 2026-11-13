"""No forbidden tools; MCP exposes only allow-listed tools (policies/tool-allowlist.yaml; NFR-03, NFR-07).

Forbidden: execute_sql, generic_http, set_status_without_validation, write_secret, shell, file_write, secret_read.
"""

from __future__ import annotations

import ast
import re

from tests._repo import files_under, imported_top_level_modules, python_files, read_text, rel, tool_allowlist

DANGEROUS_NAME = re.compile(
    r"execute_sql|run_sql|raw_sql|exec_sql|generic_http|http_request|shell|exec_command|run_command|"
    r"write_file|file_write|read_secret|secret_read|get_secret|write_secret|set_status_without_validation",
    re.IGNORECASE,
)
PROCESS_MODULES = frozenset({"subprocess", "pty"})


def _defined_names(tree: ast.AST) -> list[str]:
    return [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
    ]


def _string_constants(tree: ast.AST) -> set[str]:
    return {node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)}


def test_allowlist_defines_exactly_ten_tools() -> None:
    allowed, forbidden = tool_allowlist()
    assert len(allowed) == 10, sorted(allowed)
    assert not allowed & forbidden


def test_no_forbidden_tools_defined() -> None:
    _, forbidden = tool_allowlist()
    files = python_files(files_under("services"))
    assert files, "services/ has no Python sources"
    violations: dict[str, list[str]] = {}
    for path in files:
        tree = ast.parse(read_text(path), filename=str(path))
        bad = [n for n in _defined_names(tree) if DANGEROUS_NAME.search(n)]
        bad += sorted(_string_constants(tree) & forbidden)
        if bad:
            violations[rel(path)] = bad
    assert not violations, f"forbidden tool capabilities present: {violations}"


def test_mcp_does_not_spawn_processes() -> None:
    violations = {
        rel(p): sorted(imported_top_level_modules(p) & PROCESS_MODULES)
        for p in python_files(files_under("services/release-mcp"))
    }
    assert not {k: v for k, v in violations.items() if v}, violations


def test_registered_tools_subset_of_allowlist() -> None:
    from release_mcp.tools import REGISTERED_TOOLS

    allowed, forbidden = tool_allowlist()
    registered = set(REGISTERED_TOOLS)
    assert len(registered) == len(REGISTERED_TOOLS), "duplicate tool registrations"
    assert registered <= allowed, f"non-allow-listed tools: {sorted(registered - allowed)}"
    assert not registered & forbidden, f"forbidden tools registered: {sorted(registered & forbidden)}"


def test_dangerous_name_detector() -> None:
    assert DANGEROUS_NAME.search("execute_sql")
    assert DANGEROUS_NAME.search("run_shell")
    assert not DANGEROUS_NAME.search("release_get_readiness")
