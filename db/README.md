# Database (Slice 2)

The Release API owns the `release_management` schema (Implementation Guide v2.0 section 4.1; `specs/architecture.md`
section 5.1). Agents and the Release MCP server never connect to MySQL. Requirements: NFR-03, NFR-06; BR-03, BR-04,
BR-05, BR-08, NFR-01, NFR-04; AC-RM-03.

| Path | Contents |
|------|----------|
| `migrations/` | Alembic environment; `0001_core_schema.py` (7 tables, InnoDB, utf8mb4_0900_ai_ci, `DATETIME(6)`) and `0002_release_status_guard.py` (status triggers, below) |
| `seed/dev.yaml`, `seed/test.yaml` | `application_config` placeholder rows for `python -m release_api.db.seed` (dev/test only) |
| `seed/dev_application_config.sql` | The same dev WileyPLUS row as a plain-mysql upsert |

## Two database identities (NFR-06; `specs/security.md` section 3)

| Identity | Used by | Privileges on `release_management.*` | Credentials (by name only) |
|----------|---------|--------------------------------------|----------------------------|
| `release_migrator` | Alembic migrations only | DDL plus data access needed by migrations | `MIGRATION_MYSQL_USER`, `MIGRATION_MYSQL_PASSWORD` |
| `release_api` | Release API runtime | `SELECT, INSERT, UPDATE` only (no `DELETE`, `DROP`, `ALTER`, `CREATE` or `GRANT`) | `MYSQL_USER`, `MYSQL_PASSWORD` |

Neither identity is root and neither has `GRANT OPTION`. Release, approval, evidence and audit rows are never deleted at
runtime. Passwords come from the approved secret manager (locally: the git-ignored `.env`); never commit them.

A DBA (not the migrations) creates the database and accounts once:

```sql
CREATE DATABASE release_management CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
CREATE USER 'release_migrator'@'127.0.0.1' IDENTIFIED BY '<from-secret-manager>';
CREATE USER 'release_api'@'127.0.0.1' IDENTIFIED BY '<from-secret-manager>';
GRANT CREATE, ALTER, DROP, INDEX, REFERENCES, TRIGGER, SELECT, INSERT, UPDATE, DELETE ON release_management.* TO 'release_migrator'@'127.0.0.1';
GRANT SELECT, INSERT, UPDATE ON release_management.* TO 'release_api'@'127.0.0.1';
-- Binary logging is on by default in MySQL 8; a non-SUPER account can create triggers only with:
SET PERSIST log_bin_trust_function_creators = 1;
```

For local integration tests, repeat the database creation and both grants for `release_management_test`
(`MYSQL_TEST_DATABASE`; the name must end in `_test`).

## Status guard triggers (`0002_release_status_guard.py`)

`trg_release_status_insert` rejects a release inserted in any status other than `RECEIVED`, and
`trg_release_status_update` rejects any status change that is not an edge in `policies/state-transitions.yaml`
(`SIGNAL SQLSTATE '45000'`, MySQL error 1644). They apply to every identity, so direct SQL cannot skip the Release API
state machine. The edge list is generated into the migration; `tests/architecture/test_status_guard_migration.py`
fails if it drifts from the policy, and changing the policy therefore requires a new migration. The triggers do not
replace the Release API gates and audit rows; they only constrain which status values can be written.

## Commands

```powershell
. .\scripts\load-env.ps1
alembic -c db/migrations/alembic.ini upgrade head
alembic -c db/migrations/alembic.ini downgrade base   # dev/test only; MySQL DDL is not transactional
python -m release_api.db.seed --file db/seed/dev.yaml # or: mysql ... < db/seed/dev_application_config.sql
pytest -q tests/integration                          # skips with a reason unless the _test database is configured
```

Sessions are forced to `time_zone = '+00:00'` and strict `sql_mode`, so timestamps are UTC with microseconds and invalid
enum or `NOT NULL` values are rejected.
