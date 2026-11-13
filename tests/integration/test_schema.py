"""Section 4.1 schema against real MySQL (Slice 2; section 13 database integration tests).

Requirements: BR-03, BR-04, BR-05, BR-08, NFR-01, NFR-04, NFR-06; AC-RM-03.
"""

from __future__ import annotations

import threading
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Engine, func, inspect, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from release_api.db.models import (
    ApplicationConfig,
    Base,
    IdempotencyRecord,
    ReleaseApproval,
    ReleaseComponent,
    ReleaseEvidence,
    ReleaseRequest,
    ReleaseTransition,
)
from release_api.db.seed import apply_seed, load_seed_rows
from tests._repo import REPO_ROOT
from tests.integration.conftest import run_alembic

EXPECTED_TABLES = set(Base.metadata.tables)
MYSQL_ACCESS_DENIED = {1142, 1143, 1044}


def _release(release_id: str = "REL-20261113-0001", **fields: Any) -> ReleaseRequest:
    correlation_id = fields.pop("correlation_id", str(uuid.uuid4()))
    return ReleaseRequest(release_id=release_id, correlation_id=correlation_id, **fields)


def _add_release(engine: Engine, **fields: Any) -> int:
    with Session(engine) as session, session.begin():
        release = _release(**fields)
        session.add(release)
        session.flush()
        return release.id


def _count(engine: Engine, model: type[Base]) -> int:
    with Session(engine) as session:
        return session.scalar(select(func.count()).select_from(model)) or 0


def _app_tables(engine: Engine) -> set[str]:
    return set(inspect(engine).get_table_names()) - {"alembic_version"}


def test_upgrade_downgrade_upgrade_roundtrip(migrated: Engine) -> None:
    run_alembic(migrated, command.downgrade, "base")
    assert _app_tables(migrated) == set()
    run_alembic(migrated, command.upgrade, "head")
    assert _app_tables(migrated) == EXPECTED_TABLES


def test_orm_models_match_migrated_schema(migrated: Engine) -> None:
    with migrated.connect() as connection:
        diff = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    assert diff == []


def test_tables_are_innodb_utf8mb4(migrated: Engine) -> None:
    query = text(
        "SELECT TABLE_NAME, ENGINE, TABLE_COLLATION FROM information_schema.TABLES "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME <> 'alembic_version'"
    )
    with migrated.connect() as connection:
        rows = {row[0]: (row[1], row[2]) for row in connection.execute(query)}
    assert set(rows) == EXPECTED_TABLES
    assert set(rows.values()) == {("InnoDB", "utf8mb4_0900_ai_ci")}


def test_sessions_use_utc_and_strict_mode(db: Engine) -> None:
    with db.connect() as connection:
        time_zone = connection.scalar(text("SELECT @@session.time_zone"))
        sql_mode = connection.scalar(text("SELECT @@session.sql_mode"))
        drift = connection.scalar(text("SELECT ABS(TIMESTAMPDIFF(SECOND, UTC_TIMESTAMP(6), NOW(6)))"))
    assert time_zone == "+00:00"
    assert "STRICT_TRANS_TABLES" in str(sql_mode)
    assert drift == 0


def test_partial_release_persists_with_defaults(db: Engine) -> None:
    # BR-04: a partial request persists with explicitly missing fields; defaults come from the schema.
    before = datetime.now(UTC).replace(tzinfo=None, microsecond=0)
    _add_release(db, missing_fields=["impact", "rollbackPlan"], conversation_id="conv-1", last_message_id="msg-1")
    with Session(db) as session:
        release = session.scalars(select(ReleaseRequest)).one()
        assert release.status == "RECEIVED"
        assert release.version == 1
        assert release.missing_fields == ["impact", "rollbackPlan"]
        assert release.release_name is None
        assert release.conversation_id == "conv-1"
        assert release.created_at >= before
        assert release.updated_at >= before


@pytest.mark.parametrize("field", ["release_id", "correlation_id"])
def test_release_identifiers_are_unique(db: Engine, field: str) -> None:
    # BR-03, BR-05.
    first = {"release_id": "REL-20261113-0001", "correlation_id": str(uuid.uuid4())}
    second = {"release_id": "REL-20261113-0002", "correlation_id": str(uuid.uuid4())}
    second[field] = first[field]
    _add_release(db, **first)
    with pytest.raises(IntegrityError):
        _add_release(db, **second)
    assert _count(db, ReleaseRequest) == 1


