"""The machine-readable policy matches the human-readable spec (Slice 3; NFR-01, NFR-02, NFR-10; AC-RM-04).

policies/state-transitions.yaml must not drift from specs/release-lifecycle.md sections 2-4.
"""

from __future__ import annotations

import re
from typing import Any

from tests._repo import REPO_ROOT, load_yaml, read_text

SPEC = read_text(REPO_ROOT / "specs" / "release-lifecycle.md")
POLICY: dict[str, Any] = load_yaml("policies/state-transitions.yaml")
ROW = re.compile(r"^\|\s*([A-Z_]+)\s*\|\s*([^|]+?)\s*\|\s*$")


def _section(title: str) -> str:
    match = re.search(rf"^## {re.escape(title)}.*?(?=^## |\Z)", SPEC, re.MULTILINE | re.DOTALL)
    assert match, f"section not found: {title}"
    return match.group(0)


def _table(title: str) -> dict[str, str]:
    rows = (ROW.match(line) for line in _section(title).splitlines())
    return {m.group(1): m.group(2) for m in rows if m}


def test_allowed_transitions_match_spec_table() -> None:
    spec = {source: [t.strip() for t in targets.split(",")] for source, targets in _table("3.").items()}
    assert spec == POLICY["transitions"]


def test_gated_states_match_spec_table() -> None:
    assert set(_table("4.")) == set(POLICY["gates"])


def test_terminal_states_match_spec() -> None:
    exceptions = set(re.findall(r"[A-Z_]{4,}", _section("2.").split("```")[1]))
    assert exceptions | {"COMPLETED"} == set(POLICY["terminal_states"])


def test_denial_contract() -> None:
    assert POLICY["on_denied"] == {"http_status": 409, "write_audit_event": True}
