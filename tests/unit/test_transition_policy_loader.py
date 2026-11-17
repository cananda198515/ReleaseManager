"""Policy and product-rule loaders fail closed on malformed configuration (Slice 3; NFR-01, NFR-02, NFR-08)."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pytest
import yaml

from release_api.domain.product_rules import ProductRulesError, load_product_rules
from release_api.domain.snapshot import ReleaseSnapshot
from release_api.domain.state_machine import (
    DEFAULT_POLICY_PATH,
    GATE_ERROR,
    GATE_FAILED,
    PolicyDenied,
    PolicyError,
    can_transition,
    default_transition_policy,
    load_transition_policy,
)
from release_api.settings import Settings
from tests._repo import REPO_ROOT, load_yaml
from tests.policy._snapshots import ready_snapshot

GOOD_POLICY: dict[str, Any] = load_yaml("policies/state-transitions.yaml")
GOOD_PRODUCT: dict[str, Any] = load_yaml("config/products/wileyplus.yaml")


def _write(tmp_path: Path, data: Any, name: str = "policy.yaml") -> Path:
    path = tmp_path / name
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def _policy(**changes: Any) -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(yaml.safe_dump(GOOD_POLICY))
    data.update(changes)
    return data


def test_default_policy_path_is_repository_policy() -> None:
    assert DEFAULT_POLICY_PATH.resolve() == (REPO_ROOT / "policies" / "state-transitions.yaml").resolve()
    assert default_transition_policy() is default_transition_policy()


def test_loads_repository_policy(tmp_path: Path) -> None:
    policy = load_transition_policy(_write(tmp_path, GOOD_POLICY))
    assert policy.transitions["RECEIVED"] == frozenset({"PENDING_INFORMATION", "INFO_COMPLETE", "CANCELLED", "ERROR"})


@pytest.mark.parametrize(
    "data",
    [
        None,
        [],
        _policy(initial_state=None),
        _policy(initial_state=""),
        _policy(terminal_states="COMPLETED"),
        _policy(transitions=[]),
        _policy(transitions={"RECEIVED": "INFO_COMPLETE"}),
        _policy(transitions={**GOOD_POLICY["transitions"], "COMPLETED": ["RECEIVED"]}),
        _policy(transitions={**GOOD_POLICY["transitions"], "RECEIVED": ["INFO_COMPLETE", "INFO_COMPLETE"]}),
        _policy(transitions={**GOOD_POLICY["transitions"], "RECEIVED": [""]}),
        _policy(gates={**GOOD_POLICY["gates"], "NOWHERE": ["x"]}),
        _policy(gates={**GOOD_POLICY["gates"], "CANCELLED": ["Cancellation approved"]}),
        _policy(gates={k: v for k, v in GOOD_POLICY["gates"].items() if k != "DEPLOYING"}),
        _policy(on_denied={"http_status": 400, "write_audit_event": True}),
        _policy(on_denied={"http_status": 409, "write_audit_event": False}),
        _policy(on_denied=None),
    ],
    ids=[
        "empty", "list", "no-initial", "blank-initial", "terminal-not-list", "transitions-not-map", "targets-not-list",
        "terminal-with-exit", "duplicate-target", "blank-target", "gate-unknown-state", "gate-without-implementation",
        "implemented-gate-missing", "denied-not-409", "denied-not-audited", "no-on-denied",
    ],
)
def test_malformed_policy_is_rejected(tmp_path: Path, data: Any) -> None:
    with pytest.raises(PolicyError):
        load_transition_policy(_write(tmp_path, data))


def test_missing_policy_file_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(PolicyError):
        load_transition_policy(tmp_path / "absent.yaml")


def test_policy_error_does_not_echo_file_contents(tmp_path: Path) -> None:
    path = tmp_path / "policy.yaml"
    path.write_text("transitions: [unclosed\nsecret-looking-value", encoding="utf-8")
    with pytest.raises(PolicyError) as error:
        load_transition_policy(path)
    assert "secret-looking-value" not in str(error.value)


def test_gate_exception_fails_closed() -> None:
    """NFR-08: an error while evaluating a gate denies the transition; it never advances state."""

    def broken(_: ReleaseSnapshot) -> list[str]:
        raise RuntimeError("boom")

    gates: Mapping[str, Callable[[ReleaseSnapshot], list[str]]] = {"INFO_COMPLETE": broken}
    with pytest.raises(PolicyDenied) as denied:
        can_transition("RECEIVED", "INFO_COMPLETE", ready_snapshot(), gates=gates)
    assert (denied.value.code, denied.value.failed_checks) == (GATE_ERROR, ("INFO_COMPLETE",))


def test_policy_denied_carries_structured_details() -> None:
    with pytest.raises(PolicyDenied) as denied:
        can_transition("SCHEDULED", "READY_FOR_RELEASE", ready_snapshot(rollback_plan=None))
    error = denied.value
    assert (error.code, error.failed_checks, error.http_status) == (GATE_FAILED, ("ROLLBACK_PLAN_MISSING",), 409)
    assert "ROLLBACK_PLAN_MISSING" in str(error)


# --- product rules ---------------------------------------------------------------------------------------------------


def test_loads_wileyplus_rules() -> None:
    rules = load_product_rules(REPO_ROOT / "config" / "products" / "wileyplus.yaml")
    assert rules.required_fields == ("releaseName", "applicationKey", "components", "expectedStart", "impact",
                                     "downtimeType")
    assert rules.required_approval_types == frozenset({"TECHNICAL", "BUSINESS", "CHANGE"})
    assert rules.completion_evidence_required == (
        "deployment_result", "smoke_test", "health_check", "monitoring_observation"
    )


def test_disabled_approvals_are_not_required(tmp_path: Path) -> None:
    data = {**GOOD_PRODUCT, "approvals": {"technical": True, "business": False, "changeManager": True}}
    assert load_product_rules(_write(tmp_path, data)).required_approval_types == frozenset({"TECHNICAL", "CHANGE"})


@pytest.mark.parametrize(
    "changes",
    [
        {"requiredFields": ["releaseName", "favouriteColour"]},
        {"requiredFields": "releaseName"},
        {"approvals": {"technical": True, "sre": True}},
        {"approvals": {"technical": "yes"}},
        {"evidence": {"completionRequired": []}},
        {"evidence": {}},
        {"evidence": {"completionRequired": ["smoke_test", ""]}},
    ],
    ids=["unknown-field", "fields-not-list", "unmapped-approval", "approval-not-bool", "no-evidence",
         "evidence-missing", "blank-evidence"],
)
def test_malformed_product_rules_are_rejected(tmp_path: Path, changes: dict[str, Any]) -> None:
    with pytest.raises(ProductRulesError):
        load_product_rules(_write(tmp_path, {**GOOD_PRODUCT, **changes}))


# --- settings (decision D3) ------------------------------------------------------------------------------------------


def test_policy_path_setting_defaults_to_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MYSQL_PASSWORD", "unit-test-placeholder")
    monkeypatch.delenv("STATE_TRANSITIONS_POLICY_PATH", raising=False)
    assert Settings().state_transitions_policy_path is None


def test_policy_path_setting_reads_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("MYSQL_PASSWORD", "unit-test-placeholder")
    monkeypatch.setenv("STATE_TRANSITIONS_POLICY_PATH", str(tmp_path / "p.yaml"))
    assert Settings().state_transitions_policy_path == tmp_path / "p.yaml"
