"""Release state machine (Slice 3; section 18.2): allow-list from policies/state-transitions.yaml plus gates.

``can_transition`` returns ``Allowed`` or raises ``PolicyDenied``; it never mutates anything. Denials carry the HTTP
status from the policy (409). Unknown states, exits from terminal states, edges not in the allow-list, failed gates and
errors raised while evaluating a gate are all denials (fail closed, NFR-08).
Requirements: NFR-01, NFR-02, NFR-08; AC-RM-04.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from types import MappingProxyType
from typing import Any

import yaml

from release_api.domain.gates import GATES, Gate
from release_api.domain.snapshot import ReleaseSnapshot

DEFAULT_POLICY_PATH = Path(__file__).resolve().parents[5] / "policies" / "state-transitions.yaml"

UNKNOWN_STATE = "UNKNOWN_STATE"
TERMINAL_STATE = "TERMINAL_STATE"
ILLEGAL_TRANSITION = "ILLEGAL_TRANSITION"
GATE_FAILED = "GATE_FAILED"
GATE_ERROR = "GATE_ERROR"

DENIED_HTTP_STATUS = 409

# Every path from the initial state to these targets must pass through each listed state, so no policy edge can skip an
# approval, scheduling, readiness or deployment gate (Slice 3 review finding #5).
MANDATORY_WAYPOINTS: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "DEPLOYING": ("CHANGE_CREATION_PENDING", "SCHEDULED", "READY_FOR_RELEASE"),
        "COMPLETED": ("CHANGE_CREATION_PENDING", "SCHEDULED", "READY_FOR_RELEASE", "DEPLOYING"),
    }
)


class PolicyError(ValueError):
    """The state-transition policy file is missing or malformed."""


class PolicyDenied(Exception):
    """A requested transition is not permitted. Maps to HTTP 409 and an audit event."""

    def __init__(
        self,
        code: str,
        failed_checks: tuple[str, ...] = (),
        *,
        current: str,
        target: str,
        http_status: int = DENIED_HTTP_STATUS,
    ) -> None:
        self.code = code
        self.failed_checks = tuple(failed_checks)
        self.current = current
        self.target = target
        self.http_status = http_status
        detail = f": {', '.join(self.failed_checks)}" if self.failed_checks else ""
        super().__init__(f"{code} {current!r} -> {target!r}{detail}")


@dataclass(frozen=True)
class Allowed:
    from_state: str
    to_state: str


@dataclass(frozen=True)
class TransitionPolicy:
    initial_state: str
    states: frozenset[str]
    terminal_states: frozenset[str]
    transitions: Mapping[str, frozenset[str]]
    gates: Mapping[str, tuple[str, ...]]
    denied_http_status: int


def _state(value: Any, what: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise PolicyError(f"{what} must be a non-empty state name")
    return value


def _state_list(value: Any, what: str) -> list[str]:
    if not isinstance(value, list):
        raise PolicyError(f"{what} must be a list")
    states = [_state(v, what) for v in value]
    if len(set(states)) != len(states):
        raise PolicyError(f"{what} contains duplicates")
    return states


def _reachable(transitions: Mapping[str, frozenset[str]], start: str, removed: str) -> set[str]:
    seen = {start}
    stack = [start]
    while stack:
        for nxt in transitions.get(stack.pop(), frozenset()):
            if nxt != removed and nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return seen


def _check_waypoints(initial: str, transitions: Mapping[str, frozenset[str]]) -> None:
    for target, waypoints in MANDATORY_WAYPOINTS.items():
        for waypoint in waypoints:
            if target in _reachable(transitions, initial, removed=waypoint):
                raise PolicyError(f"policy lets {target} bypass {waypoint}")


def parse_transition_policy(data: Any) -> TransitionPolicy:
    if not isinstance(data, dict):
        raise PolicyError("policy must be a mapping")

    initial = _state(data.get("initial_state"), "initial_state")
    terminal = frozenset(_state_list(data.get("terminal_states"), "terminal_states"))

    raw_transitions = data.get("transitions")
    if not isinstance(raw_transitions, dict) or not raw_transitions:
        raise PolicyError("transitions must be a non-empty mapping")
    transitions = {
        _state(source, "transition source"): frozenset(_state_list(targets, f"transitions[{source}]"))
        for source, targets in raw_transitions.items()
    }
    exits_from_terminal = sorted(terminal & set(transitions))
    if exits_from_terminal:
        raise PolicyError(f"terminal states must have no outgoing transitions: {exits_from_terminal}")

    states = frozenset({initial, *terminal, *transitions, *(t for ts in transitions.values() for t in ts)})
    _check_waypoints(initial, transitions)

    raw_gates = data.get("gates")
    if not isinstance(raw_gates, dict):
        raise PolicyError("gates must be a mapping")
    unknown_gates = sorted(set(raw_gates) - states)
    if unknown_gates:
        raise PolicyError(f"gates reference unknown states: {unknown_gates}")
    if set(raw_gates) != set(GATES):
        raise PolicyError(
            "policy gates and implemented gates differ: "
            f"unimplemented={sorted(set(raw_gates) - set(GATES))}, unlisted={sorted(set(GATES) - set(raw_gates))}"
        )
    gates = {state: tuple(str(check) for check in checks or ()) for state, checks in raw_gates.items()}

    on_denied = data.get("on_denied")
    if not isinstance(on_denied, dict):
        raise PolicyError("on_denied must be a mapping")
    if on_denied.get("http_status") != DENIED_HTTP_STATUS or on_denied.get("write_audit_event") is not True:
        raise PolicyError("on_denied must be http_status 409 with write_audit_event true")

    return TransitionPolicy(
        initial_state=initial,
        states=states,
        terminal_states=terminal,
        transitions=MappingProxyType(transitions),
        gates=MappingProxyType(gates),
        denied_http_status=DENIED_HTTP_STATUS,
    )


def load_transition_policy(path: Path = DEFAULT_POLICY_PATH) -> TransitionPolicy:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise PolicyError(f"cannot read state-transition policy {path.name}: {type(exc).__name__}") from None
    return parse_transition_policy(data)


@cache
def default_transition_policy() -> TransitionPolicy:
    return load_transition_policy(DEFAULT_POLICY_PATH)


def can_transition(
    current: str,
    target: str,
    release_snapshot: ReleaseSnapshot,
    *,
    policy: TransitionPolicy | None = None,
    gates: Mapping[str, Gate] | None = None,
) -> Allowed:
    policy = policy or default_transition_policy()
    gates = GATES if gates is None else gates

    def deny(code: str, failed_checks: tuple[str, ...] = ()) -> PolicyDenied:
        return PolicyDenied(code, failed_checks, current=current, target=target, http_status=policy.denied_http_status)

    if current not in policy.states or target not in policy.states:
        raise deny(UNKNOWN_STATE)
    if current in policy.terminal_states:
        raise deny(TERMINAL_STATE)
    if target not in policy.transitions.get(current, frozenset()):
        raise deny(ILLEGAL_TRANSITION)

    gate = gates.get(target)
    if gate is not None:
        try:
            failed = tuple(gate(release_snapshot))
        except Exception:
            raise deny(GATE_ERROR, (target,)) from None
        if failed:
            raise deny(GATE_FAILED, failed)
    return Allowed(from_state=current, to_state=target)
