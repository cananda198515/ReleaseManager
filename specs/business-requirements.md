# Business Requirements

Source: AI-Native Release Management Harness Implementation Guide v2.0, sections 2.3, 2.4 and 17 (copied verbatim).

## Functional requirements (section 2.3)

| ID | Requirement |
|----|-------------|
| BR-01 | Accept requests from a shared mailbox and optionally Teams/Jira/API. |
| BR-02 | Extract release name, product/application, components and versions, requested date/time, impact, downtime, implementation, validation and rollback information. |
| BR-03 | Generate immutable business identifier REL-YYYYMMDD-NNNN and correlation ID. |
| BR-04 | Persist partial requests and ask only for missing mandatory fields. |
| BR-05 | Maintain all replies under the release by subject tag/correlation and external message IDs. |
| BR-06 | Validate readiness and compute risk using deterministic policy rules. |
| BR-07 | Generate traceable release notes and create a Confluence draft. |
| BR-08 | Collect technical/business approvals and preserve approver evidence. |
| BR-09 | Generate and create a Jira/JSM change only after configured approval gates. |
| BR-10 | Collect Change Manager approval before scheduling/production readiness. |
| BR-11 | Create release meeting with requester, SRE, approvers and configured delivery teams. |
| BR-12 | Collect deployment/test evidence and support completed, failed and rolled-back outcomes. |
| BR-13 | Expose release status and evidence to an operator/Coordinator agent. |
| BR-14 | Provide reminders, timeouts, manual-review routing and safe retry behavior. |
| BR-15 | Support multiple products through configuration without changing core agent prompts. |

## Non-functional requirements (section 2.4)

| ID | Requirement |
|----|-------------|
| NFR-01 | All consequential state transitions are deterministic and auditable. |
| NFR-02 | Illegal state transitions and approval bypasses must be prevented 100% in gate tests. |
| NFR-03 | Database credentials, tokens and secrets never appear in prompts or logs. |
| NFR-04 | All write calls are idempotent. |
| NFR-05 | Structured JSON logging uses release_id, correlation_id, actor and action. |
| NFR-06 | Read/write database access uses least-privilege service identities. |
| NFR-07 | Agent-provided strings are treated as untrusted input and validated server-side. |
| NFR-08 | Failures never silently advance state; they create an error/audit event and route to retry or human review. |
| NFR-09 | Configuration is externalized so the plugin can be reused across products/environments. |
| NFR-10 | Evaluation is regression-ratcheted: a release cannot reduce previously passing security/control gates. |

## Acceptance criteria for go-live (section 17)

| ID | Acceptance criterion |
|----|----------------------|
| AC-RM-01 | New and reply emails correlate to the correct release. |
| AC-RM-02 | Required fields are never hallucinated; missing values remain explicitly missing. |
| AC-RM-03 | Duplicate intake and external writes are idempotent. |
| AC-RM-04 | No illegal state transition can be committed through API/MCP. |
| AC-RM-05 | No human approval can be fabricated or inferred from ambiguous language. |
| AC-RM-06 | Jira is not created before configured upstream approvals. |
| AC-RM-07 | Meeting is not scheduled before change approval. |
| AC-RM-08 | COMPLETED cannot be reached without configured validated evidence. |
| AC-RM-09 | Secrets and PII-sensitive values configured as restricted are absent from application logs. |
| AC-RM-10 | Plugin can be installed for a second product using configuration only, without changing core agent logic. |

## Actors (section 2.2)

| Actor | Responsibility |
|-------|----------------|
| Requester | Submits release request and supplies missing information. |
| Release Owner | Owns completeness and readiness. |
| Product Owner | Technical/business-scope approval as configured. |
| VP / Business Approver | Business approval when required. |
| Change Manager | Approves governed production change. |
| SRE / Operations | Reviews operational readiness and participates in release. |
| Release Manager | Handles exceptions, overrides and audit review. |
| Harness Agents | Interpret, validate, draft and coordinate within policy boundaries. |
