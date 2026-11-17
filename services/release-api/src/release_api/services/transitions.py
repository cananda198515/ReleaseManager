"""Apply release state transitions transactionally (Slice 3; section 18.2).

The release row is locked (SELECT ... FOR UPDATE), the domain state machine decides, and on success the status change,
version increment and ``release_transition`` audit row commit in one transaction. Denied or failed attempts roll back
and are recorded as a ``release_transition`` row whose reason starts with ``DENIED:<code>`` and whose ``to_status`` is
the *requested* state (owner decision D2, specs/slices.md); readers must use the prefix to tell denials from changes.
Requirements: NFR-01, NFR-02, NFR-08; AC-RM-04.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from release_api.db.models import (
    ApplicationConfig,
    ReleaseApproval,
    ReleaseComponent,
    ReleaseEvidence,
    ReleaseRequest,
    ReleaseTransition,
)
from release_api.domain.product_rules import ProductRules
from release_api.domain.snapshot import ApprovalSnapshot, ComponentSnapshot, EvidenceSnapshot, ReleaseSnapshot
from release_api.domain.state_machine import (
    DEFAULT_POLICY_PATH,
    PolicyDenied,
    TransitionPolicy,
    can_transition,
    load_transition_policy,
)
from release_api.settings import Settings

DENIED_REASON_PREFIX = "DENIED:"
TRANSITION_ERROR = "TRANSITION_ERROR"
MAX_REASON_LENGTH = 2000  # release_transition.reason VARCHAR(2000)
MAX_STATE_LENGTH = 50  # release_transition.to_status VARCHAR(50)
MAX_ACTOR_TYPE_LENGTH = 30
MAX_ACTOR_ID_LENGTH = 320
RELEASE_ID_PATTERN = re.compile(r"^REL-\d{8}-\d{4}$")


class ReleaseNotFoundError(LookupError):
    """No release exists with the requested release_id."""


@dataclass(frozen=True)
class TransitionOutcome:
    release_id: str
    from_state: str
    to_state: str
    version: int


@dataclass(frozen=True)
class GateFacts:
    """Gate inputs with no database column yet; produced by later slices. Defaults fail closed."""

    schema_valid: bool = False
    readiness_report_produced: bool = False
    blockers: tuple[str, ...] = ()
    attendees: tuple[str, ...] = ()


FactsProvider = Callable[[Session, ReleaseRequest], GateFacts]


def no_gate_facts(_session: Session, _release: ReleaseRequest) -> GateFacts:
    return GateFacts()


def transition_policy_from_settings(settings: Settings) -> TransitionPolicy:
    return load_transition_policy(settings.state_transitions_policy_path or DEFAULT_POLICY_PATH)


def denial_reason(code: str, failed_checks: tuple[str, ...], reason: str | None) -> str:
    text = f"{DENIED_REASON_PREFIX}{code}"
    if failed_checks:
        text += ":" + ",".join(failed_checks)
    if reason:
        text += f" | {reason}"
    return text[:MAX_REASON_LENGTH]


def load_release_snapshot(
    session: Session, release: ReleaseRequest, rules: ProductRules, as_of: datetime, facts: GateFacts
) -> ReleaseSnapshot:
    components = session.scalars(
        select(ReleaseComponent).where(ReleaseComponent.release_fk == release.id).order_by(ReleaseComponent.id)
    )
    approvals = session.scalars(select(ReleaseApproval).where(ReleaseApproval.release_fk == release.id))
    evidence = session.scalars(select(ReleaseEvidence).where(ReleaseEvidence.release_fk == release.id))
    return ReleaseSnapshot(
        as_of=as_of,
        rules=rules,
        release_name=release.release_name,
        application_key=release.application_key,
        expected_start_utc=release.expected_start_utc,
        expected_end_utc=release.expected_end_utc,
        impact=release.impact,
        downtime_type=release.downtime_type,
        downtime_details=release.downtime_details,
        implementation_plan=release.implementation_plan,
        validation_plan=release.validation_plan,
        rollback_plan=release.rollback_plan,
        risk_score=release.risk_score,
        risk_level=release.risk_level,
        components=tuple(ComponentSnapshot(name=c.component_name, target_version=c.target_version) for c in components),
        approvals=tuple(
            ApprovalSnapshot(
                approval_type=a.approval_type,
                approver_email=a.approver_email,
                decision=a.decision,
                decision_at=a.decision_at,
                source_message_id=a.source_message_id,
            )
            for a in approvals
        ),
        evidence=tuple(
            EvidenceSnapshot(evidence_type=e.evidence_type, validation_status=e.validation_status) for e in evidence
        ),
        schema_valid=facts.schema_valid,
        readiness_report_produced=facts.readiness_report_produced,
        blockers=facts.blockers,
        attendees=facts.attendees,
        requester_email=release.requester_email,
        approvers=_configured_approvers(session, release.application_key),
    )


def _configured_approvers(session: Session, application_key: str | None) -> dict[str, str]:
    """BUSINESS/CHANGE approvers from the active application_config row; absent values fail closed in the gates."""
    if application_key is None:
        return {}
    config = session.scalars(
        select(ApplicationConfig).where(
            ApplicationConfig.application_key == application_key, ApplicationConfig.active.is_(True)
        )
    ).one_or_none()
    if config is None:
        return {}
    configured = {"BUSINESS": config.business_approver_email, "CHANGE": config.change_manager_email}
    return {approval_type: email for approval_type, email in configured.items() if email}


def _validate(
    release_id: str, target: str, actor_type: str, actor_id: str | None, reason: str | None, correlation_id: str
) -> None:
    if not RELEASE_ID_PATTERN.fullmatch(release_id):
        raise ValueError("release_id must match REL-YYYYMMDD-NNNN")
    if not target or len(target) > MAX_STATE_LENGTH:
        raise ValueError(f"target must be 1..{MAX_STATE_LENGTH} characters")
    if not actor_type.strip() or len(actor_type) > MAX_ACTOR_TYPE_LENGTH:
        raise ValueError(f"actor_type must be 1..{MAX_ACTOR_TYPE_LENGTH} characters")
    if actor_id is not None and len(actor_id) > MAX_ACTOR_ID_LENGTH:
        raise ValueError(f"actor_id must be at most {MAX_ACTOR_ID_LENGTH} characters")
    if reason is not None and len(reason) > MAX_REASON_LENGTH:
        raise ValueError(f"reason must be at most {MAX_REASON_LENGTH} characters")
    try:
        canonical = str(uuid.UUID(correlation_id))
    except (ValueError, AttributeError, TypeError):
        raise ValueError("correlation_id must be a UUID") from None
    if canonical != correlation_id.lower():
        raise ValueError("correlation_id must be a canonical 36-character UUID")


class _Rollback(Exception):
    """Internal control flow: roll back the transition transaction; never leaves this module."""


class TransitionService:
    def __init__(
        self,
        *,
        session_factory: Callable[[], Session],
        policy: TransitionPolicy,
        rules: ProductRules,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        facts: FactsProvider = no_gate_facts,
    ) -> None:
        self._session_factory = session_factory
        self._policy = policy
        self._rules = rules
        self._clock = clock
        self._facts = facts

    def request_transition(
        self,
        *,
        release_id: str,
        target: str,
        actor_type: str,
        actor_id: str | None,
        reason: str | None,
        correlation_id: str,
    ) -> TransitionOutcome:
        _validate(release_id, target, actor_type, actor_id, reason, correlation_id)
        audit = {"actor_type": actor_type, "actor_id": actor_id, "correlation_id": correlation_id, "to_status": target}
        release_fk: int | None = None
        from_state: str | None = None
        denial: PolicyDenied | None = None
        outcome: TransitionOutcome | None = None
        try:
            with self._session_factory() as session, session.begin():
                release = session.scalars(
                    select(ReleaseRequest).where(ReleaseRequest.release_id == release_id).with_for_update()
                ).one_or_none()
                if release is None:
                    raise ReleaseNotFoundError(release_id)
                release_fk, from_state = release.id, release.status
                snapshot = load_release_snapshot(
                    session, release, self._rules, self._clock(), self._facts(session, release)
                )
                try:
                    can_transition(from_state, target, snapshot, policy=self._policy)
                except PolicyDenied as exc:
                    denial = exc
                    raise _Rollback from None
                release.status = target
                release.version += 1
                session.add(
                    ReleaseTransition(release_fk=release_fk, from_status=from_state, reason=reason, **audit)
                )
                session.flush()
                outcome = TransitionOutcome(release_id, from_state, target, release.version)
        except _Rollback:
            pass
        except ReleaseNotFoundError:
            raise
        except Exception as exc:
            if release_fk is not None:
                try:
                    self._audit_denial(release_fk, from_state, TRANSITION_ERROR, (type(exc).__name__,), reason, audit)
                except Exception as audit_exc:
                    exc.add_note(f"error audit event could not be written: {type(audit_exc).__name__}")
            raise

        if denial is not None and release_fk is not None:
            self._audit_denial(release_fk, from_state, denial.code, denial.failed_checks, reason, audit)
            raise denial
        if outcome is None:
            raise RuntimeError("transition finished without an outcome")
        return outcome

    def _audit_denial(
        self,
        release_fk: int,
        from_state: str | None,
        code: str,
        failed_checks: tuple[str, ...],
        reason: str | None,
        audit: dict[str, str | None],
    ) -> None:
        with self._session_factory() as session, session.begin():
            session.add(
                ReleaseTransition(
                    release_fk=release_fk,
                    from_status=from_state,
                    reason=denial_reason(code, failed_checks, reason),
                    **audit,
                )
            )
