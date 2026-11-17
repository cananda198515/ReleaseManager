"""Product rules consumed by the gates (config/products/<product>.yaml, section 9.2; policies/approvals.yaml).

Malformed product configuration fails closed with ProductRulesError. Requirements: BR-06, BR-09, BR-12, BR-15, NFR-09.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

# Product config approval keys -> release_approval.approval_type (policies/approvals.yaml product_config_mapping).
APPROVAL_CONFIG_MAPPING: dict[str, str] = {"technical": "TECHNICAL", "business": "BUSINESS", "changeManager": "CHANGE"}

# requiredFields names (product config) that the INFO_COMPLETE gate can evaluate.
KNOWN_REQUIRED_FIELDS = frozenset(
    {
        "releaseName",
        "applicationKey",
        "components",
        "expectedStart",
        "expectedEnd",
        "impact",
        "downtimeType",
        "downtimeDetails",
        "implementationPlan",
        "validationPlan",
        "rollbackPlan",
    }
)


class ProductRulesError(ValueError):
    """Product configuration is missing or malformed."""


@dataclass(frozen=True)
class ProductRules:
    required_fields: tuple[str, ...]
    required_approval_types: frozenset[str]
    completion_evidence_required: tuple[str, ...]


def _string_list(value: Any, name: str, *, allow_empty: bool) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
        raise ProductRulesError(f"{name} must be a list of non-empty strings")
    if not value and not allow_empty:
        raise ProductRulesError(f"{name} must not be empty")
    return tuple(value)


def parse_product_rules(data: Any) -> ProductRules:
    if not isinstance(data, dict):
        raise ProductRulesError("product configuration must be a mapping")

    required = _string_list(data.get("requiredFields"), "requiredFields", allow_empty=True)
    unknown = sorted(set(required) - KNOWN_REQUIRED_FIELDS)
    if unknown:
        raise ProductRulesError(f"requiredFields has unsupported names: {unknown}")

    approvals = data.get("approvals")
    if not isinstance(approvals, dict):
        raise ProductRulesError("approvals must be a mapping")
    unmapped = sorted(set(approvals) - set(APPROVAL_CONFIG_MAPPING))
    if unmapped:
        raise ProductRulesError(f"approvals has unmapped keys: {unmapped}")
    # An omitted key must not silently disable an approval (Slice 3 review finding #4).
    omitted = sorted(set(APPROVAL_CONFIG_MAPPING) - set(approvals))
    if omitted:
        raise ProductRulesError(f"approvals must state every key explicitly; missing: {omitted}")
    if not all(isinstance(v, bool) for v in approvals.values()):
        raise ProductRulesError("approvals values must be booleans")

    evidence = data.get("evidence")
    if not isinstance(evidence, dict):
        raise ProductRulesError("evidence must be a mapping")
    completion = _string_list(evidence.get("completionRequired"), "evidence.completionRequired", allow_empty=False)

    return ProductRules(
        required_fields=required,
        required_approval_types=frozenset(APPROVAL_CONFIG_MAPPING[k] for k, enabled in approvals.items() if enabled),
        completion_evidence_required=completion,
    )


def load_product_rules(path: Path) -> ProductRules:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ProductRulesError(f"cannot read product configuration {path.name}: {type(exc).__name__}") from None
    return parse_product_rules(data)
