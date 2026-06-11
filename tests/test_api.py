"""REST API smoke tests over an in-memory container (no Postgres, no Discord)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.container import Container
from app.infrastructure.persistence.in_memory import InMemoryJobRepository
from app.main import create_app


@pytest.fixture
def client():
    settings = Settings(
        openai_api_key="test-key",
        scheduler_enabled=False,
        _env_file=None,
    )
    container = Container(settings, repository=InMemoryJobRepository())
    app = create_app(settings, container=container)
    with TestClient(app) as test_client:
        yield test_client


def test_health(client: TestClient):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"


def test_jobs_empty(client: TestClient):
    response = client.get("/jobs")
    assert response.status_code == 200
    assert response.json() == []


def test_job_not_found(client: TestClient):
    assert client.get("/jobs/999").status_code == 404


def test_stats(client: TestClient):
    response = client.get("/stats")
    assert response.status_code == 200
    body = response.json()
    assert body["published"] == 0


def test_discord_test_unconfigured_returns_503(client: TestClient):
    response = client.post("/discord/test", json={"message": "hola"})
    assert response.status_code == 503