@pytest.mark.parametrize("field", ["release_id", "correlation_id"])
def test_release_identifiers_are_required(db: Engine, field: str) -> None:
    columns = {"release_id": "'REL-20261113-0001'", "correlation_id": f"'{uuid.uuid4()}'"}
    del columns[field]
    statement = f"INSERT INTO release_request ({', '.join(columns)}) VALUES ({', '.join(columns.values())})"  # noqa: S608
    with pytest.raises(DBAPIError), db.begin() as connection:
        connection.execute(text(statement))
    assert _count(db, ReleaseRequest) == 0


def test_component_name_unique_per_release(db: Engine) -> None:
    release_fk = _add_release(db)
    with Session(db) as session, session.begin():
        session.add(ReleaseComponent(release_fk=release_fk, component_name="web", target_version="1.0"))
    with pytest.raises(IntegrityError), Session(db) as session, session.begin():
        session.add(ReleaseComponent(release_fk=release_fk, component_name="web", target_version="2.0"))
    assert _count(db, ReleaseComponent) == 1


def test_approval_unique_per_type_and_approver(db: Engine) -> None:
    # BR-08: one approval record per release, type and approver.
    release_fk = _add_release(db)
    approval = {"release_fk": release_fk, "approval_type": "TECHNICAL", "approver_email": "a@example.com"}
    with Session(db) as session, session.begin():
        session.add(ReleaseApproval(**approval))
    with pytest.raises(IntegrityError), Session(db) as session, session.begin():
        session.add(ReleaseApproval(**approval))
    with Session(db) as session:
        stored = session.scalars(select(ReleaseApproval)).one()
        assert stored.decision == "PENDING"


@pytest.mark.parametrize(
    "make_row",
    [
        lambda fk: ReleaseComponent(release_fk=fk, component_name="web", target_version="1.0"),
        lambda fk: ReleaseApproval(release_fk=fk, approval_type="BUSINESS", approver_email="b@example.com"),
        lambda fk: ReleaseEvidence(release_fk=fk, evidence_type="smoke_test", source_system="ci", source_reference="r"),
        lambda fk: ReleaseTransition(
            release_fk=fk, to_status="RECEIVED", actor_type="SYSTEM", correlation_id=str(uuid.uuid4())
        ),
    ],
    ids=["component", "approval", "evidence", "transition"],
)
def test_child_rows_require_existing_release(db: Engine, make_row: Any) -> None:
    with pytest.raises(IntegrityError), Session(db) as session, session.begin():
        session.add(make_row(999_999_999))


@pytest.mark.parametrize(
    ("table", "column", "value"),
    [
        ("release_request", "downtime_type", "SOME"),
        ("release_request", "risk_level", "EXTREME"),
        ("release_approval", "approval_type", "SELF"),
        ("release_approval", "decision", "PROBABLY"),
        ("release_evidence", "validation_status", "TRUSTED"),
    ],
)
def test_invalid_enum_values_are_rejected(db: Engine, table: str, column: str, value: str) -> None:
    release_fk = _add_release(db)
    base = {
        "release_request": {"release_id": "'REL-20261113-0009'", "correlation_id": f"'{uuid.uuid4()}'"},
        "release_approval": {"release_fk": str(release_fk), "approval_type": "'SRE'", "approver_email": "'s@x.io'"},
        "release_evidence": {
            "release_fk": str(release_fk),
            "evidence_type": "'smoke_test'",
            "source_system": "'ci'",
            "source_reference": "'r'",
        },
    }[table]
    base[column] = f"'{value}'"
    statement = f"INSERT INTO {table} ({', '.join(base)}) VALUES ({', '.join(base.values())})"  # noqa: S608
    with pytest.raises(DBAPIError), db.begin() as connection:
        connection.execute(text(statement))


def test_failed_transaction_rolls_back_all_rows(db: Engine) -> None:
    # NFR-01/NFR-08 support: a failure part-way leaves no partial release behind.
    with pytest.raises(IntegrityError), Session(db) as session, session.begin():
        release = _release()
        session.add(release)
        session.flush()
        session.add(ReleaseComponent(release_fk=release.id, component_name="web", target_version="1.0"))
        session.add(ReleaseTransition(
            release_fk=release.id, to_status="RECEIVED", actor_type="SYSTEM", correlation_id=release.correlation_id
        ))
        session.flush()
        session.add(ReleaseComponent(release_fk=release.id, component_name="web", target_version="2.0"))
        session.flush()
    for model in (ReleaseRequest, ReleaseComponent, ReleaseTransition):
        assert _count(db, model) == 0


