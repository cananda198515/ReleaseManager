"""Smoke test: GET /health returns 200 {"status": "ok"} (Slice 1; liveness endpoint from section 5.1)."""

from __future__ import annotations

import pytest


def test_health_returns_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.testclient import TestClient

    from release_api.main import create_app

    monkeypatch.setenv("MYSQL_PASSWORD", "test-only-placeholder")
    with TestClient(create_app()) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
