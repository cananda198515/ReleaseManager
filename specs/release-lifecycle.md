# Release Lifecycle

Source: Implementation Guide v2.0, sections 4.2, 8.1 and 8.2.
Requirements: NFR-01, NFR-02, NFR-08, BR-06, BR-09, BR-10, BR-12; AC-RM-04, AC-RM-06, AC-RM-07, AC-RM-08.
Machine-readable allow-list: `policies/state-transitions.yaml`.

## 1. States (section 4.2)

Happy path:

```
RECEIVED -> PENDING_INFORMATION -> INFO_COMPLETE -> VALIDATION_PENDING
VALIDATION_PENDING -> OWNER_REVIEW -> BUSINESS_APPROVAL_PENDING
BUSINESS_APPROVAL_PENDING -> CHANGE_CREATION_PENDING -> CHANGE_APPROVAL_PENDING
CHANGE_APPROVAL_PENDING -> SCHEDULED -> READY_FOR_RELEASE -> DEPLOYING -> VALIDATING -> COMPLETED
```

Initial state: `RECEIVED` (database default for `release_request.status`).

## 2. Terminal / exception states (section 4.2)

```
REJECTED | CANCELLED | FAILED | ROLLED_BACK | ERROR | MANUAL_REVIEW
```

`COMPLETED` is the successful end state. No outgoing transitions are defined for `COMPLETED` or for any
terminal/exception state in section 8.1 (see open questions in `specs/slices.md`).

## 3. Allowed transitions (section 8.1)

| From | Allowed targets |
|------|-----------------|
| RECEIVED | PENDING_INFORMATION, INFO_COMPLETE, CANCELLED, ERROR |
| PENDING_INFORMATION | INFO_COMPLETE, CANCELLED, MANUAL_REVIEW, ERROR |
| INFO_COMPLETE | VALIDATION_PENDING, CANCELLED, ERROR |
| VALIDATION_PENDING | OWNER_REVIEW, MANUAL_REVIEW, ERROR |
| OWNER_REVIEW | BUSINESS_APPROVAL_PENDING, REJECTED, CANCELLED |
| BUSINESS_APPROVAL_PENDING | CHANGE_CREATION_PENDING, REJECTED, CANCELLED |
| CHANGE_CREATION_PENDING | CHANGE_APPROVAL_PENDING, ERROR |
| CHANGE_APPROVAL_PENDING | SCHEDULED, REJECTED, ERROR |
| SCHEDULED | READY_FOR_RELEASE, CANCELLED, ERROR |
| READY_FOR_RELEASE | DEPLOYING, CANCELLED, ERROR |
| DEPLOYING | VALIDATING, FAILED, ROLLED_BACK, ERROR |
| VALIDATING | COMPLETED, FAILED, ROLLED_BACK, ERROR |

Rules:

- Implement the allow-list **in code, not in a prompt**.
- A transition request that is not present in the allow-list returns **HTTP 409** and writes an audit event.
- State changes happen only through `POST /v1/releases/{releaseId}/transition` (MCP: `release_request_transition`).
- Each transition validates the allowed edge **and** named prerequisites (gates), and persists the release state change
  and the `release_transition` audit row in the **same transaction** (section 18.2).
- Failures never silently advance state; they create an error/audit event and route to retry or human review (NFR-08).

## 4. Deterministic gates (section 8.2)

A gate is evaluated when entering the named target state.

| Gate (target state) | Required checks |
|---------------------|-----------------|
| INFO_COMPLETE | Mandatory fields complete; at least one component; target versions provided. |
| OWNER_REVIEW | Schema valid; risk calculable; readiness report produced. |
| CHANGE_CREATION_PENDING | All configured technical/business approvals APPROVED. |
| SCHEDULED | Change approval APPROVED; valid release window; attendee config present. |
| READY_FOR_RELEASE | Change still approved; no blocker; implementation/rollback/validation plans present. |
| DEPLOYING | Explicit production execution authorization from existing deployment mechanism/human policy. |
| COMPLETED | Deployment success evidence + post-deploy validation + required monitoring evidence valid. |

Related inputs:

- Mandatory fields per product: `requiredFields` in `config/products/<product>.yaml` (section 9.2). Intake also requires
  `downtimeDetails` when `downtimeType != NONE`, and `implementationPlan`, `validationPlan`, `rollbackPlan` before
  INFO_COMPLETE if product policy marks them mandatory (section 6.2).
- Configured approvals: `approvals` in product config and `policies/approvals.yaml`.
- Completion evidence set: `evidence.completionRequired` in product config.
- `features.allowAutonomousProductionDeployment: false` — production execution is never autonomous.

## 5. Golden gate cases (section 13.1, subset)

- Release attempts READY_FOR_RELEASE with missing rollback plan. Expected: policy denial.
- Pipeline starts but no smoke test is present. Expected: cannot reach COMPLETED.
- State machine suite: every illegal edge returns policy denial: 100% (section 13).