@pytest.mark.parametrize("model", [ReleaseRequest, IdempotencyRecord], ids=["release_id", "idempotency_key"])
def test_concurrent_duplicate_create_yields_one_row(db: Engine, model: type[Base]) -> None:
    # NFR-04, AC-RM-03: two concurrent creates with the same key commit exactly one row.
    workers = 2
    barrier = threading.Barrier(workers)
    outcomes: list[str] = []
    lock = threading.Lock()

    def create() -> None:
        row: Base
        if model is ReleaseRequest:
            row = _release("REL-20261113-0042")
        else:
            row = IdempotencyRecord(
                idempotency_key="outlook:<duplicate@example.com>", operation="create_release",
                release_id="REL-20261113-0042",
            )
        with Session(db) as session:
            session.add(row)
            barrier.wait(timeout=10)
            try:
                session.commit()
                outcome = "committed"
            except IntegrityError:
                session.rollback()
                outcome = "duplicate"
        with lock:
            outcomes.append(outcome)

    threads = [threading.Thread(target=create) for _ in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert sorted(outcomes) == ["committed", "duplicate"]
    assert _count(db, model) == 1


def test_datetime_columns_have_microsecond_precision(migrated: Engine) -> None:
    query = text(
        "SELECT TABLE_NAME, COLUMN_NAME, DATETIME_PRECISION FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND DATA_TYPE = 'datetime' AND TABLE_NAME <> 'alembic_version'"
    )
    with migrated.connect() as connection:
        precision = {(row[0], row[1]): row[2] for row in connection.execute(query)}
    assert len(precision) == 8
    assert set(precision.values()) == {6}, precision


def test_timestamps_are_stored_with_microseconds(db: Engine) -> None:
    start = datetime(2026, 11, 20, 3, 30, 15, 123456)
    _add_release(db, expected_start_utc=start)
    with db.connect() as connection:
        stored = connection.execute(
            text("SELECT expected_start_utc, DATE_FORMAT(created_at, '%f') FROM release_request")
        ).one()
    assert stored[0] == start
    assert stored[0].microsecond == 123456
    assert len(stored[1]) == 6


def test_sql_seed_applies_idempotently_as_runtime_identity(db: Engine, runtime_engine: Engine) -> None:
    statement = "\n".join(
        line for line in (REPO_ROOT / "db" / "seed" / "dev_application_config.sql").read_text("utf-8").splitlines()
        if not line.lstrip().startswith("--")
    ).strip().rstrip(";")
    for _ in range(2):
        with runtime_engine.begin() as connection:
            connection.exec_driver_sql(statement)
    with Session(db) as session:
        (row,) = session.scalars(select(ApplicationConfig)).all()
    assert row.application_key == "wileyplus"
    assert row.product_owner_email is not None
    assert row.product_owner_email.endswith("@example.com")


def test_seed_is_idempotent(db: Engine) -> None:
    rows = load_seed_rows(REPO_ROOT / "db" / "seed" / "test.yaml", app_env="test")
    for _ in range(2):
        with db.begin() as connection:
            apply_seed(connection, rows)
    with Session(db) as session:
        stored = {c.application_key: c.display_name for c in session.scalars(select(ApplicationConfig))}
    assert stored == {row["application_key"]: row["display_name"] for row in rows}


def test_runtime_identity_can_read_and_write(db: Engine, runtime_engine: Engine) -> None:
    release_fk = _add_release(runtime_engine)
    with runtime_engine.begin() as connection:
        connection.execute(text("UPDATE release_request SET release_name = 'n' WHERE id = :id"), {"id": release_fk})
    assert _count(db, ReleaseRequest) == 1


@pytest.mark.parametrize(
    "statement",
    [
        "DELETE FROM release_transition",
        "DELETE FROM release_request",
        "DROP TABLE release_transition",
        "ALTER TABLE release_request ADD COLUMN x INT",
        "CREATE TABLE runtime_probe (id INT)",
        "TRUNCATE TABLE release_transition",
    ],
)
def test_runtime_identity_cannot_change_schema_or_delete(db: Engine, runtime_engine: Engine, statement: str) -> None:
    # NFR-06, NFR-01: the runtime identity cannot alter schema or erase audit/release records.
    with pytest.raises(DBAPIError) as excinfo, runtime_engine.begin() as connection:
        connection.execute(text(statement))
    assert excinfo.value.orig is not None
    assert excinfo.value.orig.args[0] in MYSQL_ACCESS_DENIED
