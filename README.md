# release-management-harness

A reusable, AI-native release-management harness. It turns a manual, multi-system release process (shared mailbox,
Confluence, Jira/JSM, Outlook/Teams) into an auditable workflow, while humans stay accountable for approvals and
production-impacting actions.

Source of truth: `AI_Native_Release_Management_Harness.pdf` (v2.0), [AGENTS.md](AGENTS.md) and [specs/](specs/).

## Architecture

```
Agents (Copilot Studio) -> Release MCP server -> Release API / Policy Engine -> MySQL
```

- **Agents** interpret language and draft artifacts. They have no database connection, no SQL and no credentials.
- **Release MCP** (`services/release-mcp`) exposes only the 10 tools in `policies/tool-allowlist.yaml` and calls only
  the Release API.
- **Release API** (`services/release-api`, FastAPI + SQLAlchemy 2.x + Alembic) owns transactions, validation,
  authorization, idempotency, the state machine, gates and audit.
- **MySQL 8.4** is reachable only from the Release API and from migrations (`db/migrations`), which use a separate
  identity.

These boundaries are enforced by tests in `tests/architecture/`. Details: [specs/architecture.md](specs/architecture.md).

## Repository layout

| Path | Purpose |
|------|---------|
| `specs/` | Business requirements, architecture, lifecycle, security, tool contracts, slices |
| `policies/` | State transitions, approvals, tool allow-list (enforced in code) |
| `config/` | Externalized harness config, `environments/{dev,test,prod}.yaml` overlays, per-product config (no secrets) |
| `services/release-api/` | Release API (sole MySQL client) |
| `services/release-mcp/` | Release MCP server (no database dependencies) |
| `db/migrations/`, `db/seed/` | Alembic migrations and dev/test seed data (see [db/README.md](db/README.md)) |
| `agents/`, `skills/`, `hooks/` | Agent instructions, skills and hooks (Slice 7) |
| `tests/` | `unit/ integration/ policy/ prompt-injection/ golden/ architecture/` |
| `.github/workflows/` | `validate.yml` (gates), `build.yml` (images), `security.yml` (security gates) |
| `scripts/` | `bootstrap.ps1`, `bootstrap.sh`, `validate.ps1` |

## Quick start

Requires Python 3.12+ and a locally installed MySQL. Docker is needed only to build the service images (CI does this).

```powershell
.\scripts\bootstrap.ps1     # creates .venv and installs tooling + both services (editable)
.\scripts\validate.ps1      # ruff check . ; mypy . ; pytest -q
```

On Linux/macOS run `scripts/bootstrap.sh`, then run `ruff check .`, `mypy .` and `pytest -q` from `.venv`.

### Pre-commit hooks

```powershell
.\.venv\Scripts\Activate.ps1   # the mypy hook runs from the active environment
pre-commit install             # ruff, mypy (strict) and gitleaks on every commit
```

### Release API settings

Settings are read from environment variables only (pydantic-settings; `.env` files are not read by the app).
`MYSQL_PASSWORD` is required and has no default, so the API refuses to start without it. It is held as a masked
`SecretStr` and never logged. `GET /health` returns `200 {"status": "ok"}`.

### Local MySQL (development only)

The database is a locally installed MySQL; there is no docker-compose. The app connects as the least-privilege user
`release_api@127.0.0.1` (`SELECT, INSERT, UPDATE` on `release_management.*` only, never root). Its credentials live only
in your git-ignored `.env` (copy `.env.example` and fill it in). Load them into your session before running the API or
Alembic:

```powershell
. .\scripts\load-env.ps1                      # prints variable names only, never values
uvicorn release_api.main:create_app --factory  # GET http://127.0.0.1:8000/health
alembic -c db/migrations/alembic.ini current
```

To create the user on a new machine, a DBA or root session runs the following once, then puts the password in `.env`:
`CREATE USER 'release_api'@'127.0.0.1' IDENTIFIED BY '<choose>'; GRANT SELECT, INSERT, UPDATE ON release_management.* TO 'release_api'@'127.0.0.1';`

### Schema migrations and seed (Slice 2)

Alembic migrations (`db/migrations/versions/`) create the section 4.1 schema (InnoDB, utf8mb4, UTC sessions, strict SQL
mode). They run as a separate migration identity, `release_migrator` (`MIGRATION_MYSQL_USER` /
`MIGRATION_MYSQL_PASSWORD`). The Release API runtime identity `release_api` cannot change the schema or delete rows. A
DBA creates the database and both accounts; migrations never create users, grants or databases:

```sql
CREATE DATABASE release_management CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
CREATE USER 'release_migrator'@'127.0.0.1' IDENTIFIED BY '<choose>';
GRANT CREATE, ALTER, DROP, INDEX, REFERENCES, SELECT, INSERT, UPDATE, DELETE ON release_management.* TO 'release_migrator'@'127.0.0.1';
```

```powershell
. .\scripts\load-env.ps1
alembic -c db/migrations/alembic.ini upgrade head
python -m release_api.db.seed --file db/seed/dev.yaml   # APP_ENV=dev or test only; application_config rows only
```

### Integration tests (local MySQL)

`tests/integration` runs against a disposable database named by `MYSQL_TEST_DATABASE`, which must end in `_test`. The
tests migrate it up and down and clear its tables. Grant both identities on it the same privileges they have on
`release_management`. Without these variables the tests skip with an explicit reason. CI has no MySQL service yet
(open question #28), so these tests are skipped in CI too.

## Secrets

No secrets in code, config, tests, prompts or logs (NFR-03). Configuration refers to secrets by name
(`{secretRef: NAME}`), and they are resolved at runtime from the approved secret provider. `.env` is git-ignored.
`tests/architecture/test_secrets.py` fails the build if credential literals are committed, and the gitleaks pre-commit
hook blocks them before they are committed.

## Gates (Definition of Done)

```
pytest -q
ruff check .
mypy .
```

Work proceeds one slice at a time, tests first, as listed in [specs/slices.md](specs/slices.md). Every change traces
to BR-/NFR-/AC-RM- IDs in [specs/business-requirements.md](specs/business-requirements.md).
