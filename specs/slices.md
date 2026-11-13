# Implementation Slices

Source: Implementation Guide v2.0, sections 11, 13, 16 and 18. One slice per branch; tests first (red -> green).
Every slice must keep `pytest -q`, `ruff check .`, `mypy .` green and must not regress earlier gates (NFR-10).
"Files" are planned paths from the guide's layout (section 10); nothing beyond them is implied.

## Slice 1 — Scaffold

- **Goal:** Monorepo skeleton per section 10 / prompt 18.1: FastAPI `services/release-api`, `services/release-mcp`,
  SQLAlchemy 2.x, Alembic, MySQL; config/policies/agents/skills/hooks/tests directories; Dockerfiles, docker-compose for
  local MySQL only, pytest, ruff, mypy and GitHub Actions. No arbitrary SQL tools; no secrets in files.
  Added by the slice owner: Release API settings via pydantic-settings, loaded from environment variables only, with
  `MYSQL_PASSWORD` required (no default) and never logged; liveness endpoint `GET /health` -> 200 `{"status":"ok"}`
  (section 5.1; moved from Slice 5); minimal non-secret environment overlays `config/environments/{dev,test,prod}.yaml`
  (moved from Slice 12); pre-commit hooks for ruff, mypy and gitleaks. No business logic and no database tables.
- **Files:** `README.md`, `services/release-api/`, `services/release-mcp/`, `db/`, `tests/{unit,integration,policy,prompt-injection,golden,architecture}/`,
  `.github/workflows/validate.yml`, `build.yml`, `security.yml`, `scripts/bootstrap.ps1`, `bootstrap.sh`, `validate.ps1`,
  Dockerfiles, docker-compose (local MySQL), `.env.example`, `.pre-commit-config.yaml`,
  `config/environments/{dev,test,prod}.yaml`.
- **Tests:** architecture tests (agents/MCP have no MySQL dependency; no forbidden tools present; no secrets; environment
  overlays non-secret); settings tests (env-only, password required and masked, never logged); smoke test `GET /health`;
  `ruff`, `mypy`, `pytest` run in CI on every PR.
- **Traceability:** NFR-03, NFR-06, NFR-09.

## Slice 2 — Schema

- **Goal:** Alembic migrations for the section 4.1 schema (InnoDB, utf8mb4, UTC); seed only application configuration in
  dev/test; separate migration and runtime identities.
- **Files:** `db/migrations/`, `db/seed/`, `services/release-api/` ORM models.
- **Tests:** database integration — migrations up/down where supported, constraints, rollback on failed transaction,
  concurrent duplicate create (section 13).
- **Traceability:** BR-03, BR-04, BR-05, NFR-01, NFR-04, NFR-06; AC-RM-03.

## Slice 3 — State machine

- **Goal:** Pure domain state-machine service loading `policies/state-transitions.yaml`; validate allowed edge and named
  prerequisites; persist state change and `release_transition` audit row in the same transaction; illegal edge -> 409 +
  audit event. No agent/LLM dependencies in the domain layer (prompt 18.2).
- **Files:** `services/release-api/` domain state-machine module, `policies/state-transitions.yaml`.
- **Tests:** table-driven tests for every allowed edge and every forbidden edge (100% denial); audit row written in same
  transaction; failures never advance state.
- **Traceability:** NFR-01, NFR-02, NFR-08; AC-RM-04.

## Slice 4 — Risk and readiness

- **Goal:** Deterministic risk rules (product thresholds) and readiness/gate checks from section 8.2.
- **Files:** `services/release-api/` risk and readiness modules, `config/products/wileyplus.yaml`, `policies/approvals.yaml`.
- **Tests:** unit tests for risk thresholds and each gate (INFO_COMPLETE, OWNER_REVIEW, CHANGE_CREATION_PENDING,
  SCHEDULED, READY_FOR_RELEASE, DEPLOYING, COMPLETED); golden cases "READY_FOR_RELEASE with missing rollback plan ->
  denial" and "no smoke test -> cannot reach COMPLETED".
