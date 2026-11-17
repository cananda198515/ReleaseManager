"""Transactional state changes against real MySQL (Slice 3; section 18.2).

A legal transition commits the status change and its release_transition audit row in one transaction. Denied or failed
transitions never advance state and write a ``DENIED:<code>`` audit row (owner decision D2, specs/slices.md).
Requirements: NFR-01, NFR-02, NFR-08; AC-RM-04.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import Engine, event, select
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Mapper, Session, sessionmaker

from release_api.db.models import (
    ApplicationConfig,
    ReleaseApproval,
    ReleaseComponent,
    ReleaseEvidence,
    ReleaseRequest,
    ReleaseTransition,
)
from release_api.domain.gates import PRODUCTION_AUTHORIZATION_EVIDENCE
from release_api.domain.state_machine import (
    GATE_FAILED,
    ILLEGAL_TRANSITION,
    TERMINAL_STATE,
    PolicyDenied,
    default_transition_policy,
)
from release_api.services.transitions import (
    DENIED_REASON_PREFIX,
    TRANSITION_ERROR,
    ReleaseNotFoundError,
    TransitionOutcome,
    TransitionService,
)
from tests.policy._snapshots import APPROVERS, AS_OF, DECISION_AT, REQUESTER, WILEYPLUS_RULES

RELEASE_ID = "REL-20261117-0001"


def _service(engine: Engine) -> TransitionService:
    return TransitionService(
        session_factory=sessionmaker(bind=engine, expire_on_commit=False),
        policy=default_transition_policy(),
        rules=WILEYPLUS_RULES,
        clock=lambda: AS_OF,
    )


def _path_to(status: str) -> list[str]:
    """Shortest allowed path from the initial state, so seeded rows satisfy the database status triggers."""
    policy = default_transition_policy()
    paths = {policy.initial_state: [policy.initial_state]}
    queue = [policy.initial_state]
    while queue:
        current = queue.pop(0)
        for nxt in sorted(policy.transitions.get(current, ())):
            if nxt not in paths:
                paths[nxt] = [*paths[current], nxt]
                queue.append(nxt)
    return paths[status][1:]


def _seed(engine: Engine, *, complete: bool = False, status: str | None = None) -> int:
    fields: dict[str, Any] = {}
    if complete:
        fields = {
            "release_name": "WileyPLUS November release",
            "application_key": "wileyplus",
            "requester_email": REQUESTER,
            "expected_start_utc": AS_OF.replace(tzinfo=None, day=24),
            "impact": "Course pages unavailable for 10 minutes",
            "downtime_type": "NONE",
        }
    with Session(engine) as session, session.begin():
        release = ReleaseRequest(release_id=RELEASE_ID, correlation_id=str(uuid.uuid4()), **fields)
        session.add(release)
        session.flush()
        if complete:
            session.add(ReleaseComponent(release_fk=release.id, component_name="web", target_version="1.2.3"))
        for step in _path_to(status) if status else ():
            release.status = step
            session.flush()
        return release.id


def _request(service: TransitionService, target: str, **kwargs: Any) -> TransitionOutcome:
    params: dict[str, Any] = {
        "release_id": RELEASE_ID,
        "target": target,
        "actor_type": "HUMAN",
        "actor_id": "release.owner@example.com",
        "reason": "requested in test",
        "correlation_id": str(uuid.uuid4()),
    }
    params.update(kwargs)
    return service.request_transition(**params)


def _state(engine: Engine) -> tuple[str, int]:
    with Session(engine) as session:
        release = session.scalars(select(ReleaseRequest).where(ReleaseRequest.release_id == RELEASE_ID)).one()
        return release.status, release.version


def _audit(engine: Engine) -> list[ReleaseTransition]:
    with Session(engine) as session:
        return list(session.scalars(select(ReleaseTransition).order_by(ReleaseTransition.id)))


def test_legal_transition_commits_state_and_audit_together(db: Engine) -> None:
    _seed(db)
    correlation_id = str(uuid.uuid4())
    outcome = _request(_service(db), "CANCELLED", correlation_id=correlation_id)

    assert outcome == TransitionOutcome(release_id=RELEASE_ID, from_state="RECEIVED", to_state="CANCELLED", version=2)
    assert _state(db) == ("CANCELLED", 2)
    [row] = _audit(db)
    assert (row.from_status, row.to_status, row.actor_type, row.actor_id, row.reason, row.correlation_id) == (
        "RECEIVED", "CANCELLED", "HUMAN", "release.owner@example.com", "requested in test", correlation_id
    )


def test_gated_transition_reads_prerequisites_from_database(db: Engine) -> None:
    _seed(db, complete=True)
    _request(_service(db), "INFO_COMPLETE")
    assert _state(db) == ("INFO_COMPLETE", 2)


def test_illegal_transition_is_denied_audited_and_not_applied(db: Engine) -> None:
    _seed(db)
    with pytest.raises(PolicyDenied) as denied:
        _request(_service(db), "COMPLETED")

    assert (denied.value.code, denied.value.http_status) == (ILLEGAL_TRANSITION, 409)
    assert _state(db) == ("RECEIVED", 1)
    [row] = _audit(db)
    assert (row.from_status, row.to_status) == ("RECEIVED", "COMPLETED")
    assert row.reason is not None and row.reason.startswith(f"{DENIED_REASON_PREFIX}{ILLEGAL_TRANSITION}")


def test_gate_failure_is_denied_with_failed_checks_and_not_applied(db: Engine) -> None:
    _seed(db)
    with pytest.raises(PolicyDenied) as denied:
        _request(_service(db), "INFO_COMPLETE")

    assert denied.value.code == GATE_FAILED
    assert "COMPONENT_MISSING" in denied.value.failed_checks
    assert _state(db) == ("RECEIVED", 1)
    [row] = _audit(db)
    assert row.reason is not None
    assert row.reason.startswith(f"{DENIED_REASON_PREFIX}{GATE_FAILED}:")
    assert "COMPONENT_MISSING" in row.reason


def test_terminal_state_exit_is_denied(db: Engine) -> None:
    _seed(db, status="COMPLETED")
    with pytest.raises(PolicyDenied) as denied:
        _request(_service(db), "RECEIVED")
    assert denied.value.code == TERMINAL_STATE
    assert _state(db) == ("COMPLETED", 1)


@pytest.fixture
def failing_audit_insert() -> Iterator[None]:
    """Make the success audit-row insert fail, leaving denial/error audit rows writable."""

    def fail(_mapper: Mapper[Any], _connection: Connection, target: ReleaseTransition) -> None:
        if not (target.reason or "").startswith(DENIED_REASON_PREFIX):
            raise RuntimeError("simulated audit insert failure")

    event.listen(ReleaseTransition, "before_insert", fail)
    yield
    event.remove(ReleaseTransition, "before_insert", fail)


@pytest.mark.usefixtures("failing_audit_insert")
def test_failed_audit_insert_rolls_back_state_change(db: Engine) -> None:
    _seed(db)
    with pytest.raises(RuntimeError, match="simulated audit insert failure"):
        _request(_service(db), "CANCELLED")

    assert _state(db) == ("RECEIVED", 1), "NFR-08: failures never silently advance state"
    [row] = _audit(db)
    assert (row.from_status, row.to_status) == ("RECEIVED", "CANCELLED")
    assert row.reason is not None and row.reason.startswith(f"{DENIED_REASON_PREFIX}{TRANSITION_ERROR}")


def test_unknown_release_raises_not_found_without_audit(db: Engine) -> None:
    with pytest.raises(ReleaseNotFoundError):
        _request(_service(db), "CANCELLED", release_id="REL-20261117-9999")
    assert _audit(db) == []


def test_concurrent_transitions_from_same_state_apply_once(db: Engine) -> None:
    _seed(db)
    service = _service(db)
    barrier = threading.Barrier(2)
    results: list[str] = []

    def attempt() -> None:
        barrier.wait()
        try:
            _request(service, "CANCELLED")
            results.append("ok")
        except PolicyDenied as denied:
            results.append(denied.code)

    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert sorted(results) == sorted(["ok", TERMINAL_STATE])
    assert _state(db) == ("CANCELLED", 2)
    assert [(r.from_status, r.to_status) for r in _audit(db)] == [("RECEIVED", "CANCELLED"), ("CANCELLED", "CANCELLED")]


def test_runtime_identity_can_apply_and_deny_transitions(db: Engine, runtime_engine: Engine) -> None:
    """The least-privilege runtime user (SELECT, INSERT, UPDATE; no DELETE) can run the whole flow."""
    _seed(db)
    service = _service(runtime_engine)
    with pytest.raises(PolicyDenied):
        _request(service, "COMPLETED")
    _request(service, "CANCELLED")
    assert _state(db) == ("CANCELLED", 2)
    assert len(_audit(db)) == 2


# --- High findings #1-#3 through the database: approvals and evidence rows reach the gates -------------------------


def _approval_row(fk: int, approval_type: str, **changes: Any) -> ReleaseApproval:
    email = changes.pop("approver_email", APPROVERS.get(approval_type, f"{approval_type.lower()}@example.com"))
    fields: dict[str, Any] = {
        "release_fk": fk,
        "approval_type": approval_type,
        "approver_email": email,
        "decision": "APPROVED",
        "decision_at": DECISION_AT.replace(tzinfo=None),
        "source_message_id": f"<{approval_type.lower()}@mail.example.com>",
    }
    fields.update(changes)
    return ReleaseApproval(**fields)


def _seed_governed(
    engine: Engine,
    status: str,
    *,
    approvals: dict[str, dict[str, Any]] | None = None,
    evidence: tuple[str, ...] = (),
    configured: bool = True,
) -> None:
    fk = _seed(engine, complete=True, status=status)
    overrides = approvals or {}
    with Session(engine) as session, session.begin():
        if configured:
            session.add(
                ApplicationConfig(
                    application_key="wileyplus",
                    display_name="WileyPLUS",
                    business_approver_email=APPROVERS["BUSINESS"],
                    change_manager_email=APPROVERS["CHANGE"],
                )
            )
        for approval_type in ("TECHNICAL", "BUSINESS", "CHANGE"):
            if overrides.get(approval_type) != {"absent": True}:
                session.add(_approval_row(fk, approval_type, **overrides.get(approval_type, {})))
        for evidence_type in evidence:
            session.add(
                ReleaseEvidence(
                    release_fk=fk,
                    evidence_type=evidence_type,
                    source_system="test",
                    source_reference=f"test://{evidence_type}",
                    validation_status="VALID",
                )
            )


def _denied_checks(engine: Engine, target: str) -> tuple[str, ...]:
    before = _state(engine)
    with pytest.raises(PolicyDenied) as denied:
        _request(_service(engine), target)
    assert denied.value.code == GATE_FAILED
    assert _state(engine) == before, "denied transition must not change state"
    return denied.value.failed_checks


def test_db_approvals_with_decision_evidence_allow_change_creation(db: Engine) -> None:
    _seed_governed(db, "BUSINESS_APPROVAL_PENDING")
    _request(_service(db), "CHANGE_CREATION_PENDING")
    assert _state(db)[0] == "CHANGE_CREATION_PENDING"


@pytest.mark.parametrize(
    ("approvals", "code"),
    [
        ({"BUSINESS": {"decision": "UNCLEAR"}}, "APPROVAL_NOT_APPROVED:BUSINESS"),
        ({"BUSINESS": {"source_message_id": None}}, "APPROVAL_EVIDENCE_MISSING:BUSINESS"),
        ({"BUSINESS": {"decision_at": None}}, "APPROVAL_EVIDENCE_MISSING:BUSINESS"),
        ({"BUSINESS": {"approver_email": "attacker@evil.test"}}, "APPROVER_NOT_AUTHORIZED:BUSINESS"),
        ({"TECHNICAL": {"approver_email": REQUESTER}}, "APPROVER_NOT_AUTHORIZED:TECHNICAL"),
        ({"TECHNICAL": {"absent": True}}, "APPROVAL_MISSING:TECHNICAL"),
    ],
    ids=lambda v: v if isinstance(v, str) else None,
)
def test_db_approval_rows_are_enforced(db: Engine, approvals: dict[str, dict[str, Any]], code: str) -> None:
    _seed_governed(db, "BUSINESS_APPROVAL_PENDING", approvals=approvals)
    assert _denied_checks(db, "CHANGE_CREATION_PENDING") == (code,)


def test_db_missing_application_config_fails_closed(db: Engine) -> None:
    _seed_governed(db, "BUSINESS_APPROVAL_PENDING", configured=False)
    assert _denied_checks(db, "CHANGE_CREATION_PENDING") == ("APPROVER_NOT_CONFIGURED:BUSINESS",)


ALL_COMPLETION_EVIDENCE = (PRODUCTION_AUTHORIZATION_EVIDENCE, *WILEYPLUS_RULES.completion_evidence_required)


def test_db_completed_requires_smoke_test_evidence(db: Engine) -> None:
    without_smoke = tuple(e for e in ALL_COMPLETION_EVIDENCE if e != "smoke_test")
    _seed_governed(db, "VALIDATING", evidence=without_smoke)
    assert _denied_checks(db, "COMPLETED") == ("EVIDENCE_MISSING:smoke_test",)


def test_db_completed_with_all_evidence_and_approvals_succeeds(db: Engine) -> None:
    _seed_governed(db, "VALIDATING", evidence=ALL_COMPLETION_EVIDENCE)
    _request(_service(db), "COMPLETED")
    assert _state(db)[0] == "COMPLETED"


@pytest.mark.parametrize(
    ("approvals", "code"),
    [
        ({"TECHNICAL": {"decision": "REJECTED"}}, "APPROVAL_NOT_APPROVED:TECHNICAL"),
        ({"CHANGE": {"decision": "REJECTED"}}, "APPROVAL_NOT_APPROVED:CHANGE"),
    ],
    ids=lambda v: v if isinstance(v, str) else None,
)
def test_db_revoked_approval_blocks_completed(db: Engine, approvals: dict[str, dict[str, Any]], code: str) -> None:
    _seed_governed(db, "VALIDATING", approvals=approvals, evidence=ALL_COMPLETION_EVIDENCE)
    assert _denied_checks(db, "COMPLETED") == (code,)
