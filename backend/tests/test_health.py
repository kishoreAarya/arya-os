"""
Sprint 1 smoke tests — confirms the app boots and root route responds.
The /health endpoint itself needs live Postgres/Redis, so it's exercised
via docker-compose, not here (see docs/RUNNING.md).
"""
from fastapi.testclient import TestClient

from app.main import app


def test_root_returns_running_status():
    with TestClient(app) as client:
        response = client.get("/")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "running"
        assert body["sprint"] == 1
