"""ORM models for the section 4.1 core schema (Slice 2).

Requirements: BR-03, BR-04, BR-05, BR-08, NFR-01, NFR-04; AC-RM-03. The schema is owned by the Alembic migrations in
db/migrations; these models must match it exactly (tests/integration/test_schema.py fails on drift). Unique and
foreign-key names follow MySQL's names for the verbatim DDL.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import FetchedValue, ForeignKey, Index, UniqueConstraint, text
from sqlalchemy.dialects.mysql import BIGINT, BOOLEAN, CHAR, DATETIME, ENUM, INTEGER, JSON, SMALLINT, TEXT, VARCHAR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

TABLE_OPTIONS: dict[str, Any] = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_ai_ci",
}

DOWNTIME_TYPES = ("NONE", "PARTIAL", "FULL")
RISK_LEVELS = ("LOW", "MEDIUM", "HIGH", "CRITICAL")
APPROVAL_TYPES = ("TECHNICAL", "BUSINESS", "CHANGE", "SRE", "RELEASE_OWNER")
APPROVAL_DECISIONS = ("PENDING", "APPROVED", "REJECTED", "UNCLEAR")
EVIDENCE_VALIDATION_STATUSES = ("UNVERIFIED", "VALID", "INVALID")


def _created_at() -> Mapped[datetime]:
    return mapped_column(DATETIME(fsp=6), nullable=False, server_default=text("CURRENT_TIMESTAMP(6)"))


def _release_fk(ondelete: str | None = None) -> Mapped[int]:
    return mapped_column(
        BIGINT(unsigned=True), ForeignKey("release_request.id", ondelete=ondelete), nullable=False
    )


def _surrogate_id() -> Mapped[int]:
    return mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)


class Base(DeclarativeBase):
    pass


class ReleaseRequest(Base):
    __tablename__ = "release_request"
    __table_args__ = (
        UniqueConstraint("release_id", name="release_id"),
        UniqueConstraint("correlation_id", name="correlation_id"),
        Index("ix_release_status", "status"),
        Index("ix_release_start", "expected_start_utc"),
        TABLE_OPTIONS,
    )

    id: Mapped[int] = _surrogate_id()
    release_id: Mapped[str] = mapped_column(VARCHAR(32), nullable=False)
    correlation_id: Mapped[str] = mapped_column(CHAR(36), nullable=False)
    release_name: Mapped[str | None] = mapped_column(VARCHAR(200))
    application_key: Mapped[str | None] = mapped_column(VARCHAR(100))
    original_subject: Mapped[str | None] = mapped_column(VARCHAR(500))
    requester_name: Mapped[str | None] = mapped_column(VARCHAR(200))
    requester_email: Mapped[str | None] = mapped_column(VARCHAR(320))
    expected_start_utc: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    expected_end_utc: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    impact: Mapped[str | None] = mapped_column(TEXT)
    downtime_type: Mapped[str | None] = mapped_column(ENUM(*DOWNTIME_TYPES))
    downtime_details: Mapped[str | None] = mapped_column(VARCHAR(2000))
    implementation_plan: Mapped[str | None] = mapped_column(TEXT)
    validation_plan: Mapped[str | None] = mapped_column(TEXT)
    rollback_plan: Mapped[str | None] = mapped_column(TEXT)
    risk_score: Mapped[int | None] = mapped_column(SMALLINT)
    risk_level: Mapped[str | None] = mapped_column(ENUM(*RISK_LEVELS))
    status: Mapped[str] = mapped_column(VARCHAR(50), nullable=False, server_default=text("'RECEIVED'"))
    conversation_id: Mapped[str | None] = mapped_column(VARCHAR(500))
    last_message_id: Mapped[str | None] = mapped_column(VARCHAR(500))
    confluence_page_id: Mapped[str | None] = mapped_column(VARCHAR(100))
    confluence_url: Mapped[str | None] = mapped_column(VARCHAR(1000))
    jira_key: Mapped[str | None] = mapped_column(VARCHAR(100))
    jira_url: Mapped[str | None] = mapped_column(VARCHAR(1000))
    meeting_id: Mapped[str | None] = mapped_column(VARCHAR(500))
    missing_fields: Mapped[Any] = mapped_column(JSON, nullable=True)
    version: Mapped[int] = mapped_column(INTEGER, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)"),
        server_onupdate=FetchedValue(),
    )


class ReleaseComponent(Base):
    __tablename__ = "release_component"
    __table_args__ = (
        UniqueConstraint("release_fk", "component_name", name="uq_release_component"),
        TABLE_OPTIONS,
    )

    id: Mapped[int] = _surrogate_id()
    release_fk: Mapped[int] = _release_fk(ondelete="CASCADE")
    component_name: Mapped[str] = mapped_column(VARCHAR(200), nullable=False)
    current_version: Mapped[str | None] = mapped_column(VARCHAR(100))
    target_version: Mapped[str] = mapped_column(VARCHAR(100), nullable=False)
    repository_url: Mapped[str | None] = mapped_column(VARCHAR(1000))
    pipeline_ref: Mapped[str | None] = mapped_column(VARCHAR(500))
    deployment_order: Mapped[int | None] = mapped_column(INTEGER)
    rollback_version: Mapped[str | None] = mapped_column(VARCHAR(100))


class ReleaseApproval(Base):
    __tablename__ = "release_approval"
    __table_args__ = (
        UniqueConstraint("release_fk", "approval_type", "approver_email", name="uq_approval"),
        TABLE_OPTIONS,
    )

    id: Mapped[int] = _surrogate_id()
    release_fk: Mapped[int] = _release_fk()
    approval_type: Mapped[str] = mapped_column(ENUM(*APPROVAL_TYPES), nullable=False)
    approver_email: Mapped[str] = mapped_column(VARCHAR(320), nullable=False)
    decision: Mapped[str] = mapped_column(
        ENUM(*APPROVAL_DECISIONS), nullable=False, server_default=text("'PENDING'")
    )
    comments: Mapped[str | None] = mapped_column(TEXT)
    decision_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    source_message_id: Mapped[str | None] = mapped_column(VARCHAR(500))


class ReleaseEvidence(Base):
    __tablename__ = "release_evidence"
    __table_args__ = (TABLE_OPTIONS,)

    id: Mapped[int] = _surrogate_id()
    release_fk: Mapped[int] = _release_fk()
    evidence_type: Mapped[str] = mapped_column(VARCHAR(100), nullable=False)
    source_system: Mapped[str] = mapped_column(VARCHAR(100), nullable=False)
    source_reference: Mapped[str] = mapped_column(VARCHAR(1000), nullable=False)
    sha256: Mapped[str | None] = mapped_column(CHAR(64))
    validation_status: Mapped[str | None] = mapped_column(
        ENUM(*EVIDENCE_VALIDATION_STATUSES), server_default=text("'UNVERIFIED'")
    )
    captured_at: Mapped[datetime] = _created_at()


class ReleaseTransition(Base):
    __tablename__ = "release_transition"
    __table_args__ = (
        Index("ix_transition_release", "release_fk", "created_at"),
        TABLE_OPTIONS,
    )

    id: Mapped[int] = _surrogate_id()
    release_fk: Mapped[int] = _release_fk()
    from_status: Mapped[str | None] = mapped_column(VARCHAR(50))
    to_status: Mapped[str] = mapped_column(VARCHAR(50), nullable=False)
    actor_type: Mapped[str] = mapped_column(VARCHAR(30), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(VARCHAR(320))
    reason: Mapped[str | None] = mapped_column(VARCHAR(2000))
    correlation_id: Mapped[str] = mapped_column(CHAR(36), nullable=False)
    created_at: Mapped[datetime] = _created_at()


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_record"
    __table_args__ = (TABLE_OPTIONS,)

    idempotency_key: Mapped[str] = mapped_column(VARCHAR(255), primary_key=True)
    operation: Mapped[str] = mapped_column(VARCHAR(100), nullable=False)
    release_id: Mapped[str | None] = mapped_column(VARCHAR(32))
    response_json: Mapped[Any] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = _created_at()


class ApplicationConfig(Base):
    __tablename__ = "application_config"
    __table_args__ = (TABLE_OPTIONS,)

    application_key: Mapped[str] = mapped_column(VARCHAR(100), primary_key=True)
    display_name: Mapped[str] = mapped_column(VARCHAR(200), nullable=False)
    product_owner_email: Mapped[str | None] = mapped_column(VARCHAR(320))
    business_approver_email: Mapped[str | None] = mapped_column(VARCHAR(320))
    change_manager_email: Mapped[str | None] = mapped_column(VARCHAR(320))
    sre_dl: Mapped[str | None] = mapped_column(VARCHAR(320))
    dev_team_dl: Mapped[str | None] = mapped_column(VARCHAR(320))
    confluence_space_id: Mapped[str | None] = mapped_column(VARCHAR(100))
    jira_project_key: Mapped[str | None] = mapped_column(VARCHAR(50))
    jira_issue_type: Mapped[str | None] = mapped_column(VARCHAR(100))
    active: Mapped[bool] = mapped_column(BOOLEAN, nullable=False, server_default=text("TRUE"))
