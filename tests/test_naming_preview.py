"""Tests for POST /api/naming/preview (stateless, no Odoo/DB writes)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_BACKEND = Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from main import app  # noqa: E402


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_naming_preview_universal_returns_name_and_keywords(client: TestClient) -> None:
    payload = {
        "part_type": "Фильтр масляный",
        "brand": "MANN",
        "article": "W712/75",
        "applicability_type": "universal",
        "current_name": "Старое имя из Odoo",
    }
    response = client.post("/api/naming/preview", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["status"] in {"generated", "review", "error"}
    assert data["name"]
    assert "W712" in data["name"] or "MANN" in data["name"]
    assert data["search_keywords"]
    assert data["current_name"] == "Старое имя из Odoo"
    assert data["changed"] is True


def test_naming_preview_fitment_requires_primary(client: TestClient) -> None:
    response = client.post(
        "/api/naming/preview",
        json={
            "part_type": "Колодки тормозные",
            "brand": "BOSCH",
            "article": "ABC123",
            "applicability_type": "fitment",
        },
    )
    assert response.status_code == 422


def test_naming_preview_fitment_with_primary_make_model(client: TestClient) -> None:
    response = client.post(
        "/api/naming/preview",
        json={
            "part_type": "Колодки тормозные",
            "brand": "BOSCH",
            "article": "ABC123",
            "applicability_type": "fitment",
            "primary_make": "Toyota",
            "primary_model": "Camry",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"]
    assert "Toyota" in data["name"] or "Camry" in data["name"]
