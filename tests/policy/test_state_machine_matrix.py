"""Full state-transition matrix generated from policies/state-transitions.yaml (Slice 3).

Every allowed edge passes when prerequisites are met; every other (state, target) pair, including self-transitions and
every exit from a terminal state, raises PolicyDenied (section 13: 100% denial).
Requirements: NFR-01, NFR-02, NFR-10; AC-RM-04.
"""

from __future__ import annotations

from itertools import product
from typing import Any

import pytest

from release_api.domain.state_machine import (
    ILLEGAL_TRANSITION,
    TERMINAL_STATE,
    UNKNOWN_STATE,
    Allowed,
    PolicyDenied,
    can_transition,
    default_transition_policy,
)
from tests._repo import load_yaml
from tests.policy._snapshots import ready_snapshot

POLICY: dict[str, Any] = load_yaml("policies/state-transitions.yaml")
TRANSITIONS: dict[str, list[str]] = POLICY["transitions"]
TERMINAL: list[str] = POLICY["terminal_states"]
STATES: list[str] = sorted(
    {POLICY["initial_state"], *TERMINAL, *TRANSITIONS, *(t for targets in TRANSITIONS.values() for t in targets)}
)
ALLOWED: list[tuple[str, str]] = [(source, target) for source, targets in TRANSITIONS.items() for target in targets]
FORBIDDEN: list[tuple[str, str]] = [pair for pair in product(STATES, STATES) if pair not in set(ALLOWED)]


def test_matrix_covers_every_pair() -> None:
    assert len(STATES) == 19  # 12 lifecycle states + 7 terminal/exception states (section 4.2)
    assert len(ALLOWED) + len(FORBIDDEN) == len(STATES) ** 2
    assert len(set(ALLOWED)) == len(ALLOWED), "duplicate edge in policies/state-transitions.yaml"


def test_loader_reads_the_same_allow_list() -> None:
    policy = default_transition_policy()
    assert policy.states == frozenset(STATES)
    assert policy.terminal_states == frozenset(TERMINAL)
    assert policy.initial_state == POLICY["initial_state"] == "RECEIVED"
    assert {(s, t) for s, targets in policy.transitions.items() for t in targets} == set(ALLOWED)
    assert policy.denied_http_status == 409


@pytest.mark.parametrize(("current", "target"), ALLOWED, ids=[f"{s}->{t}" for s, t in ALLOWED])
def test_allowed_edge_passes_when_prerequisites_met(current: str, target: str) -> None:
    result = can_transition(current, target, ready_snapshot())
    assert result == Allowed(from_state=current, to_state=target)


@pytest.mark.parametrize(("current", "target"), FORBIDDEN, ids=[f"{s}->{t}" for s, t in FORBIDDEN])
def test_forbidden_pair_is_denied(current: str, target: str) -> None:
    with pytest.raises(PolicyDenied) as denied:
        can_transition(current, target, ready_snapshot())
    expected = TERMINAL_STATE if current in TERMINAL else ILLEGAL_TRANSITION
    assert denied.value.code == expected
    assert denied.value.http_status == 409
    assert (denied.value.current, denied.value.target) == (current, target)


@pytest.mark.parametrize("terminal", TERMINAL)
def test_terminal_states_have_no_outgoing_edges(terminal: str) -> None:
    assert terminal not in TRANSITIONS
    for target in STATES:
        with pytest.raises(PolicyDenied) as denied:
            can_transition(terminal, target, ready_snapshot())
        assert denied.value.code == TERMINAL_STATE


def test_requested_terminal_set_is_terminal() -> None:
    assert {"COMPLETED", "REJECTED", "CANCELLED", "FAILED", "ROLLED_BACK"} <= set(TERMINAL)


@pytest.mark.parametrize(
    ("current", "target"),
    [("RECEIVED", "SHIPPED"), ("SHIPPED", "RECEIVED"), ("received", "INFO_COMPLETE"), ("RECEIVED", "info_complete"),
     ("", "INFO_COMPLETE"), ("RECEIVED", " INFO_COMPLETE")],
)
def test_unknown_states_are_denied(current: str, target: str) -> None:
    with pytest.raises(PolicyDenied) as denied:
        can_transition(current, target, ready_snapshot())
    assert denied.value.code == UNKNOWN_STATE


def test_decision_is_deterministic() -> None:
    snapshot = ready_snapshot()
    assert {can_transition("RECEIVED", "INFO_COMPLETE", snapshot) for _ in range(5)} == {
        Allowed(from_state="RECEIVED", to_state="INFO_COMPLETE")
    }
