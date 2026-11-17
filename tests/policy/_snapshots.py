"""Release snapshots for state-machine and gate tests (Slice 3; NFR-01, NFR-02; AC-RM-04).

``ready_snapshot`` satisfies every gate in specs/release-lifecycle.md section 4, so a denial in a test that starts from
it is caused only by the single prerequisite the test removes (or by the edge itself).
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

from release_api.domain.gates import PRODUCTION_AUTHORIZATION_EVIDENCE
from release_api.domain.product_rules import ProductRules, load_product_rules
from release_api.domain.snapshot import ApprovalSnapshot, ComponentSnapshot, EvidenceSnapshot, ReleaseSnapshot
from tests._repo import REPO_ROOT

AS_OF = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)
WILEYPLUS_RULES: ProductRules = load_product_rules(REPO_ROOT / "config" / "products" / "wileyplus.yaml")
DECISION_AT = AS_OF - timedelta(days=1)
REQUESTER = "requester@example.com"
# Configured approvers (application_config.business_approver_email / change_manager_email).
APPROVERS = {"BUSINESS": "business@example.com", "CHANGE": "change@example.com"}


def approval(approval_type: str, decision: str = "APPROVED", email: str | None = None) -> ApprovalSnapshot:
    """An approval carrying the decision evidence required by policies/approvals.yaml."""
    approver = email or f"{approval_type.lower()}@example.com"
    return ApprovalSnapshot(
        approval_type=approval_type,
        approver_email=approver,
        decision=decision,
        decision_at=DECISION_AT,
        source_message_id=f"<{approval_type.lower()}.{approver}@mail.example.com>",
    )


def evidence(evidence_type: str, validation_status: str | None = "VALID") -> EvidenceSnapshot:
    return EvidenceSnapshot(evidence_type=evidence_type, validation_status=validation_status)


def ready_snapshot(**overrides: Any) -> ReleaseSnapshot:
    start = AS_OF + timedelta(days=7)
    snapshot = ReleaseSnapshot(
        as_of=AS_OF,
        rules=WILEYPLUS_RULES,
        release_name="WileyPLUS November release",
        application_key="wileyplus",
        expected_start_utc=start,
        expected_end_utc=start + timedelta(hours=2),
        impact="Course pages unavailable for 10 minutes",
        downtime_type="NONE",
        downtime_details=None,
        implementation_plan="Deploy via pipeline",
        validation_plan="Run smoke tests",
        rollback_plan="Redeploy previous version",
        risk_score=5,
        risk_level="LOW",
        components=(ComponentSnapshot(name="web", target_version="1.2.3"),),
        approvals=(approval("TECHNICAL"), approval("BUSINESS"), approval("CHANGE")),
        evidence=(
            evidence(PRODUCTION_AUTHORIZATION_EVIDENCE),
            *(evidence(kind) for kind in WILEYPLUS_RULES.completion_evidence_required),
        ),
        schema_valid=True,
        readiness_report_produced=True,
        blockers=(),
        attendees=("dev-team@example.com",),
        requester_email=REQUESTER,
        approvers=dict(APPROVERS),
    )
    return replace(snapshot, **overrides)
