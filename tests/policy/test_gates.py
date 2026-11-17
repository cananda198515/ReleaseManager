"""Deterministic gates (specs/release-lifecycle.md section 4; policies/approvals.yaml).

One test per missing prerequisite, asserting the exact failed check code. Each test starts from ``ready_snapshot`` (all
gates satisfied) and removes exactly one prerequisite, entering the gated state through an allowed edge.
UNCLEAR, PENDING and REJECTED approvals never count as APPROVED; only VALID evidence counts.
Requirements: BR-06, BR-09, BR-10, BR-12, NFR-01, NFR-02, NFR-08; AC-RM-04, AC-RM-06, AC-RM-07, AC-RM-08.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from typing import Any

import pytest

from release_api.domain.gates import GATES, PRODUCTION_AUTHORIZATION_EVIDENCE
from release_api.domain.snapshot import ComponentSnapshot, ReleaseSnapshot
from release_api.domain.state_machine import GATE_FAILED, Allowed, PolicyDenied, can_transition
from tests._repo import load_yaml
from tests.policy._snapshots import AS_OF, WILEYPLUS_RULES, approval, evidence, ready_snapshot

# Allowed edge used to enter each gated state.
ENTRY = {
    "INFO_COMPLETE": "RECEIVED",
    "OWNER_REVIEW": "VALIDATION_PENDING",
    "CHANGE_CREATION_PENDING": "BUSINESS_APPROVAL_PENDING",
    "SCHEDULED": "CHANGE_APPROVAL_PENDING",
    "READY_FOR_RELEASE": "SCHEDULED",
    "DEPLOYING": "READY_FOR_RELEASE",
    "COMPLETED": "VALIDATING",
}
NOT_APPROVED = ("PENDING", "UNCLEAR", "REJECTED")
COMPLETION_TYPES = WILEYPLUS_RULES.completion_evidence_required


def failed_checks(target: str, snapshot: ReleaseSnapshot) -> tuple[str, ...]:
    with pytest.raises(PolicyDenied) as denied:
        can_transition(ENTRY[target], target, snapshot)
    assert denied.value.code == GATE_FAILED
    assert denied.value.http_status == 409
    return denied.value.failed_checks


def passes(target: str, snapshot: ReleaseSnapshot) -> bool:
    return can_transition(ENTRY[target], target, snapshot) == Allowed(from_state=ENTRY[target], to_state=target)


def without_approval(approval_type: str, **extra: Any) -> ReleaseSnapshot:
    base = ready_snapshot(**extra)
    return replace(base, approvals=tuple(a for a in base.approvals if a.approval_type != approval_type))


def with_approval_decision(approval_type: str, decision: str) -> ReleaseSnapshot:
    base = without_approval(approval_type)
    return replace(base, approvals=(*base.approvals, approval(approval_type, decision)))


def with_evidence(evidence_type: str, *statuses: str | None) -> ReleaseSnapshot:
    base = ready_snapshot()
    kept = tuple(e for e in base.evidence if e.evidence_type != evidence_type)
    return replace(base, evidence=(*kept, *(evidence(evidence_type, s) for s in statuses)))


# --- registry ------------------------------------------------------------------------------------------------------


def test_every_policy_gate_has_an_implementation_and_vice_versa() -> None:
    assert set(GATES) == set(load_yaml("policies/state-transitions.yaml")["gates"]) == set(ENTRY)


@pytest.mark.parametrize("target", sorted(ENTRY))
def test_ready_snapshot_passes_every_gate(target: str) -> None:
    assert passes(target, ready_snapshot())


@pytest.mark.parametrize(
    ("current", "target"),
    [("RECEIVED", "CANCELLED"), ("RECEIVED", "ERROR"), ("PENDING_INFORMATION", "MANUAL_REVIEW"),
     ("VALIDATION_PENDING", "MANUAL_REVIEW"), ("DEPLOYING", "ROLLED_BACK"), ("VALIDATING", "FAILED")],
)
def test_exception_routes_are_not_gated(current: str, target: str) -> None:
    """NFR-08: failures must always be able to route to error, cancellation or human review."""
    bare = ReleaseSnapshot(as_of=AS_OF, rules=WILEYPLUS_RULES)
    assert can_transition(current, target, bare) == Allowed(from_state=current, to_state=target)


# --- INFO_COMPLETE ---------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("override", "code"),
    [
        ({"release_name": None}, "REQUIRED_FIELD_MISSING:releaseName"),
        ({"release_name": "   "}, "REQUIRED_FIELD_MISSING:releaseName"),
        ({"application_key": None}, "REQUIRED_FIELD_MISSING:applicationKey"),
        ({"expected_start_utc": None}, "REQUIRED_FIELD_MISSING:expectedStart"),
        ({"impact": ""}, "REQUIRED_FIELD_MISSING:impact"),
        ({"downtime_type": None}, "REQUIRED_FIELD_MISSING:downtimeType"),
        ({"components": ()}, "COMPONENT_MISSING"),
        ({"components": (ComponentSnapshot(name="web", target_version=None),)}, "TARGET_VERSION_MISSING:web"),
        ({"components": (ComponentSnapshot(name="api", target_version=" "),)}, "TARGET_VERSION_MISSING:api"),
        ({"downtime_type": "PARTIAL", "downtime_details": None}, "DOWNTIME_DETAILS_MISSING"),
        ({"downtime_type": "FULL", "downtime_details": "  "}, "DOWNTIME_DETAILS_MISSING"),
    ],
    ids=lambda value: value if isinstance(value, str) else None,
)
def test_info_complete_missing_prerequisite(override: dict[str, Any], code: str) -> None:
    assert failed_checks("INFO_COMPLETE", ready_snapshot(**override)) == (code,)


def test_info_complete_reports_only_the_component_missing_its_target_version() -> None:
    components = (
        ComponentSnapshot(name="web", target_version="1.2.3"),
        ComponentSnapshot(name="worker", target_version=None),
    )
    assert failed_checks("INFO_COMPLETE", ready_snapshot(components=components)) == ("TARGET_VERSION_MISSING:worker",)


def test_info_complete_downtime_details_satisfy_partial_downtime() -> None:
    assert passes("INFO_COMPLETE", ready_snapshot(downtime_type="PARTIAL", downtime_details="Reports read-only 5 min"))


def test_info_complete_honours_product_required_plans() -> None:
    rules = replace(WILEYPLUS_RULES, required_fields=(*WILEYPLUS_RULES.required_fields, "rollbackPlan"))
    assert failed_checks("INFO_COMPLETE", ready_snapshot(rules=rules, rollback_plan=None)) == (
        "REQUIRED_FIELD_MISSING:rollbackPlan",
    )
    assert passes("INFO_COMPLETE", ready_snapshot(rollback_plan=None)), "plans are not required by WileyPLUS config"


def test_info_complete_bare_release_reports_every_missing_prerequisite() -> None:
    bare = ReleaseSnapshot(as_of=AS_OF, rules=WILEYPLUS_RULES)
    assert set(failed_checks("INFO_COMPLETE", bare)) == {
        "REQUIRED_FIELD_MISSING:releaseName",
        "REQUIRED_FIELD_MISSING:applicationKey",
        "REQUIRED_FIELD_MISSING:expectedStart",
        "REQUIRED_FIELD_MISSING:impact",
        "REQUIRED_FIELD_MISSING:downtimeType",
        "COMPONENT_MISSING",
    }


# --- OWNER_REVIEW ----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("override", "code"),
    [
        ({"schema_valid": False}, "SCHEMA_INVALID"),
        ({"risk_score": None}, "RISK_NOT_CALCULABLE"),
        ({"risk_level": None}, "RISK_NOT_CALCULABLE"),
        ({"readiness_report_produced": False}, "READINESS_REPORT_MISSING"),
    ],
    ids=lambda value: value if isinstance(value, str) else None,
)
def test_owner_review_missing_prerequisite(override: dict[str, Any], code: str) -> None:
    assert failed_checks("OWNER_REVIEW", ready_snapshot(**override)) == (code,)


# --- CHANGE_CREATION_PENDING -----------------------------------------------------------------------------------------


@pytest.mark.parametrize("approval_type", ["TECHNICAL", "BUSINESS"])
def test_change_creation_requires_configured_approval(approval_type: str) -> None:
    assert failed_checks("CHANGE_CREATION_PENDING", without_approval(approval_type)) == (
        f"APPROVAL_MISSING:{approval_type}",
    )


@pytest.mark.parametrize("decision", NOT_APPROVED)
@pytest.mark.parametrize("approval_type", ["TECHNICAL", "BUSINESS"])
def test_change_creation_never_counts_non_approved_decisions(approval_type: str, decision: str) -> None:
    assert failed_checks("CHANGE_CREATION_PENDING", with_approval_decision(approval_type, decision)) == (
        f"APPROVAL_NOT_APPROVED:{approval_type}",
    )


@pytest.mark.parametrize("decision", NOT_APPROVED)
def test_change_creation_requires_every_approver_of_a_type(decision: str) -> None:
    base = ready_snapshot()
    snapshot = replace(base, approvals=(*base.approvals, approval("TECHNICAL", decision, "second-tech@example.com")))
    assert failed_checks("CHANGE_CREATION_PENDING", snapshot) == ("APPROVAL_NOT_APPROVED:TECHNICAL",)


def test_change_creation_ignores_unconfigured_approval_types() -> None:
    rules = replace(WILEYPLUS_RULES, required_approval_types=frozenset({"TECHNICAL", "CHANGE"}))
    assert passes("CHANGE_CREATION_PENDING", without_approval("BUSINESS", rules=rules))


def test_change_creation_does_not_require_change_approval_yet() -> None:
    assert passes("CHANGE_CREATION_PENDING", without_approval("CHANGE"))


def test_other_approval_types_never_substitute() -> None:
    snapshot = without_approval("TECHNICAL")
    snapshot = replace(snapshot, approvals=(*snapshot.approvals, approval("SRE"), approval("RELEASE_OWNER")))
    assert failed_checks("CHANGE_CREATION_PENDING", snapshot) == ("APPROVAL_MISSING:TECHNICAL",)


# --- SCHEDULED -------------------------------------------------------------------------------------------------------


def test_scheduled_requires_change_approval() -> None:
    assert failed_checks("SCHEDULED", without_approval("CHANGE")) == ("APPROVAL_MISSING:CHANGE",)


@pytest.mark.parametrize("decision", NOT_APPROVED)
def test_scheduled_never_counts_non_approved_change(decision: str) -> None:
    assert failed_checks("SCHEDULED", with_approval_decision("CHANGE", decision)) == ("APPROVAL_NOT_APPROVED:CHANGE",)


@pytest.mark.parametrize(
    ("override", "code"),
    [
        ({"expected_start_utc": None}, "RELEASE_WINDOW_MISSING"),
        ({"expected_end_utc": None}, "RELEASE_WINDOW_MISSING"),
        ({"expected_end_utc": AS_OF + timedelta(days=7)}, "RELEASE_WINDOW_INVALID"),
        ({"expected_end_utc": AS_OF + timedelta(days=6)}, "RELEASE_WINDOW_INVALID"),
        ({"expected_start_utc": AS_OF, "expected_end_utc": AS_OF + timedelta(hours=1)}, "RELEASE_WINDOW_IN_PAST"),
        (
            {"expected_start_utc": AS_OF - timedelta(hours=2), "expected_end_utc": AS_OF + timedelta(hours=1)},
            "RELEASE_WINDOW_IN_PAST",
        ),
        ({"attendees": ()}, "ATTENDEE_CONFIG_MISSING"),
        ({"attendees": ("  ",)}, "ATTENDEE_CONFIG_MISSING"),
    ],
    ids=lambda value: value if isinstance(value, str) else None,
)
def test_scheduled_missing_prerequisite(override: dict[str, Any], code: str) -> None:
    assert failed_checks("SCHEDULED", ready_snapshot(**override)) == (code,)


def test_scheduled_treats_naive_database_datetimes_as_utc() -> None:
    start = (AS_OF + timedelta(days=1)).replace(tzinfo=None)
    assert passes("SCHEDULED", ready_snapshot(expected_start_utc=start, expected_end_utc=start + timedelta(hours=1)))
    past = (AS_OF - timedelta(minutes=1)).replace(tzinfo=None)
    assert failed_checks(
        "SCHEDULED", ready_snapshot(expected_start_utc=past, expected_end_utc=past + timedelta(hours=1))
    ) == ("RELEASE_WINDOW_IN_PAST",)


# --- READY_FOR_RELEASE -----------------------------------------------------------------------------------------------


def test_ready_for_release_requires_change_still_approved() -> None:
    assert failed_checks("READY_FOR_RELEASE", without_approval("CHANGE")) == ("APPROVAL_MISSING:CHANGE",)


@pytest.mark.parametrize("decision", NOT_APPROVED)
def test_ready_for_release_never_counts_non_approved_change(decision: str) -> None:
    assert failed_checks("READY_FOR_RELEASE", with_approval_decision("CHANGE", decision)) == (
        "APPROVAL_NOT_APPROVED:CHANGE",
    )


@pytest.mark.parametrize(
    ("override", "code"),
    [
        ({"blockers": ("Sev1 incident open",)}, "BLOCKERS_PRESENT"),
        ({"implementation_plan": None}, "IMPLEMENTATION_PLAN_MISSING"),
        ({"validation_plan": " "}, "VALIDATION_PLAN_MISSING"),
        ({"rollback_plan": None}, "ROLLBACK_PLAN_MISSING"),
    ],
    ids=lambda value: value if isinstance(value, str) else None,
)
def test_ready_for_release_missing_prerequisite(override: dict[str, Any], code: str) -> None:
    assert failed_checks("READY_FOR_RELEASE", ready_snapshot(**override)) == (code,)


def test_golden_ready_for_release_with_missing_rollback_plan_is_denied() -> None:
    """Section 13.1 golden case: READY_FOR_RELEASE with missing rollback plan -> policy denial."""
    assert "ROLLBACK_PLAN_MISSING" in failed_checks("READY_FOR_RELEASE", ready_snapshot(rollback_plan=""))


# --- DEPLOYING -------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("statuses", [(), ("UNVERIFIED",), ("INVALID",), (None,)], ids=str)
def test_deploying_requires_valid_human_production_authorization(statuses: tuple[str | None, ...]) -> None:
    snapshot = with_evidence(PRODUCTION_AUTHORIZATION_EVIDENCE, *statuses)
    assert failed_checks("DEPLOYING", snapshot) == ("PRODUCTION_AUTHORIZATION_MISSING",)


def test_deploying_is_not_authorized_by_approvals() -> None:
    snapshot = with_evidence(PRODUCTION_AUTHORIZATION_EVIDENCE)
    snapshot = replace(snapshot, approvals=(*snapshot.approvals, approval("RELEASE_OWNER"), approval("SRE")))
    assert failed_checks("DEPLOYING", snapshot) == ("PRODUCTION_AUTHORIZATION_MISSING",)


# --- COMPLETED -------------------------------------------------------------------------------------------------------


def test_wileyplus_completion_evidence_set() -> None:
    assert COMPLETION_TYPES == ("deployment_result", "smoke_test", "health_check", "monitoring_observation")


@pytest.mark.parametrize("evidence_type", COMPLETION_TYPES)
def test_completed_requires_each_evidence_type(evidence_type: str) -> None:
    assert failed_checks("COMPLETED", with_evidence(evidence_type)) == (f"EVIDENCE_MISSING:{evidence_type}",)


@pytest.mark.parametrize("statuses", [("UNVERIFIED",), ("INVALID",), (None,), ("INVALID", "UNVERIFIED")], ids=str)
@pytest.mark.parametrize("evidence_type", COMPLETION_TYPES)
def test_completed_requires_validated_evidence(evidence_type: str, statuses: tuple[str | None, ...]) -> None:
    assert failed_checks("COMPLETED", with_evidence(evidence_type, *statuses)) == (
        f"EVIDENCE_NOT_VALID:{evidence_type}",
    )


def test_completed_accepts_one_valid_row_among_invalid_ones() -> None:
    assert passes("COMPLETED", with_evidence("smoke_test", "INVALID", "VALID"))


def test_golden_no_smoke_test_cannot_reach_completed() -> None:
    """Section 13.1 golden case: pipeline starts but no smoke test is present -> cannot reach COMPLETED."""
    assert "EVIDENCE_MISSING:smoke_test" in failed_checks("COMPLETED", with_evidence("smoke_test"))
