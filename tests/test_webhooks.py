"""Tests for Odoo product webhook endpoint."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

_BACKEND = Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from main import app  # noqa: E402


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@patch("app.api.routers.webhooks.process_product_webhook_async")
def test_odoo_product_webhook_returns_200_and_schedules_background(
    mock_process: object,
    client: TestClient,
) -> None:
    response = client.post(
        "/api/webhooks/odoo/product",
        json={"product_id": 123, "default_code": "ART-01"},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "accepted"}
    mock_process.assert_called_once()
    payload = mock_process.call_args[0][0]
    assert payload.product_id == 123
    assert payload.default_code == "ART-01"


def test_odoo_product_webhook_rejects_invalid_payload(client: TestClient) -> None:
    response = client.post(
        "/api/webhooks/odoo/product",
        json={"product_id": 0},
    )
    assert response.status_code == 422
