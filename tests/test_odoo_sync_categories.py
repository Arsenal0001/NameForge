"""Tests for POST /api/odoo/sync/categories."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

_BACKEND = Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from main import app  # noqa: E402


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@patch("app.api.odoo.sync_odoo_categories")
@patch("app.api.odoo.OdooClient")
def test_sync_categories_returns_stats(
    mock_client_cls: MagicMock,
    mock_sync: MagicMock,
    client: TestClient,
) -> None:
    mock_client_cls.return_value = MagicMock()
    mock_sync.return_value = {"inserted": 120, "updated": 50, "total": 170}

    response = client.post("/api/odoo/sync/categories")

    assert response.status_code == 200
    data = response.json()
    assert data == {"inserted": 120, "updated": 50, "total": 170}
    mock_sync.assert_called_once()


@patch("app.api.odoo.sync_odoo_categories")
@patch("app.api.odoo.OdooClient")
def test_sync_categories_preserves_parent_id_parsing(
    mock_client_cls: MagicMock,
    mock_sync: MagicMock,
    client: TestClient,
) -> None:
    """Endpoint delegates to service that maps Odoo many2one parent_id → int."""
    mock_client_cls.return_value = MagicMock()
    mock_sync.return_value = {"inserted": 1, "updated": 0, "total": 1}

    response = client.post("/api/odoo/sync/categories?chunk_size=50")

    assert response.status_code == 200
    _db_arg, client_arg = mock_sync.call_args[0]
    assert client_arg is mock_client_cls.return_value
    assert mock_sync.call_args.kwargs["chunk_size"] == 50
