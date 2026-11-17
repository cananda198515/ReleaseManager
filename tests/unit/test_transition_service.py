"""TransitionService input validation and denial audit format, without a database (Slice 3; NFR-01, NFR-08)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from release_api.domain.state_machine import GATE_FAILED, ILLEGAL_TRANSITION, PolicyDenied, default_transition_policy
from release_api.services.transitions import (
    DENIED_REASON_PREFIX,
    MAX_REASON_LENGTH,
    TransitionService,
    denial_reason,
)
from tests.policy._snapshots import AS_OF, WILEYPLUS_RULES


def _unused_session_factory() -> Any:
    raise AssertionError("invalid input must be rejected before any database access")


def _service() -> TransitionService:
    return TransitionService(
        session_factory=_unused_session_factory,
        policy=default_transition_policy(),
        rules=WILEYPLUS_RULES,
        clock=lambda: AS_OF,
    )


def _valid(**changes: Any) -> dict[str, Any]:
    params: dict[str, Any] = {
        "release_id": "REL-20261117-0001",
        "target": "CANCELLED",
        "actor_type": "HUMAN",
        "actor_id": "owner@example.com",
        "reason": "ok",
        "correlation_id": str(uuid.uuid4()),
    }
    params.update(changes)
    return params


@pytest.mark.parametrize(
    "changes",
    [
        {"release_id": "REL-1"},
        {"release_id": "rel-20261117-0001"},
        {"release_id": "REL-20261117-0001; DROP TABLE release_request"},
        {"actor_type": ""},
        {"actor_type": "X" * 31},
        {"actor_id": "a" * 321},
        {"correlation_id": "not-a-uuid"},
        {"correlation_id": ""},
        {"reason": "r" * (MAX_REASON_LENGTH + 1)},
        {"target": ""},
    ],
    ids=["short-id", "lowercase-id", "injection-id", "blank-actor", "long-actor", "long-actor-id", "bad-correlation",
         "blank-correlation", "long-reason", "blank-target"],
)
def test_invalid_input_rejected_before_database(changes: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        _service().request_transition(**_valid(**changes))


def test_denial_reason_for_illegal_edge() -> None:
    denied = PolicyDenied(ILLEGAL_TRANSITION, current="RECEIVED", target="COMPLETED")
    assert denial_reason(denied.code, denied.failed_checks, "please") == "DENIED:ILLEGAL_TRANSITION | please"


def test_denial_reason_for_gate_failure_lists_checks() -> None:
    denied = PolicyDenied(GATE_FAILED, ("ROLLBACK_PLAN_MISSING", "BLOCKERS_PRESENT"), current="SCHEDULED",
                          target="READY_FOR_RELEASE")
    assert denial_reason(denied.code, denied.failed_checks, None) == (
        "DENIED:GATE_FAILED:ROLLBACK_PLAN_MISSING,BLOCKERS_PRESENT"
    )


def test_denial_reason_fits_column_and_keeps_prefix() -> None:
    reason = denial_reason(GATE_FAILED, tuple(f"CHECK_{i}" for i in range(400)), "x" * MAX_REASON_LENGTH)
    assert len(reason) <= MAX_REASON_LENGTH
    assert reason.startswith(f"{DENIED_REASON_PREFIX}{GATE_FAILED}:CHECK_0")
