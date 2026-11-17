"""Migration 0002 guards release_request.status in the database (Slice 3 review, High finding #6).

The trigger edge list is generated into the migration and must equal policies/state-transitions.yaml, so the database
and the state machine cannot drift. Creating triggers needs the TRIGGER privilege for the migration identity and, with
binary logging, log_bin_trust_function_creators=1 (a DBA step documented in db/README.md).
Requirements: NFR-01, NFR-02, NFR-06; AC-RM-04.
"""

from __future__ import annotations

import importlib.util
import re
from types import ModuleType

from tests._repo import REPO_ROOT, load_yaml, read_text

MIGRATION = REPO_ROOT / "db" / "migrations" / "versions" / "0002_release_status_guard.py"


def _migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migration_0002", MIGRATION)
    assert spec and spec.loader, f"missing {MIGRATION}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_revises_core_schema() -> None:
    module = _migration()
    assert (module.revision, module.down_revision) == ("0002", "0001")


def test_trigger_edges_match_state_transition_policy() -> None:
    policy = load_yaml("policies/state-transitions.yaml")
    expected = {(source, target) for source, targets in policy["transitions"].items() for target in targets}
    module = _migration()
    assert set(module.ALLOWED_STATUS_EDGES) == expected
    assert len(module.ALLOWED_STATUS_EDGES) == len(expected)
    assert module.INITIAL_STATUS == policy["initial_state"]


def test_triggers_guard_insert_and_update_and_are_dropped_on_downgrade() -> None:
    source = read_text(MIGRATION)
    assert re.search(r"CREATE TRIGGER\s+trg_release_status_insert\s+BEFORE INSERT ON release_request", source)
    assert re.search(r"CREATE TRIGGER\s+trg_release_status_update\s+BEFORE UPDATE ON release_request", source)
    assert "SIGNAL SQLSTATE '45000'" in source
    assert "DROP TRIGGER IF EXISTS trg_release_status_insert" in source
    assert "DROP TRIGGER IF EXISTS trg_release_status_update" in source


def test_readme_documents_trigger_prerequisites() -> None:
    readme = read_text(REPO_ROOT / "db" / "README.md")
    pattern = r"GRANT\s+(?P<privs>[A-Z ,]+?)\s+ON\s+release_management\.\*\s+TO\s+'release_migrator'"
    migrator = re.search(pattern, readme)
    assert migrator and "TRIGGER" in {p.strip() for p in migrator.group("privs").split(",")}
    assert "log_bin_trust_function_creators" in readme
    assert "0002_release_status_guard.py" in readme
