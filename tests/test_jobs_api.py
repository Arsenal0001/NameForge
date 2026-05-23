"""Tests for POST /api/jobs/* background triggers."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

_BACKEND = Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.services.job_lock import JobKind, release, try_acquire  # noqa: E402
from main import app  # noqa: E402


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_sync_from_odoo_returns_202(client: TestClient) -> None:
    with patch("app.api.routers.jobs.OdooClient") as mock_client:
        mock_client.return_value.test_connection.return_value = (True, "api@test")
        response = client.post("/api/jobs/sync-from-odoo")

    assert response.status_code == 202
    data = response.json()
    assert data["status"] == "accepted"
    assert data["job"] == JobKind.SYNC_FROM_ODOO
    release(JobKind.SYNC_FROM_ODOO)


def test_job_conflict_when_already_running(client: TestClient) -> None:
    assert try_acquire(JobKind.ENRICH) is True
    try:
        response = client.post("/api/jobs/enrich")
        assert response.status_code == 409
        assert response.json()["detail"] == "Job is already running"
    finally:
        release(JobKind.ENRICH)


def test_enrich_missing_jsonl_returns_400(client: TestClient) -> None:
    with patch("app.api.routers.jobs.DEFAULT_JSONL") as mock_path:
        mock_path.is_file.return_value = False
        response = client.post("/api/jobs/enrich")

    assert response.status_code == 400
    assert "JSONL not found" in response.json()["detail"]


def test_push_to_odoo_returns_202(client: TestClient) -> None:
    with patch("app.api.routers.jobs.OdooClient") as mock_client:
        mock_client.return_value.test_connection.return_value = (True, "api@test")
        response = client.post("/api/jobs/push-to-odoo")

    assert response.status_code == 202
    assert response.json()["job"] == JobKind.PUSH_TO_ODOO
    release(JobKind.PUSH_TO_ODOO)


def test_active_jobs_returns_progress_snapshot(client: TestClient) -> None:
    from app.services.job_progress import job_progress

    job_progress.start(JobKind.ENRICH, total_items=1000)
    job_progress.update(JobKind.ENRICH, 450, total_items=1000, force=True)

    response = client.get("/api/jobs/active")

    assert response.status_code == 200
    data = response.json()
    assert len(data["jobs"]) >= 1
    enrich = next(item for item in data["jobs"] if item["job_type"] == JobKind.ENRICH)
    assert enrich["status"] == "running"
    assert enrich["processed_items"] == 450
    assert enrich["total_items"] == 1000
    assert enrich["progress_percent"] == 45.0

    job_progress.complete(JobKind.ENRICH, processed_items=1000)
