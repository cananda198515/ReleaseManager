"""No secrets in code, config, tests or scripts; secrets are referenced by name only (NFR-03, AC-RM-09 support)."""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

from tests._repo import REPO_ROOT, load_yaml, python_files, read_text, rel, text_files

PRIVATE_KEY = re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----")
URL_CREDENTIALS = re.compile(r"\b[a-zA-Z][a-zA-Z0-9+.-]*://[^\s/:@'\"<>{}$]+:[^\s/@'\"<>{}$]+@")
KNOWN_TOKEN = re.compile(r"\b(?:AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{36,}|xox[abprs]-[A-Za-z0-9-]{10,})\b")
SECRET_KEY_NAME = re.compile(r"password|passwd|pwd|secret|token|api_?key|private_?key|credential", re.IGNORECASE)
CONFIG_ASSIGNMENT = re.compile(
    r"^[ \t]*[\"']?(?P<key>[A-Za-z0-9_.-]*(?:password|passwd|pwd|secret|token|api_?key|private_?key)[A-Za-z0-9_.-]*)"
    r"[\"']?[ \t]*[:=][ \t]*(?P<value>.*)$",
    re.IGNORECASE | re.MULTILINE,
)
REFERENCE_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")
# Keys that name a secret mechanism or reference rather than holding a secret value.
NON_SECRET_KEY = re.compile(r"(?:provider|_ref|ref|_name)$", re.IGNORECASE)
PLACEHOLDER_PREFIXES = ("<", "${", "$", "{", "[", "|", ">", "#")
NON_VALUES = frozenset({"", "null", "none", "~", "true", "false", "str", "string"})


def _is_safe_value(raw: str) -> bool:
    value = raw.split(" #", 1)[0].strip().strip("\"'").strip()
    return (
        value.lower() in NON_VALUES
        or value.startswith(PLACEHOLDER_PREFIXES)
        or bool(REFERENCE_NAME.fullmatch(value))
    )


def find_text_secrets(text: str, *, config_style: bool) -> list[str]:
    findings = [m.group(0) for p in (PRIVATE_KEY, URL_CREDENTIALS, KNOWN_TOKEN) for m in p.finditer(text)]
    if config_style:
        findings += [
            m.group(0)
            for m in CONFIG_ASSIGNMENT.finditer(text)
            if not NON_SECRET_KEY.search(m.group("key")) and not _is_safe_value(m.group("value"))
        ]
    return findings


def _target_names(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Assign):
        return [
            t.id if isinstance(t, ast.Name) else t.attr
            for t in node.targets
            if isinstance(t, ast.Name | ast.Attribute)
        ]
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name | ast.Attribute):
        return [node.target.id if isinstance(node.target, ast.Name) else node.target.attr]
    return []


def find_python_secrets(source: str) -> list[str]:
    findings = find_text_secrets(source, config_style=False)
    for node in ast.walk(ast.parse(source)):
        pairs: list[tuple[str, ast.AST | None]] = []
        if isinstance(node, ast.Assign | ast.AnnAssign):
            pairs = [(name, node.value) for name in _target_names(node)]
        elif isinstance(node, ast.keyword) and node.arg:
            pairs = [(node.arg, node.value)]
        elif isinstance(node, ast.Dict):
            pairs = [
                (k.value, v) for k, v in zip(node.keys, node.values, strict=True)
                if isinstance(k, ast.Constant) and isinstance(k.value, str)
            ]
        for name, value in pairs:
            if (
                SECRET_KEY_NAME.search(name)
                and not NON_SECRET_KEY.search(name)
                and isinstance(value, ast.Constant)
                and isinstance(value.value, str)
                and not _is_safe_value(value.value)
            ):
                findings.append(f"{name} = {value.value!r}")
    return findings


def _scan(path: Path) -> list[str]:
    source = read_text(path)
    if path.suffix == ".py":
        return find_python_secrets(source)
    return find_text_secrets(source, config_style=True)


def test_no_secret_literals_in_repo() -> None:
    violations = {rel(p): f for p in text_files() if (f := _scan(p))}
    assert not violations, f"possible secrets committed: {violations}"


def test_secret_detectors_catch_known_patterns() -> None:
    assert find_text_secrets("db_password: hunter2", config_style=True)
    assert find_text_secrets("mysql://app" + ":s3cr3t@db/x", config_style=False)
    assert find_text_secrets("-----BEGIN " + "PRIVATE KEY-----", config_style=False)
    assert find_python_secrets("api_key = " + "'abc123'")
    assert find_python_secrets("connect(password=" + "'hunter2')")


def test_secret_detectors_allow_references() -> None:
    assert not find_text_secrets("password: {secretRef: MYSQL_PASSWORD}", config_style=True)
    assert not find_text_secrets("MYSQL_PASSWORD=<resolved-from-secret-manager>", config_style=True)
    assert not find_text_secrets("MYSQL_PASSWORD: ${MYSQL_PASSWORD:?set in .env}", config_style=True)
    assert not find_python_secrets("mysql_password_ref: str = 'MYSQL_PASSWORD'")
    assert not find_text_secrets("SECRET_PROVIDER=azure-key-vault", config_style=True)
    assert find_text_secrets("SECRET_KEY=abc123", config_style=True)


def _walk(node: Any, path: str = "") -> list[tuple[str, Any]]:
    if isinstance(node, dict):
        if set(node) <= {"env", "secretRef"}:
            return [(path, node)]
        return [item for k, v in node.items() for item in _walk(v, f"{path}.{k}" if path else str(k))]
    return [(path, node)]


def test_config_references_secrets_by_name() -> None:
    config = load_yaml("config/default.yaml")
    assert config["mysql"]["password"] == {"secretRef": "MYSQL_PASSWORD"}
    for key_path, value in _walk(config):
        if SECRET_KEY_NAME.search(key_path.rsplit(".", 1)[-1]):
            assert isinstance(value, dict) and set(value) == {"secretRef"}, f"{key_path} must be a secretRef"


def test_env_files_are_gitignored() -> None:
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".env" in gitignore, ".env must be git-ignored so local credentials are never committed"


def test_env_example_never_configures_root() -> None:
    # specs/security.md section 3: root account not used by application.
    entries = {
        key.strip(): value.strip()
        for key, _, value in (
            line.partition("=") for line in read_text(REPO_ROOT / ".env.example").splitlines()
        )
        if key.strip() and not key.strip().startswith("#")
    }
    assert "MYSQL_ROOT_PASSWORD" not in entries, ".env.example must not configure root credentials"
    assert entries.get("MYSQL_USER", "").lower() != "root", "the application must not connect as root"


def test_python_sources_scanned() -> None:
    assert python_files(), "no Python files discovered; scanner would pass vacuously"