- **Traceability:** BR-06, BR-09, BR-10, BR-12, NFR-01, NFR-02; AC-RM-06, AC-RM-07, AC-RM-08.

## Slice 5 — Release API

- **Goal:** REST endpoints in section 5.1 with typed models, authorization, optimistic locking, idempotency, server-side
  validation, structured JSON logging with redaction (`/health` was delivered in Slice 1).
- **Files:** `services/release-api/` routers, schemas, services.
- **Tests:** API unit tests — state transitions, validation, idempotency, optimistic locking, risk and readiness rules;
  duplicate create returns one release; logs contain release_id/correlation_id/actor/action and no secrets.
- **Traceability:** BR-03, BR-04, BR-05, BR-08, BR-12, BR-13, NFR-04, NFR-05, NFR-07, NFR-08; AC-RM-03, AC-RM-04, AC-RM-09.

## Slice 6 — Release MCP server

- **Goal:** Expose only the 10 tools in `specs/tool-contracts.md`; each mutation calls the Release API, requires
  correlation/idempotency headers, validates JSON Schema, propagates identity, maps policy-denied to a typed MCP error
  (prompt 18.3).
- **Files:** `services/release-mcp/`, `policies/tool-allowlist.yaml`, `.mcp.json`.
- **Tests:** MCP contract tests — every tool rejects malformed IDs/enums; no non-allowlisted operation; no execute_sql,
  generic HTTP, shell, file-write or secret-reading tool.
- **Traceability:** NFR-03, NFR-04, NFR-07; AC-RM-03, AC-RM-04.

## Slice 7 — Agents, skills and hooks

- **Goal:** Agent instructions A0–A8 (section 6), skills (section 7, generic template 7.1) and hooks (before-tool-call
  authorize, after-tool-call validate output schema, before-final-response grounding check, on-error escalate after retry
  limit — section 11 step 15).
- **Files:** `agents/*.md`, `skills/*/`, `hooks/before-tool-call/`, `hooks/after-tool-call/`,
  `hooks/before-final-response/`, `hooks/on-error/`.
- **Tests:** prompt/config lint; hook unit tests; skills use only allowed tools; no product-specific values in core prompts.
- **Traceability:** BR-02, BR-07, BR-13, BR-15, NFR-07, NFR-09; AC-RM-02, AC-RM-05, AC-RM-10.

## Slice 8 — Evals

- **Goal:** Golden intake set (>= 20 representative requests), missing-data cases, duplicates, permission failures,
  malicious content, retries, rejection and rollback; adversarial cases of section 13.1; approval classification (12.2).
- **Files:** `tests/golden/`, `tests/prompt-injection/`, `tests/policy/`.
- **Tests:** mandatory-field extraction >= 95% on labeled fields; prompt-injection/tool-abuse 100% prevented for
  consequential bypass; ambiguous approvals never APPROVED (100%).
- **Traceability:** BR-02, NFR-02, NFR-07, NFR-10; AC-RM-02, AC-RM-05.

## Slice 9 — Workflows

- **Goal:** Copilot Studio workflows per sections 11 (steps 8–14) and 12.1: email intake and missing-information loop,
  readiness/risk flow, release-note flow (Confluence draft), parallel technical/business approvals, change flow (Jira,
  Change Manager approval), scheduler (Teams/calendar), release-day evidence path, reminders/timeouts, retry policy.
- **Files:** not defined by the guide's layout (see open questions).
- **Tests:** idempotency (repeated Jira/Confluence/meeting calls create one artifact); duplicate internetMessageId -> one
  release; failure recovery (429/5xx retry, 401/403 no retry, circuit breaker escalates); E2E in non-production systems.
