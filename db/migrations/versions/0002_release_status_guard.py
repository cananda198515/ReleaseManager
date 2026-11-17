"""Database guard for release_request.status (Slice 3 security review, High finding #6).

Rejects, for every database identity, a release inserted in any state other than the initial state and any status
change that is not an edge in policies/state-transitions.yaml (P9, P10). The edge list is generated from the policy and
tests/architecture/test_status_guard_migration.py keeps the two identical. The Release API's state machine remains the
primary control (gates, audit rows); this trigger stops direct SQL from skipping it.
Requirements: NFR-01, NFR-02, NFR-06; AC-RM-04. Approved by the slice owner on 17 Nov 2026 (specs/slices.md #32).

DBA prerequisites (db/README.md): the migration identity needs TRIGGER, and with binary logging enabled MySQL requires
log_bin_trust_function_creators=1 for a non-SUPER account to create triggers.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-17
"""

from __future__ import annotations

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

INITIAL_STATUS = "RECEIVED"
ALLOWED_STATUS_EDGES: tuple[tuple[str, str], ...] = (
    ("RECEIVED", "PENDING_INFORMATION"),
    ("RECEIVED", "INFO_COMPLETE"),
    ("RECEIVED", "CANCELLED"),
    ("RECEIVED", "ERROR"),
    ("PENDING_INFORMATION", "INFO_COMPLETE"),
    ("PENDING_INFORMATION", "CANCELLED"),
    ("PENDING_INFORMATION", "MANUAL_REVIEW"),
    ("PENDING_INFORMATION", "ERROR"),
    ("INFO_COMPLETE", "VALIDATION_PENDING"),
    ("INFO_COMPLETE", "CANCELLED"),
    ("INFO_COMPLETE", "ERROR"),
    ("VALIDATION_PENDING", "OWNER_REVIEW"),
    ("VALIDATION_PENDING", "MANUAL_REVIEW"),
    ("VALIDATION_PENDING", "ERROR"),
    ("OWNER_REVIEW", "BUSINESS_APPROVAL_PENDING"),
    ("OWNER_REVIEW", "REJECTED"),
    ("OWNER_REVIEW", "CANCELLED"),
    ("BUSINESS_APPROVAL_PENDING", "CHANGE_CREATION_PENDING"),
    ("BUSINESS_APPROVAL_PENDING", "REJECTED"),
    ("BUSINESS_APPROVAL_PENDING", "CANCELLED"),
    ("CHANGE_CREATION_PENDING", "CHANGE_APPROVAL_PENDING"),
    ("CHANGE_CREATION_PENDING", "ERROR"),
    ("CHANGE_APPROVAL_PENDING", "SCHEDULED"),
    ("CHANGE_APPROVAL_PENDING", "REJECTED"),
    ("CHANGE_APPROVAL_PENDING", "ERROR"),
    ("SCHEDULED", "READY_FOR_RELEASE"),
    ("SCHEDULED", "CANCELLED"),
    ("SCHEDULED", "ERROR"),
    ("READY_FOR_RELEASE", "DEPLOYING"),
    ("READY_FOR_RELEASE", "CANCELLED"),
    ("READY_FOR_RELEASE", "ERROR"),
    ("DEPLOYING", "VALIDATING"),
    ("DEPLOYING", "FAILED"),
    ("DEPLOYING", "ROLLED_BACK"),
    ("DEPLOYING", "ERROR"),
    ("VALIDATING", "COMPLETED"),
    ("VALIDATING", "FAILED"),
    ("VALIDATING", "ROLLED_BACK"),
    ("VALIDATING", "ERROR"),
)

_EDGE_LIST = ",\n      ".join(f"'{source}>{target}'" for source, target in ALLOWED_STATUS_EDGES)

CREATE_INSERT_TRIGGER = f"""
CREATE TRIGGER trg_release_status_insert BEFORE INSERT ON release_request
FOR EACH ROW
BEGIN
  IF NEW.status IS NULL OR NEW.status <> '{INITIAL_STATUS}' THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'release_request.status must start as {INITIAL_STATUS}';
  END IF;
END
"""

CREATE_UPDATE_TRIGGER = f"""
CREATE TRIGGER trg_release_status_update BEFORE UPDATE ON release_request
FOR EACH ROW
BEGIN
  IF NOT (NEW.status <=> OLD.status) AND CONCAT(OLD.status, '>', NEW.status) NOT IN (
      {_EDGE_LIST}
  ) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'release_request.status change is not an allowed transition';
  END IF;
END
"""


def upgrade() -> None:
    op.execute(CREATE_INSERT_TRIGGER)
    op.execute(CREATE_UPDATE_TRIGGER)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_release_status_update")
    op.execute("DROP TRIGGER IF EXISTS trg_release_status_insert")
