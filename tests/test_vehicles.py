"""Tests for GET /api/vehicles/* (mock applicability matrix)."""

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


def test_list_makes_returns_mock_catalog(client: TestClient) -> None:
    response = client.get("/api/vehicles/makes")

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 3

    names = {row["name"] for row in data}
    assert "BMW" in names
    assert "Lada" in names

    for row in data:
        assert isinstance(row["id"], int)
        assert isinstance(row["name"], str)
        assert row["name"]


def test_list_models_requires_valid_make(client: TestClient) -> None:
    makes = client.get("/api/vehicles/makes").json()
    bmw = next(m for m in makes if m["name"] == "BMW")

    response = client.get("/api/vehicles/models", params={"make_id": bmw["id"]})
    assert response.status_code == 200
    models = response.json()
    assert len(models) >= 2
    assert all(m["make_id"] == bmw["id"] for m in models)

    missing = client.get("/api/vehicles/models", params={"make_id": 99999})
    assert missing.status_code == 404


def test_list_generations_for_model(client: TestClient) -> None:
    makes = client.get("/api/vehicles/makes").json()
    bmw = next(m for m in makes if m["name"] == "BMW")
    models = client.get("/api/vehicles/models", params={"make_id": bmw["id"]}).json()
    series3 = next(m for m in models if m["name"] == "3 Series")

    response = client.get(
        "/api/vehicles/generations",
        params={"model_id": series3["id"]},
    )
    assert response.status_code == 200
    generations = response.json()
    assert len(generations) >= 2
    assert all(g["model_id"] == series3["id"] for g in generations)

    missing = client.get("/api/vehicles/generations", params={"model_id": 99999})
    assert missing.status_code == 404
