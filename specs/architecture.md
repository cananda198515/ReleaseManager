# Architecture

Source: Implementation Guide v2.0, sections 1.1, 3, 3.1, 4, 4.1 and 10. Requirements: NFR-01, NFR-03, NFR-06, NFR-07, NFR-09.

## 1. Layers (section 1.1)

| Layer | Recommended implementation | Why |
|-------|----------------------------|-----|
| Database | MySQL 8.4 LTS-compatible managed MySQL | Relational transactions, constraints, mature tooling and portability. |
| Database access | Release API: Python FastAPI + SQLAlchemy + Alembic | Never give an LLM unrestricted SQL; expose narrow validated operations. |
| Agent/runtime | Microsoft Copilot Studio GitHub Copilot harness | Reasoning-heavy orchestration, skills, hooks, connected agents and tools. |
| Integration | MCP over Streamable HTTP; REST/custom connector fallback | Portable typed tool boundary that can be consumed by agentic clients. |
| Workflow | Copilot Studio Workflows / agent flows | Deterministic approvals, email, reminders and system actions. |
| External systems | Outlook, Jira/JSM, Confluence, Teams/Calendar | Matches the current release process. |
| Dev harness | VS Code + GitHub Copilot CLI/Chat + Git repository | Source-controlled specifications, agents, skills, policies and tests. |
| Secrets | Azure Key Vault or approved enterprise secret manager | No database or Atlassian credentials in prompts, source or logs. |

## 2. Target architecture (section 3)

The MySQL database is not connected directly to the language model. A Release API owns transactions and business rules;
an MCP server exposes only explicit tools. Copilot Studio agents and workflows call those tools. This creates a stable
security and portability boundary.

```
[Request Channels]
 Outlook shared mailbox | Teams | Jira | API
              |
              v
     [Release Orchestrator Agent]
        |        |        |
        v        v        v
     Intake  Readiness   Risk
         \       |       /
          +------+------+
                 |
                 v
        [Release MCP Server]
                 |
                 v
     [Release API / Policy Engine]
                 |
                 v
              [MySQL]
                 |
   +-------------+--------------+
   |             |              |
Confluence    Jira/JSM     Outlook/Teams
   |             |              |
 Notes         Change     Approval/Meeting
                 |
                 v
      Evidence + Audit + Metrics
```

Call chain: **Agents -> Release MCP -> Release API -> MySQL.** Agents never touch MySQL.

## 3. Trust boundaries (section 3.1)

- **LLM boundary:** agents may request tool operations but cannot issue arbitrary SQL or bypass server validation.
- **API boundary:** every write checks authorization, permitted state transition, prerequisites and idempotency.
- **Database boundary:** API identity is restricted to the release schema; migrations use a separate identity.
- **External-system boundary:** Jira/Confluence/Outlook credentials have only required scopes.
- **Human boundary:** production approval and other high-impact decisions stay with named human owners.

## 4. Repository layout (section 10)

```
release-management-harness/
  AGENTS.md
  README.md
  plugin.json
  .mcp.json
  config/
    release-harness.schema.json
    default.yaml
    environments/dev.yaml
    environments/test.yaml
    environments/prod.yaml
  specs/
    business-requirements.md
    architecture.md
    release-lifecycle.md
    security.md
  agents/
    orchestrator.md intake.md readiness.md risk.md release-notes.md
    change-request.md communications.md coordinator.md evidence.md
  skills/
    parse-release-request/
    validate-release-schema/
    calculate-release-risk/
    check-release-readiness/
    generate-release-notes/
    generate-change-request/
    collect-release-evidence/
  hooks/
    before-tool-call/
    after-tool-call/
    before-final-response/
    on-error/
  policies/
    state-transitions.yaml
    approvals.yaml
    tool-allowlist.yaml
    data-classification.yaml
  services/
    release-api/
    release-mcp/
  db/
    migrations/
    seed/
  tests/
    unit/ integration/ policy/ prompt-injection/ golden/ architecture/
  .github/workflows/
    validate.yml
    build.yml
    security.yml
    package.yml
  scripts/
    bootstrap.ps1 bootstrap.sh validate.ps1 package.ps1
```

