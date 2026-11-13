"""ORM models mirror the section 4.1 core schema (Slice 2; BR-03, BR-04, BR-05, BR-08, NFR-01, NFR-04; AC-RM-03).

These checks need no database; tests/integration/test_schema.py proves the models match the migrated schema.
"""

from __future__ import annotations

import pytest
from sqlalchemy import Table, UniqueConstraint
from sqlalchemy.dialects import mysql

from release_api.db.models import Base

EXPECTED_TABLES = {
    "release_request",
    "release_component",
    "release_approval",
    "release_evidence",
    "release_transition",
    "idempotency_record",
    "application_config",
}


def _table(name: str) -> Table:
    return Base.metadata.tables[name]


def _unique_sets(table: Table) -> dict[str | None, tuple[str, ...]]:
    return {
        str(c.name) if c.name else None: tuple(col.name for col in c.columns)
        for c in table.constraints
        if isinstance(c, UniqueConstraint)
    }


def test_metadata_has_exactly_section_4_1_tables() -> None:
    assert set(Base.metadata.tables) == EXPECTED_TABLES


@pytest.mark.parametrize("name", sorted(EXPECTED_TABLES))
def test_tables_are_innodb_utf8mb4(name: str) -> None:
    kwargs = _table(name).dialect_kwargs
    assert kwargs["mysql_engine"] == "InnoDB"
    assert kwargs["mysql_charset"] == "utf8mb4"
    assert kwargs["mysql_collate"] == "utf8mb4_0900_ai_ci"


def test_release_identifiers_are_required_and_unique() -> None:
    # BR-03: immutable business identifier and correlation ID; BR-05: replies correlate by correlation_id.
    table = _table("release_request")
    for column in ("release_id", "correlation_id"):
        assert table.c[column].nullable is False
    assert table.c.release_id.type.length == 32  # type: ignore[attr-defined]
    assert table.c.correlation_id.type.length == 36  # type: ignore[attr-defined]
    uniques = set(_unique_sets(table).values())
    assert ("release_id",) in uniques
    assert ("correlation_id",) in uniques


def test_release_request_allows_partial_requests() -> None:
    # BR-04: business fields are nullable so partial requests persist; missing_fields is JSON.
    table = _table("release_request")
    required = {c.name for c in table.columns if not c.nullable}
    assert required == {"id", "release_id", "correlation_id", "status", "version", "created_at", "updated_at"}
    assert isinstance(table.c.missing_fields.type, mysql.JSON)


def test_release_request_defaults_and_indexes() -> None:
    table = _table("release_request")
    assert "RECEIVED" in str(table.c.status.server_default.arg)  # type: ignore[union-attr]
    assert str(table.c.version.server_default.arg) == "1"  # type: ignore[union-attr]
    assert "CURRENT_TIMESTAMP(6)" in str(table.c.created_at.server_default.arg)  # type: ignore[union-attr]
    assert "ON UPDATE CURRENT_TIMESTAMP(6)" in str(table.c.updated_at.server_default.arg)  # type: ignore[union-attr]
    for column in ("created_at", "updated_at", "expected_start_utc", "expected_end_utc"):
        assert table.c[column].type.fsp == 6  # type: ignore[attr-defined]
    indexes = {i.name: tuple(c.name for c in i.columns) for i in table.indexes}
    assert indexes == {"ix_release_status": ("status",), "ix_release_start": ("expected_start_utc",)}


@pytest.mark.parametrize(
    ("table_name", "column", "values"),
    [
        ("release_request", "downtime_type", ("NONE", "PARTIAL", "FULL")),
        ("release_request", "risk_level", ("LOW", "MEDIUM", "HIGH", "CRITICAL")),
        ("release_approval", "approval_type", ("TECHNICAL", "BUSINESS", "CHANGE", "SRE", "RELEASE_OWNER")),
        ("release_approval", "decision", ("PENDING", "APPROVED", "REJECTED", "UNCLEAR")),
        ("release_evidence", "validation_status", ("UNVERIFIED", "VALID", "INVALID")),
    ],
)
def test_enums_match_spec(table_name: str, column: str, values: tuple[str, ...]) -> None:
    column_type = _table(table_name).c[column].type
    assert isinstance(column_type, mysql.ENUM)
    assert tuple(column_type.enums) == values


def test_approval_decision_defaults_to_pending() -> None:
    # AC-RM-05 support: an approval row is never APPROVED unless explicitly recorded.
    decision = _table("release_approval").c.decision
    assert decision.nullable is False
    assert "PENDING" in str(decision.server_default.arg)  # type: ignore[union-attr]


def test_unique_keys_match_spec() -> None:
    assert _unique_sets(_table("release_component"))["uq_release_component"] == ("release_fk", "component_name")
    assert _unique_sets(_table("release_approval"))["uq_approval"] == ("release_fk", "approval_type", "approver_email")


@pytest.mark.parametrize(
    ("table_name", "ondelete"),
    [
        ("release_component", "CASCADE"),
        ("release_approval", None),
        ("release_evidence", None),
        ("release_transition", None),
    ],
)
def test_child_tables_reference_release_request(table_name: str, ondelete: str | None) -> None:
    # Approval, evidence and audit rows are never removed by cascading deletes (NFR-01, BR-08).
    (fk,) = _table(table_name).foreign_keys
    assert fk.target_fullname == "release_request.id"
    assert fk.parent.name == "release_fk"
    assert fk.parent.nullable is False
    assert fk.ondelete == ondelete


def test_transition_audit_columns() -> None:
    # NFR-01: every transition records actor and correlation; indexed for per-release audit history.
    table = _table("release_transition")
    for column in ("to_status", "actor_type", "correlation_id", "created_at"):
        assert table.c[column].nullable is False
    assert table.c.from_status.nullable is True
    indexes = {i.name: tuple(c.name for c in i.columns) for i in table.indexes}
    assert indexes == {"ix_transition_release": ("release_fk", "created_at")}


def test_idempotency_key_is_primary_key() -> None:
    # NFR-04, AC-RM-03: duplicate keys are rejected by the database.
    table = _table("idempotency_record")
    assert [c.name for c in table.primary_key.columns] == ["idempotency_key"]
    assert table.c.idempotency_key.type.length == 255  # type: ignore[attr-defined]
    assert table.c.operation.nullable is False


def test_application_config_keyed_by_application() -> None:
    table = _table("application_config")
    assert [c.name for c in table.primary_key.columns] == ["application_key"]
    assert table.c.display_name.nullable is False
    assert table.c.active.nullable is False


def test_surrogate_ids_are_unsigned_bigint() -> None:
    for name in EXPECTED_TABLES - {"idempotency_record", "application_config"}:
        column_type = _table(name).c.id.type
        assert isinstance(column_type, mysql.BIGINT)
        assert column_type.unsigned is True
