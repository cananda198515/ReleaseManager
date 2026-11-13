"""Release API application factory. Business endpoints (specs/tool-contracts.md section 1) arrive in Slice 5."""

from __future__ import annotations

from fastapi import FastAPI

from release_api.settings import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI(title="Release API", version="0.1.0")
    # Fail fast at startup if required configuration (e.g. MYSQL_PASSWORD) is missing.
    app.state.settings = settings if settings is not None else Settings()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