- **Traceability:** BR-01, BR-04, BR-05, BR-07, BR-08, BR-09, BR-10, BR-11, BR-12, BR-14, NFR-04, NFR-08; AC-RM-01,
  AC-RM-03, AC-RM-06, AC-RM-07, AC-RM-08.

## Slice 10 — Security review

- **Goal:** Security review per prompt 18.4 (tool permissions, injection paths, SQL injection, authorization,
  tenant/product isolation, secret handling, logging, idempotency, SSRF through URLs, replay, approval spoofing) and the
  section 14 checklist in `specs/security.md`.
- **Files:** `.github/workflows/security.yml`, `tests/prompt-injection/`, `tests/architecture/`.
- **Tests:** one deterministic test per finding; a finding is not fixed until its test passes; log-redaction tests.
- **Traceability:** NFR-03, NFR-06, NFR-07; AC-RM-05, AC-RM-09.

## Slice 11 — Evaluation

- **Goal:** Evaluator per prompt 18.5: assess every BR-, NFR- and AC-RM ID, citing an exact test or code artifact;
  run deterministic tests first; output PASS/FAIL/BLOCKED with evidence and remediation; enforce ratchets.
- **Files:** evaluation report and ratchet baseline (location not defined by the guide).
- **Tests:** ratchet — any regression of previously passing security, approval, state-transition or idempotency tests
  fails the build.
- **Traceability:** NFR-10; BR-01..BR-15, NFR-01..NFR-10, AC-RM-01..AC-RM-10.

## Slice 12 — Packaging

- **Goal:** Portable plugin package (section 10.1): manifest, MCP config, config schema (validating the environment
  configs created in Slice 1); CI builds API/MCP images, runs migrations against disposable DB, publishes plugin
  artifact (section 11 step 17).
- **Files:** `plugin.json`, `.mcp.json`, `config/release-harness.schema.json`,
  `.github/workflows/package.yml`, `scripts/package.ps1`.
- **Tests:** config validates against schema; a second product installs via configuration only, without core agent changes.
- **Traceability:** BR-15, NFR-09; AC-RM-10.

## Open questions

1. **Exits from exception states.** Section 8.1 defines no outgoing transitions for MANUAL_REVIEW, ERROR (or any
   terminal state). How does a release resume after manual review or retry from ERROR?
2. **Missing exception edges.** NFR-08 requires failures to route to retry or human review, but several states have no
   MANUAL_REVIEW edge and OWNER_REVIEW/BUSINESS_APPROVAL_PENDING have no ERROR edge; CHANGE_CREATION_PENDING and
   CHANGE_APPROVAL_PENDING cannot be CANCELLED. Is 8.1 (titled "example") the complete allow-list?
3. **RECEIVED -> INFO_COMPLETE** is allowed in 8.1 but not shown in the 4.2 chain. Confirm it is intended.
4. **Gates for other states.** No gates are defined for PENDING_INFORMATION, VALIDATION_PENDING,
   BUSINESS_APPROVAL_PENDING, CHANGE_APPROVAL_PENDING, VALIDATING, FAILED, ROLLED_BACK, REJECTED, CANCELLED.
5. **Audit of denied transitions / errors.** `release_transition.to_status` is NOT NULL and there is no generic audit or
   security-event table. Where are denied transitions (409 audit event), NFR-08 error events and
   `security_event=PROMPT_INJECTION_SUSPECTED` stored?
6. **Risk rules.** Only thresholds (6/11/16) are given. What are the risk factors and weights? Is LOW `< 6`? Where are
   risk factors stored (schema has only `risk_score`, `risk_level`)?
7. **Readiness checks.** Beyond the 8.2 gates, what checks does `/readiness` return, and what is "valid release window"
   and "no blocker"?
8. **Tool-to-endpoint mapping.** Which endpoints back `release_merge_intake`, `release_get_missing_fields` and
   `release_record_external_artifact`? Allowed values for `type` (Confluence/Jira/meeting?) are not specified.
