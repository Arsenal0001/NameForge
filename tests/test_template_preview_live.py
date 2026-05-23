"""Tests for POST /api/templates/preview-live (Odoo read mocked)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

_BACKEND = Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.schemas.template import (  # noqa: E402
    TemplateLivePreviewItem,
    TemplateLivePreviewResponse,
)
from main import app  # noqa: E402


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@patch("app.api.templates.run_live_preview")
def test_preview_live_endpoint_returns_pairs(mock_run: MagicMock, client: TestClient) -> None:
    mock_run.return_value = TemplateLivePreviewResponse(
        category_id=42,
        template_string="{part_type} {brand}",
        normalized_pattern="{part_type} {brand}",
        sample_source="cache",
        items=[
            TemplateLivePreviewItem(
                odoo_id=1,
                odoo_name="Коврик Toyota",
                generated_name="Коврик Toyota",
            ),
            TemplateLivePreviewItem(
                odoo_id=2,
                odoo_name="Коврик Lada",
                generated_name="Коврик Lada",
            ),
        ],
    )

    response = client.post(
        "/api/templates/preview-live",
        json={"category_id": 42, "template_string": "{part_type} {brand}"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["category_id"] == 42
    assert len(data["items"]) == 2
    assert data["items"][0]["odoo_name"] == "Коврик Toyota"
    assert data["items"][0]["generated_name"] == "Коврик Toyota"
    mock_run.assert_called_once()


@patch("app.services.template_live_preview.fetch_sample_products_from_odoo")
def test_run_live_preview_uses_odoo_fallback(mock_odoo_fetch: MagicMock) -> None:
    from app.services.template_live_preview import run_live_preview

    mock_odoo_fetch.return_value = [
        {
            "id": 801,
            "name": "Лампа H7 12V Philips",
            "default_code": "LMP-801",
            "categ_id": 9100,
        },
    ]

    session = MagicMock()
    cat = MagicMock()
    cat.complete_name = "Электрика / Лампы"
    cat.name = "Лампы"
    session.get.return_value = cat
    session.scalar.return_value = None

    with patch(
        "app.services.template_live_preview.fetch_sample_products_from_cache",
        return_value=[],
    ):
        result = run_live_preview(
            session,
            category_id=9100,
            template_string="{part_type} {brand}",
        )

    assert result.sample_source == "odoo"
    assert len(result.items) == 1
    assert result.items[0].odoo_name == "Лампа H7 12V Philips"
    assert result.items[0].generated_name
    mock_odoo_fetch.assert_called_once()
