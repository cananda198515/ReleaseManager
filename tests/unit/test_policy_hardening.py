"""Configuration cannot weaken approval gates (Slice 3 review, High findings #4 and #5).

#4: product configuration must state every approval key explicitly; an omitted key is no longer "not required" (P3).
#5: a state-transition policy whose edges let a release reach DEPLOYING or COMPLETED without passing through every
approval/readiness gate is rejected at load time, so STATE_TRANSITIONS_POLICY_PATH cannot weaken the lifecycle (P8).
Requirements: BR-09, BR-10, NFR-01, NFR-02; AC-RM-04, AC-RM-06, AC-RM-07.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from release_api.domain.product_rules import ProductRulesError, parse_product_rules
from release_api.domain.state_machine import PolicyError, load_transition_policy
from tests._repo import load_yaml

GOOD_PRODUCT: dict[str, Any] = load_yaml("config/products/wileyplus.yaml")
GOOD_POLICY: dict[str, Any] = load_yaml("policies/state-transitions.yaml")


@pytest.mark.parametrize(
    "approvals",
    [{}, {"technical": True}, {"technical": True, "business": True}, {"business": True, "changeManager": True}],
    ids=str,
)
def test_product_config_must_state_every_approval_key(approvals: dict[str, bool]) -> None:
    with pytest.raises(ProductRulesError):
        parse_product_rules({**GOOD_PRODUCT, "approvals": approvals})


def test_explicitly_disabled_approval_is_still_allowed() -> None:
    rules = parse_product_rules({**GOOD_PRODUCT, "approvals": {"technical": True, "business": False,
                                                               "changeManager": True}})
    assert rules.required_approval_types == frozenset({"TECHNICAL", "CHANGE"})


@pytest.mark.parametrize(
    ("source", "target"),
    [
        ("INFO_COMPLETE", "SCHEDULED"),  # skips TECHNICAL/BUSINESS (CHANGE_CREATION_PENDING)
        ("VALIDATION_PENDING", "COMPLETED"),  # skips every approval gate
        ("RECEIVED", "DEPLOYING"),
        ("CHANGE_APPROVAL_PENDING", "READY_FOR_RELEASE"),  # skips SCHEDULED
        ("SCHEDULED", "DEPLOYING"),  # skips READY_FOR_RELEASE
        ("READY_FOR_RELEASE", "VALIDATING"),  # COMPLETED without DEPLOYING
        ("OWNER_REVIEW", "CHANGE_APPROVAL_PENDING"),  # skips CHANGE_CREATION_PENDING
    ],
    ids=lambda v: v,
)
def test_policy_with_gate_skipping_edge_is_rejected(tmp_path: Path, source: str, target: str) -> None:
    data = yaml.safe_load(yaml.safe_dump(GOOD_POLICY))
    data["transitions"][source].append(target)
    path = tmp_path / "policy.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(PolicyError, match="bypass"):
        load_transition_policy(path)


def test_policy_with_harmless_extra_edge_still_loads(tmp_path: Path) -> None:
    data = yaml.safe_load(yaml.safe_dump(GOOD_POLICY))
    data["transitions"]["OWNER_REVIEW"].append("ERROR")
    path = tmp_path / "policy.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    assert "ERROR" in load_transition_policy(path).transitions["OWNER_REVIEW"]
