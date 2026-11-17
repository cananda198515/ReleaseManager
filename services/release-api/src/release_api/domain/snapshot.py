"""Immutable release snapshot evaluated by the gates (Slice 3).

Defaults are fail-closed: facts not yet produced by later slices (schema validation, readiness report, blockers,
attendees) default to values that deny the corresponding gate. Naive datetimes are UTC (MySQL DATETIME columns).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime

from release_api.domain.product_rules import ProductRules


@dataclass(frozen=True)
class ComponentSnapshot:
    name: str
    target_version: str | None


@dataclass(frozen=True)
class ApprovalSnapshot:
    approval_type: str
    approver_email: str
    decision: str
    decision_at: datetime | None = None
    source_message_id: str | None = None


@dataclass(frozen=True)
class EvidenceSnapshot:
    evidence_type: str
    validation_status: str | None


@dataclass(frozen=True)
class ReleaseSnapshot:
    as_of: datetime
    rules: ProductRules
    release_name: str | None = None
    application_key: str | None = None
    expected_start_utc: datetime | None = None
    expected_end_utc: datetime | None = None
    impact: str | None = None
    downtime_type: str | None = None
    downtime_details: str | None = None
    implementation_plan: str | None = None
    validation_plan: str | None = None
    rollback_plan: str | None = None
    risk_score: int | None = None
    risk_level: str | None = None
    components: tuple[ComponentSnapshot, ...] = ()
    approvals: tuple[ApprovalSnapshot, ...] = ()
    evidence: tuple[EvidenceSnapshot, ...] = ()
    schema_valid: bool = False
    readiness_report_produced: bool = False
    blockers: tuple[str, ...] = ()
    attendees: tuple[str, ...] = ()
    requester_email: str | None = None
    # Configured approver email per approval type (application_config); missing entries fail closed.
    approvers: Mapping[str, str] = field(default_factory=dict)
