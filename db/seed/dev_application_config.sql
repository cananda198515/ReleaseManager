-- Dev seed: one application_config row (Slice 2; BR-15, NFR-09). Placeholder example.com values only; no secrets.
-- Plain-mysql alternative to `python -m release_api.db.seed --file db/seed/dev.yaml`; keep both in sync.
-- Re-runnable (upsert on application_key). Run in dev only, against release_management, as release_api:
--   mysql -h 127.0.0.1 -u release_api -p release_management < db/seed/dev_application_config.sql
INSERT INTO application_config (
  application_key, display_name, product_owner_email, business_approver_email, change_manager_email,
  sre_dl, dev_team_dl, confluence_space_id, jira_project_key, jira_issue_type, active
) VALUES (
  'wileyplus', 'WileyPLUS', 'product-owner@example.com', 'business-approver@example.com', 'change-manager@example.com',
  'sre@example.com', 'dev-team@example.com', 'EXAMPLE', 'EXAMPLE', 'Change', TRUE
) AS new
ON DUPLICATE KEY UPDATE
  display_name = new.display_name,
  product_owner_email = new.product_owner_email,
  business_approver_email = new.business_approver_email,
  change_manager_email = new.change_manager_email,
  sre_dl = new.sre_dl,
  dev_team_dl = new.dev_team_dl,
  confluence_space_id = new.confluence_space_id,
  jira_project_key = new.jira_project_key,
  jira_issue_type = new.jira_issue_type,
  active = new.active;