Bootstrap additions requested for this repository (not in the guide's layout): `.github/copilot-instructions.md`,
`specs/tool-contracts.md`, `specs/slices.md`, `config/products/wileyplus.yaml`. See open questions in `specs/slices.md`.

## 5. MySQL data model (section 4)

Use InnoDB, utf8mb4, UTC timestamps and migration-controlled schema changes. Store normalized
components/approvals/evidence rather than comma-separated values.

### 5.1 Core schema (section 4.1, verbatim)

```sql
CREATE DATABASE release_management CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
USE release_management;

CREATE TABLE release_request (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  release_id VARCHAR(32) NOT NULL UNIQUE,
  correlation_id CHAR(36) NOT NULL UNIQUE,
  release_name VARCHAR(200), application_key VARCHAR(100),
  original_subject VARCHAR(500), requester_name VARCHAR(200), requester_email VARCHAR(320),
  expected_start_utc DATETIME(6), expected_end_utc DATETIME(6),
  impact TEXT, downtime_type ENUM('NONE','PARTIAL','FULL'), downtime_details VARCHAR(2000),
  implementation_plan TEXT, validation_plan TEXT, rollback_plan TEXT,
  risk_score SMALLINT, risk_level ENUM('LOW','MEDIUM','HIGH','CRITICAL'),
  status VARCHAR(50) NOT NULL DEFAULT 'RECEIVED',
  conversation_id VARCHAR(500), last_message_id VARCHAR(500),
  confluence_page_id VARCHAR(100), confluence_url VARCHAR(1000),
  jira_key VARCHAR(100), jira_url VARCHAR(1000), meeting_id VARCHAR(500),
  missing_fields JSON, version INT NOT NULL DEFAULT 1,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  INDEX ix_release_status(status), INDEX ix_release_start(expected_start_utc)
);

CREATE TABLE release_component (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY, release_fk BIGINT UNSIGNED NOT NULL,
  component_name VARCHAR(200) NOT NULL, current_version VARCHAR(100), target_version VARCHAR(100) NOT NULL,
  repository_url VARCHAR(1000), pipeline_ref VARCHAR(500), deployment_order INT, rollback_version VARCHAR(100),
  FOREIGN KEY (release_fk) REFERENCES release_request(id) ON DELETE CASCADE,
  UNIQUE KEY uq_release_component(release_fk, component_name)
);

CREATE TABLE release_approval (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY, release_fk BIGINT UNSIGNED NOT NULL,
  approval_type ENUM('TECHNICAL','BUSINESS','CHANGE','SRE','RELEASE_OWNER') NOT NULL,
  approver_email VARCHAR(320) NOT NULL, decision ENUM('PENDING','APPROVED','REJECTED','UNCLEAR') NOT NULL DEFAULT 'PENDING',
  comments TEXT, decision_at DATETIME(6), source_message_id VARCHAR(500),
  FOREIGN KEY (release_fk) REFERENCES release_request(id),
  UNIQUE KEY uq_approval(release_fk, approval_type, approver_email)
);

CREATE TABLE release_evidence (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY, release_fk BIGINT UNSIGNED NOT NULL,
  evidence_type VARCHAR(100) NOT NULL, source_system VARCHAR(100) NOT NULL, source_reference VARCHAR(1000) NOT NULL,
  sha256 CHAR(64), validation_status ENUM('UNVERIFIED','VALID','INVALID') DEFAULT 'UNVERIFIED',
  captured_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  FOREIGN KEY (release_fk) REFERENCES release_request(id)
);

CREATE TABLE release_transition (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY, release_fk BIGINT UNSIGNED NOT NULL,
  from_status VARCHAR(50), to_status VARCHAR(50) NOT NULL, actor_type VARCHAR(30) NOT NULL, actor_id VARCHAR(320),
  reason VARCHAR(2000), correlation_id CHAR(36) NOT NULL, created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  FOREIGN KEY (release_fk) REFERENCES release_request(id), INDEX ix_transition_release(release_fk, created_at)
);

CREATE TABLE idempotency_record (
  idempotency_key VARCHAR(255) PRIMARY KEY, operation VARCHAR(100) NOT NULL, release_id VARCHAR(32),
  response_json JSON, created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
);

CREATE TABLE application_config (
  application_key VARCHAR(100) PRIMARY KEY, display_name VARCHAR(200) NOT NULL,
  product_owner_email VARCHAR(320), business_approver_email VARCHAR(320), change_manager_email VARCHAR(320),
  sre_dl VARCHAR(320), dev_team_dl VARCHAR(320), confluence_space_id VARCHAR(100), jira_project_key VARCHAR(50),
  jira_issue_type VARCHAR(100), active BOOLEAN NOT NULL DEFAULT TRUE
);
```
