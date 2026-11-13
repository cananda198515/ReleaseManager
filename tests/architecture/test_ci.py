"""CI runs the gates; docker-compose is local MySQL only (Slice 1; NFR-03, NFR-06)."""

from __future__ import annotations

from typing import Any

from tests._repo import load_yaml


def _run_commands(workflow: dict[str, Any]) -> str:
    return "\n".join(
        str(step.get("run", "")) for job in workflow["jobs"].values() for step in job.get("steps", [])
    )


def test_validate_workflow_runs_gates() -> None:
    commands = _run_commands(load_yaml(".github/workflows/validate.yml"))
    for gate in ("ruff check .", "mypy .", "pytest -q"):
        assert gate in commands, f"validate.yml does not run `{gate}`"


def test_validate_workflow_runs_on_every_pull_request() -> None:
    workflow = load_yaml(".github/workflows/validate.yml")
    triggers = workflow.get("on", workflow.get(True))  # PyYAML parses the bare key `on` as True
    assert "pull_request" in triggers
    assert not (triggers["pull_request"] or {}).get("branches"), "validate.yml must run on every PR"


def test_pre_commit_runs_ruff_mypy_and_gitleaks() -> None:
    config = load_yaml(".pre-commit-config.yaml")
    hook_ids = {hook["id"] for repo in config["repos"] for hook in repo["hooks"]}
    assert {"ruff-check", "mypy", "gitleaks"} <= hook_ids, sorted(hook_ids)


def test_build_workflow_builds_both_services() -> None:
    workflow = load_yaml(".github/workflows/build.yml")
    text = _run_commands(workflow) + str(workflow)
    assert "services/release-api" in text
    assert "services/release-mcp" in text


def test_security_workflow_runs_architecture_tests() -> None:
    assert "tests/architecture" in _run_commands(load_yaml(".github/workflows/security.yml"))


def test_workflows_use_read_only_token() -> None:
    for name in ("validate", "build", "security"):
        workflow = load_yaml(f".github/workflows/{name}.yml")
        assert workflow.get("permissions") == {"contents": "read"}, f"{name}.yml must declare contents: read"


def test_compose_is_local_mysql_only() -> None:
    compose = load_yaml("docker-compose.yml")
    assert set(compose["services"]) == {"mysql"}
    mysql = compose["services"]["mysql"]
    assert str(mysql["image"]).startswith("mysql:8.4")
    assert all(str(p).startswith("127.0.0.1:") for p in mysql.get("ports", [])), "bind MySQL to localhost only"
