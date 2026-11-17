"""Approval and evidence bypass paths found in the Slice 3 review (High findings #1-#5).

Each test reproduces a path that previously reached a gated state without its approvals or evidence. Owner decisions
(17 Nov 2026, specs/slices.md #32): later gates re-check every earlier approval (cumulative); APPROVED approvals need
decision evidence; requesters cannot approve; BUSINESS/CHANGE approvers must match application_config.
Requirements: BR-08, BR-09, BR-10, BR-12, NFR-01, NFR-02; AC-RM-04, AC-RM-05, AC-RM-06, AC-RM-07, AC-RM-08.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from release_api.domain.gates import PRODUCTION_AUTHORIZATION_EVIDENCE
from release_api.domain.snapshot import ApprovalSnapshot, ReleaseSnapshot
from release_api.domain.state_machine import GATE_FAILED, PolicyDenied, can_transition
from tests.policy._snapshots import approval, ready_snapshot

ENTRY = {
    "CHANGE_CREATION_PENDING": "BUSINESS_APPROVAL_PENDING",
    "SCHEDULED": "CHANGE_APPROVAL_PENDING",
    "READY_FOR_RELEASE": "SCHEDULED",
    "DEPLOYING": "READY_FOR_RELEASE",
    "COMPLETED": "VALIDATING",
}
AFTER_CHANGE_CREATION = ("SCHEDULED", "READY_FOR_RELEASE", "DEPLOYING", "COMPLETED")
APPROVAL_GATES = ("CHANGE_CREATION_PENDING", *AFTER_CHANGE_CREATION)


def failed_checks(target: str, snapshot: ReleaseSnapshot) -> tuple[str, ...]:
    with pytest.raises(PolicyDenied) as denied:
        can_transition(ENTRY[target], target, snapshot)
    assert denied.value.code == GATE_FAILED
    return denied.value.failed_checks


def replacing(approval_type: str, *rows: ApprovalSnapshot) -> ReleaseSnapshot:
    base = ready_snapshot()
    kept = tuple(a for a in base.approvals if a.approval_type != approval_type)
    return replace(base, approvals=(*kept, *rows))


# --- #1 approvals are re-checked by every later gate (P4, P5, P6) ---------------------------------------------------


@pytest.mark.parametrize("target", AFTER_CHANGE_CREATION)
@pytest.mark.parametrize(("approval_type", "decision"), [("TECHNICAL", "REJECTED"), ("BUSINESS", "UNCLEAR"),
                                                         ("TECHNICAL", "PENDING")])
def test_revoked_technical_or_business_approval_blocks_later_gates(
    target: str, approval_type: str, decision: str
) -> None:
    snapshot = replacing(approval_type, approval(approval_type, decision))
    assert failed_checks(target, snapshot) == (f"APPROVAL_NOT_APPROVED:{approval_type}",)


@pytest.mark.parametrize("target", ["DEPLOYING", "COMPLETED"])
@pytest.mark.parametrize("decision", ["REJECTED", "UNCLEAR", "PENDING"])
def test_revoked_change_approval_blocks_deploying_and_completed(target: str, decision: str) -> None:
    assert failed_checks(target, replacing("CHANGE", approval("CHANGE", decision))) == (
        "APPROVAL_NOT_APPROVED:CHANGE",
    )


@pytest.mark.parametrize("target", ["DEPLOYING", "COMPLETED"])
def test_missing_change_approval_blocks_deploying_and_completed(target: str) -> None:
    assert failed_checks(target, replacing("CHANGE")) == ("APPROVAL_MISSING:CHANGE",)


def test_completed_requires_production_authorization() -> None:
    base = ready_snapshot()
    kept = tuple(e for e in base.evidence if e.evidence_type != PRODUCTION_AUTHORIZATION_EVIDENCE)
    assert failed_checks("COMPLETED", replace(base, evidence=kept)) == ("PRODUCTION_AUTHORIZATION_MISSING",)


# --- #2 APPROVED needs decision evidence (policies/approvals.yaml evidence_required; P11) ----------------------------


@pytest.mark.parametrize("target", APPROVAL_GATES)
@pytest.mark.parametrize(
    "missing", [{"decision_at": None}, {"source_message_id": None}, {"source_message_id": "  "}], ids=str
)
def test_approved_without_decision_evidence_does_not_count(target: str, missing: dict[str, Any]) -> None:
    snapshot = replacing("BUSINESS", replace(approval("BUSINESS"), **missing))
    assert failed_checks(target, snapshot) == ("APPROVAL_EVIDENCE_MISSING:BUSINESS",)


@pytest.mark.parametrize("target", AFTER_CHANGE_CREATION)
def test_change_approval_without_decision_evidence_does_not_count(target: str) -> None:
    assert failed_checks(target, replacing("CHANGE", replace(approval("CHANGE"), source_message_id=None))) == (
        "APPROVAL_EVIDENCE_MISSING:CHANGE",
    )


# --- #3 approver identity (P7) ----------------------------------------------------------------------------------------


@pytest.mark.parametrize("approval_type", ["TECHNICAL", "BUSINESS", "CHANGE"])
@pytest.mark.parametrize("requester", ["requester@example.com", " Requester@Example.COM "])
def test_requester_cannot_approve(approval_type: str, requester: str) -> None:
    base = replacing(approval_type, approval(approval_type, email="requester@example.com"))
    approvers = {k: "requester@example.com" for k in base.approvers}  # even if also the configured approver
    snapshot = replace(base, requester_email=requester, approvers=approvers)
    target = "CHANGE_CREATION_PENDING" if approval_type != "CHANGE" else "SCHEDULED"
    assert f"APPROVER_NOT_AUTHORIZED:{approval_type}" in failed_checks(target, snapshot)


@pytest.mark.parametrize(("approval_type", "target"), [("BUSINESS", "CHANGE_CREATION_PENDING"), ("CHANGE", "SCHEDULED"),
                                                       ("BUSINESS", "COMPLETED"), ("CHANGE", "DEPLOYING")])
def test_approval_from_unconfigured_approver_does_not_count(approval_type: str, target: str) -> None:
    snapshot = replacing(approval_type, approval(approval_type, email="attacker@evil.test"))
    assert failed_checks(target, snapshot) == (f"APPROVER_NOT_AUTHORIZED:{approval_type}",)


def test_extra_unauthorized_approval_row_fails_closed() -> None:
    base = ready_snapshot()
    snapshot = replace(base, approvals=(*base.approvals, approval("BUSINESS", email="someone-else@example.com")))
    assert failed_checks("CHANGE_CREATION_PENDING", snapshot) == ("APPROVER_NOT_AUTHORIZED:BUSINESS",)


@pytest.mark.parametrize(
    ("approval_type", "target"), [("BUSINESS", "CHANGE_CREATION_PENDING"), ("CHANGE", "SCHEDULED")]
)
@pytest.mark.parametrize("configured", [None, "", "  "])
def test_unconfigured_approver_fails_closed(approval_type: str, target: str, configured: str | None) -> None:
    base = ready_snapshot()
    approvers = {k: v for k, v in base.approvers.items() if k != approval_type}
    if configured is not None:
        approvers[approval_type] = configured
    assert failed_checks(target, replace(base, approvers=approvers)) == (f"APPROVER_NOT_CONFIGURED:{approval_type}",)


def test_configured_approver_match_is_case_insensitive() -> None:
    base = replacing("BUSINESS", approval("BUSINESS", email="Business@Example.com"))
    assert can_transition("BUSINESS_APPROVAL_PENDING", "CHANGE_CREATION_PENDING", base)


def test_technical_approver_may_be_any_non_requester() -> None:
    snapshot = replacing("TECHNICAL", approval("TECHNICAL", email="tech-lead@example.com"))
    assert can_transition("BUSINESS_APPROVAL_PENDING", "CHANGE_CREATION_PENDING", snapshot)