9. **PATCH fields.** Which business fields are "permitted" for PATCH, and in which states?
10. **Idempotency header and scope.** Header name, key format (other than `outlook:<internetMessageId>`) and retention of
    `idempotency_record` are not specified.
11. **release_id generation.** Timezone for YYYYMMDD (assume UTC?), whether NNNN is a per-day sequence, and behaviour
    beyond 9999 per day.
12. **Authorization model.** Roles/scopes per caller (agents, workflows, humans) and how "authenticated identity" maps
    to `actor_type`/`actor_id` are not defined.
13. **Required approvals.** Product config covers technical/business/changeManager only; when are SRE and RELEASE_OWNER
    approvals required? How are multiple approvers per type and re-decisions handled given `uq_approval`?
14. **Implementation/validation/rollback plans.** Section 6.2 says mandatory before INFO_COMPLETE "if product policy
    marks them mandatory", but section 9.2 has no such setting; the READY_FOR_RELEASE gate always requires them.
15. **DEPLOYING authorization.** What is the "existing deployment mechanism/human policy" and how is the authorization
    recorded?
16. **Config layout.** The guide defines `config/default.yaml` contents only implicitly and uses
    `config/environments/*.yaml`; `config/products/` is a bootstrap addition. How do `application_config` (DB) and
    product YAML relate (e.g. approver emails, Jira project) and which wins?
17. **Skills list mismatch.** Section 7 lists 9 skills; section 10 layout lists 7 (omits `generate-communication` and
    `post-release-summary`). Which set is required?
18. **Workflow artifacts.** How are Copilot Studio workflows represented and tested in this repository (slice 9 files)?
19. **Data classification.** `policies/data-classification.yaml` is in the layout but its content and the list of
    "PII-sensitive values configured as restricted" (AC-RM-09) are undefined.
20. **Intake channels.** Teams/Jira/API intake are "optional" (BR-01); are they in scope for the first release?
21. **Reminders/timeouts.** Reminder cadence is configured, but timeout durations and where reminder counts are stored
    are not specified (BR-14).
22. **Evaluation location.** Where do eval datasets, thresholds, ratchet baselines and evaluator reports live
    (no `evals/` directory in the section 10 layout)?
23. **Toolchain versions.** Python version and tool configuration (ruff/mypy settings) are not specified.
24. **Slice 1 provisional decisions (approved with the Slice 1 plan; confirm or revise).** D1: target Python 3.12
    (`requires-python >=3.12`), ruff rules `E,F,W,I,B,S,UP`, mypy `strict`. D2: PyMySQL driver. D3: official `mcp`
    Python SDK + `httpx` for the MCP server. D4: root `pyproject.toml`, `.gitignore`, `.env.example` and
    `docker-compose.yml` added although absent from the section 10 layout. D5: `security.yml` runs only
    `tests/architecture` and `tests/prompt-injection` until Slice 10 (no pip-audit/gitleaks yet).
25. **Slice 1 owner decisions (13 Nov 2026).** `MYSQL_PASSWORD` is a required pydantic `SecretStr` in Release API
    settings (fail fast at startup; masked; `hide_input_in_errors`); `/health` and `config/environments/*.yaml` moved
    into Slice 1; environment overlays hold only `appEnv` plus `{env: NAME}` references; gitleaks is the pre-commit
    secret scanner (CI secret scanning still deferred to Slice 10).
26. **Local MySQL (13 Nov 2026).** Local development uses an installed MySQL **8.0.46**, not 8.4 LTS (section 1.1) or
    docker-compose. Is 8.0 acceptable for local work, given that CI and deployed environments should target 8.4? The
    runtime user `release_api@127.0.0.1` has `SELECT, INSERT, UPDATE` only (no `DELETE`, since release and audit records
    are never deleted). Slice 2 must define the migration identity and whether any runtime `DELETE` is needed.
