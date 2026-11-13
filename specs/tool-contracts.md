# Tool Contracts

Source: Implementation Guide v2.0, sections 5.1, 5.2, 13 and 18.3.
Requirements: NFR-03, NFR-04, NFR-07; AC-RM-03, AC-RM-04, AC-RM-05.
Machine-readable allow-list: `policies/tool-allowlist.yaml`.

## 1. Release API REST endpoints (section 5.1)

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | /v1/releases | Create an idempotent draft release. |
| GET | /v1/releases/{releaseId} | Read complete release aggregate. |
| PATCH | /v1/releases/{releaseId} | Update permitted business fields with optimistic version. |
| POST | /v1/releases/{releaseId}/transition | Request server-validated transition. |
| POST | /v1/releases/{releaseId}/approvals | Create or record approval evidence. |
| POST | /v1/releases/{releaseId}/evidence | Append deployment/testing evidence. |
| POST | /v1/releases/{releaseId}/risk:calculate | Execute deterministic risk rules. |
| GET | /v1/releases/{releaseId}/readiness | Return deterministic readiness failures. |
| GET | /health | Liveness/readiness endpoint. |

API rules (sections 3.1, 11 step 4):

- Every write checks authorization, permitted state transition, prerequisites and idempotency.
- Typed models, optimistic locking (`release_request.version`), idempotency (`idempotency_record`), state-policy service,
  risk rules, readiness gates and audit transactions.
- An illegal transition returns HTTP 409 and writes an audit event (section 4.2).

## 2. MCP tools exposed to agents (section 5.2) — exactly these 10

| # | Tool | Signature |
|---|------|-----------|
| 1 | release_create_draft | `release_create_draft(input)` |
| 2 | release_get | `release_get(release_id)` |
| 3 | release_merge_intake | `release_merge_intake(release_id, extracted_fields, source_message_id)` |
| 4 | release_get_missing_fields | `release_get_missing_fields(release_id)` |
| 5 | release_calculate_risk | `release_calculate_risk(release_id)` |
| 6 | release_get_readiness | `release_get_readiness(release_id)` |
| 7 | release_request_transition | `release_request_transition(release_id, target_state, reason)` |
| 8 | release_record_approval | `release_record_approval(release_id, approval_type, approver, decision, evidence_ref)` |
| 9 | release_record_external_artifact | `release_record_external_artifact(release_id, type, external_id, url)` |
| 10 | release_append_evidence | `release_append_evidence(release_id, evidence_type, source, reference, sha256)` |

Tool-to-endpoint mapping explicitly implied by section 5.1: `release_create_draft` -> `POST /v1/releases`;
`release_get` -> `GET /v1/releases/{releaseId}`; `release_request_transition` -> `POST .../transition`;
`release_record_approval` -> `POST .../approvals`; `release_append_evidence` -> `POST .../evidence`;
`release_calculate_risk` -> `POST .../risk:calculate`; `release_get_readiness` -> `GET .../readiness`.
The mapping for `release_merge_intake`, `release_get_missing_fields` and `release_record_external_artifact` is not
specified (see open questions in `specs/slices.md`).

### MCP implementation rules (section 18.3)

- Expose only the approved Release MCP tools listed above.
- Each mutation must call the Release API, require correlation/idempotency headers, validate JSON Schema, propagate
  authenticated identity and map policy-denied to a typed MCP error.
- There must be no execute_sql, generic HTTP, shell, file write or secret-reading tool.
- Add contract tests.

### MCP contract test gate (section 13)

Every tool rejects malformed IDs/enums and cannot access non-allowlisted operation.

## 3. Forbidden tools

Never expose (section 5.2):

```
execute_sql(sql)
generic_http(url, method, body)
set_status_without_validation(...)
write_secret(...)
```

Also forbidden (section 18.3): any shell tool, any file-write tool, any secret-reading tool.
