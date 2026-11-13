"""Core schema from Implementation Guide v2.0 section 4.1 (Slice 2).

Requirements: BR-03, BR-04, BR-05, BR-08, NFR-01, NFR-04, NFR-06; AC-RM-03. Statements are copied verbatim from
specs/architecture.md section 5.1 with explicit InnoDB/utf8mb4 table options
(tests/architecture/test_db_migrations.py enforces this). The database itself and its accounts are provisioned by a
DBA, not by migrations. MySQL DDL is not transactional: a failed downgrade can leave tables partially dropped.

Revision ID: 0001
Revises:
Create Date: 2026-11-13
"""

from __future__ import annotations

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

CREATE_TABLES = (
    """
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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
""",
    """
CREATE TABLE release_component (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY, release_fk BIGINT UNSIGNED NOT NULL,
  component_name VARCHAR(200) NOT NULL, current_version VARCHAR(100), target_version VARCHAR(100) NOT NULL,
  repository_url VARCHAR(1000), pipeline_ref VARCHAR(500), deployment_order INT, rollback_version VARCHAR(100),
  FOREIGN KEY (release_fk) REFERENCES release_request(id) ON DELETE CASCADE,
  UNIQUE KEY uq_release_component(release_fk, component_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
""",
    """
CREATE TABLE release_approval (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY, release_fk BIGINT UNSIGNED NOT NULL,
  approval_type ENUM('TECHNICAL','BUSINESS','CHANGE','SRE','RELEASE_OWNER') NOT NULL,
  approver_email VARCHAR(320) NOT NULL, decision ENUM('PENDING','APPROVED','REJECTED','UNCLEAR') NOT NULL DEFAULT 'PENDING',
  comments TEXT, decision_at DATETIME(6), source_message_id VARCHAR(500),
  FOREIGN KEY (release_fk) REFERENCES release_request(id),
  UNIQUE KEY uq_approval(release_fk, approval_type, approver_email)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
""",
    """
CREATE TABLE release_evidence (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY, release_fk BIGINT UNSIGNED NOT NULL,
  evidence_type VARCHAR(100) NOT NULL, source_system VARCHAR(100) NOT NULL, source_reference VARCHAR(1000) NOT NULL,
  sha256 CHAR(64), validation_status ENUM('UNVERIFIED','VALID','INVALID') DEFAULT 'UNVERIFIED',
  captured_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  FOREIGN KEY (release_fk) REFERENCES release_request(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
""",
    """
CREATE TABLE release_transition (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY, release_fk BIGINT UNSIGNED NOT NULL,
  from_status VARCHAR(50), to_status VARCHAR(50) NOT NULL, actor_type VARCHAR(30) NOT NULL, actor_id VARCHAR(320),
  reason VARCHAR(2000), correlation_id CHAR(36) NOT NULL, created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  FOREIGN KEY (release_fk) REFERENCES release_request(id), INDEX ix_transition_release(release_fk, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
""",
    """
CREATE TABLE idempotency_record (
  idempotency_key VARCHAR(255) PRIMARY KEY, operation VARCHAR(100) NOT NULL, release_id VARCHAR(32),
  response_json JSON, created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
""",
    """
CREATE TABLE application_config (
  application_key VARCHAR(100) PRIMARY KEY, display_name VARCHAR(200) NOT NULL,
  product_owner_email VARCHAR(320), business_approver_email VARCHAR(320), change_manager_email VARCHAR(320),
  sre_dl VARCHAR(320), dev_team_dl VARCHAR(320), confluence_space_id VARCHAR(100), jira_project_key VARCHAR(50),
  jira_issue_type VARCHAR(100), active BOOLEAN NOT NULL DEFAULT TRUE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
""",
)

DROP_ORDER = (
    "application_config",
    "idempotency_record",
    "release_transition",
    "release_evidence",
    "release_approval",
    "release_component",
    "release_request",
)


def upgrade() -> None:
    for statement in CREATE_TABLES:
        op.execute(statement)


def downgrade() -> None:
    for table in DROP_ORDER:
        op.drop_table(table)
