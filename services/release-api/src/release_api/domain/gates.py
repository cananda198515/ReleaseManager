"""Deterministic gates evaluated when entering a state (specs/release-lifecycle.md section 4; section 8.2).

Each gate returns the codes of its failed checks (empty list = pass). Approvals count only when APPROVED; PENDING,
UNCLEAR and REJECTED never do. Evidence counts only when VALID. Gate inputs that later slices produce (schema
validation, risk, readiness report, blockers, attendees) are read from the snapshot and default to failing.

Owner decisions after the Slice 3 review (specs/slices.md #32): approvals are cumulative (every gate from SCHEDULED
onward re-checks TECHNICAL/BUSINESS and CHANGE; COMPLETED re-checks production authorization); an APPROVED row counts
only with ``decision_at`` and ``source_message_id`` (policies/approvals.yaml evidence_required); the requester can
never approve; BUSINESS and CHANGE approvers must equal the configured approver (application_config).
Requirements: BR-06, BR-08, BR-09, BR-10, BR-12, NFR-01, NFR-02; AC-RM-04, AC-RM-05, AC-RM-06, AC-RM-07, AC-RM-08.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime
from types import MappingProxyType

from release_api.domain.snapshot import ApprovalSnapshot, ReleaseSnapshot

Gate = Callable[[ReleaseSnapshot], list[str]]

APPROVED = "APPROVED"
VALID = "VALID"
NO_DOWNTIME = "NONE"
# Evidence type recording explicit human production execution authorization (owner decision, specs/slices.md).
PRODUCTION_AUTHORIZATION_EVIDENCE = "production_authorization"
CHANGE_CREATION_APPROVAL_TYPES = ("TECHNICAL", "BUSINESS")
CHANGE_APPROVAL_TYPE = "CHANGE"
# Approval types whose approver must equal the configured approver (application_config).
CONFIGURED_APPROVER_TYPES = frozenset({"BUSINESS", "CHANGE"})

APPROVER_NOT_CONFIGURED = "APPROVER_NOT_CONFIGURED"
APPROVER_NOT_AUTHORIZED = "APPROVER_NOT_AUTHORIZED"
APPROVAL_EVIDENCE_MISSING = "APPROVAL_EVIDENCE_MISSING"

REQUIRED_FIELD_MISSING = "REQUIRED_FIELD_MISSING"
COMPONENT_MISSING = "COMPONENT_MISSING"
TARGET_VERSION_MISSING = "TARGET_VERSION_MISSING"
DOWNTIME_DETAILS_MISSING = "DOWNTIME_DETAILS_MISSING"
SCHEMA_INVALID = "SCHEMA_INVALID"
RISK_NOT_CALCULABLE = "RISK_NOT_CALCULABLE"
READINESS_REPORT_MISSING = "READINESS_REPORT_MISSING"
APPROVAL_MISSING = "APPROVAL_MISSING"
APPROVAL_NOT_APPROVED = "APPROVAL_NOT_APPROVED"
RELEASE_WINDOW_MISSING = "RELEASE_WINDOW_MISSING"
RELEASE_WINDOW_INVALID = "RELEASE_WINDOW_INVALID"
RELEASE_WINDOW_IN_PAST = "RELEASE_WINDOW_IN_PAST"
ATTENDEE_CONFIG_MISSING = "ATTENDEE_CONFIG_MISSING"
BLOCKERS_PRESENT = "BLOCKERS_PRESENT"
IMPLEMENTATION_PLAN_MISSING = "IMPLEMENTATION_PLAN_MISSING"
VALIDATION_PLAN_MISSING = "VALIDATION_PLAN_MISSING"
ROLLBACK_PLAN_MISSING = "ROLLBACK_PLAN_MISSING"
PRODUCTION_AUTHORIZATION_MISSING = "PRODUCTION_AUTHORIZATION_MISSING"
EVIDENCE_MISSING = "EVIDENCE_MISSING"
EVIDENCE_NOT_VALID = "EVIDENCE_NOT_VALID"


def _blank(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _scalar_fields(s: ReleaseSnapshot) -> dict[str, object]:
    return {
        "releaseName": s.release_name,
        "applicationKey": s.application_key,
        "expectedStart": s.expected_start_utc,
        "expectedEnd": s.expected_end_utc,
        "impact": s.impact,
        "downtimeType": s.downtime_type,
        "downtimeDetails": s.downtime_details,
        "implementationPlan": s.implementation_plan,
        "validationPlan": s.validation_plan,
        "rollbackPlan": s.rollback_plan,
    }


def _same_address(left: str | None, right: str | None) -> bool:
    if left is None or right is None:
        return False
    normalized = left.strip().casefold()
    return bool(normalized) and normalized == right.strip().casefold()


def _approver_authorized(s: ReleaseSnapshot, row: ApprovalSnapshot) -> bool:
    if _same_address(row.approver_email, s.requester_email):
        return False
    if row.approval_type in CONFIGURED_APPROVER_TYPES:
        return _same_address(row.approver_email, s.approvers.get(row.approval_type))
    return not _blank(row.approver_email)


def _approval_checks(s: ReleaseSnapshot, approval_types: Iterable[str]) -> list[str]:
    """One code per type, most fundamental first; every row of the type must be valid (fail closed)."""
    failed: list[str] = []
    for approval_type in approval_types:
        rows = [a for a in s.approvals if a.approval_type == approval_type]
        if approval_type in CONFIGURED_APPROVER_TYPES and _blank(s.approvers.get(approval_type)):
            failed.append(f"{APPROVER_NOT_CONFIGURED}:{approval_type}")
        elif not rows:
            failed.append(f"{APPROVAL_MISSING}:{approval_type}")
        elif any(row.decision != APPROVED for row in rows):
            failed.append(f"{APPROVAL_NOT_APPROVED}:{approval_type}")
        elif not all(_approver_authorized(s, row) for row in rows):
            failed.append(f"{APPROVER_NOT_AUTHORIZED}:{approval_type}")
        elif any(row.decision_at is None or _blank(row.source_message_id) for row in rows):
            failed.append(f"{APPROVAL_EVIDENCE_MISSING}:{approval_type}")
    return failed


def _configured_creation_approvals(s: ReleaseSnapshot) -> list[str]:
    return [t for t in CHANGE_CREATION_APPROVAL_TYPES if t in s.rules.required_approval_types]


def _all_approvals(s: ReleaseSnapshot) -> list[str]:
    """Cumulative approval set re-checked by every gate after CHANGE_CREATION_PENDING."""
    return [*_configured_creation_approvals(s), CHANGE_APPROVAL_TYPE]


def _has_valid_evidence(s: ReleaseSnapshot, evidence_type: str) -> bool:
    return any(e.evidence_type == evidence_type and e.validation_status == VALID for e in s.evidence)


def _production_authorization(s: ReleaseSnapshot) -> list[str]:
    return [] if _has_valid_evidence(s, PRODUCTION_AUTHORIZATION_EVIDENCE) else [PRODUCTION_AUTHORIZATION_MISSING]


def info_complete(s: ReleaseSnapshot) -> list[str]:
    """Mandatory fields complete; at least one component; target versions provided; downtime details if downtime.

    The ``components`` required field is reported once, as COMPONENT_MISSING, which is checked unconditionally.
    """
    scalars = _scalar_fields(s)
    failed = [
        f"{REQUIRED_FIELD_MISSING}:{name}"
        for name in s.rules.required_fields
        if name != "components" and _blank(scalars[name])
    ]
    if not s.components:
        failed.append(COMPONENT_MISSING)
    failed.extend(f"{TARGET_VERSION_MISSING}:{c.name}" for c in s.components if _blank(c.target_version))
    if not _blank(s.downtime_type) and s.downtime_type != NO_DOWNTIME and _blank(s.downtime_details):
        failed.append(DOWNTIME_DETAILS_MISSING)
    return failed


def owner_review(s: ReleaseSnapshot) -> list[str]:
    failed: list[str] = []
    if not s.schema_valid:
        failed.append(SCHEMA_INVALID)
    if s.risk_score is None or _blank(s.risk_level):
        failed.append(RISK_NOT_CALCULABLE)
    if not s.readiness_report_produced:
        failed.append(READINESS_REPORT_MISSING)
    return failed


def change_creation_pending(s: ReleaseSnapshot) -> list[str]:
    return _approval_checks(s, _configured_creation_approvals(s))


def scheduled(s: ReleaseSnapshot) -> list[str]:
    failed = _approval_checks(s, _all_approvals(s))
    if s.expected_start_utc is None or s.expected_end_utc is None:
        failed.append(RELEASE_WINDOW_MISSING)
    else:
        start, end = _utc(s.expected_start_utc), _utc(s.expected_end_utc)
        if end <= start:
            failed.append(RELEASE_WINDOW_INVALID)
        if start <= _utc(s.as_of):
            failed.append(RELEASE_WINDOW_IN_PAST)
    if not any(not _blank(attendee) for attendee in s.attendees):
        failed.append(ATTENDEE_CONFIG_MISSING)
    return failed


def ready_for_release(s: ReleaseSnapshot) -> list[str]:
    failed = _approval_checks(s, _all_approvals(s))
    if s.blockers:
        failed.append(BLOCKERS_PRESENT)
    for value, code in (
        (s.implementation_plan, IMPLEMENTATION_PLAN_MISSING),
        (s.validation_plan, VALIDATION_PLAN_MISSING),
        (s.rollback_plan, ROLLBACK_PLAN_MISSING),
    ):
        if _blank(value):
            failed.append(code)
    return failed


def deploying(s: ReleaseSnapshot) -> list[str]:
    return [*_approval_checks(s, _all_approvals(s)), *_production_authorization(s)]


def completed(s: ReleaseSnapshot) -> list[str]:
    failed = [*_approval_checks(s, _all_approvals(s)), *_production_authorization(s)]
    for evidence_type in s.rules.completion_evidence_required:
        if _has_valid_evidence(s, evidence_type):
            continue
        present = any(e.evidence_type == evidence_type for e in s.evidence)
        failed.append(f"{EVIDENCE_NOT_VALID if present else EVIDENCE_MISSING}:{evidence_type}")
    return failed


GATES: Mapping[str, Gate] = MappingProxyType(
    {
        "INFO_COMPLETE": info_complete,
        "OWNER_REVIEW": owner_review,
        "CHANGE_CREATION_PENDING": change_creation_pending,
        "SCHEDULED": scheduled,
        "READY_FOR_RELEASE": ready_for_release,
        "DEPLOYING": deploying,
        "COMPLETED": completed,
    }
)
