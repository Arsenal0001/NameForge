"""Tests for POST /api/products/{product_id}/fitment."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

_BACKEND = Path(__file__).resolve().parents[1] / "backend"
_ROOT = _BACKEND.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import src.db as legacy_db  # noqa: E402
from app.core import config  # noqa: E402
from app.core.database import get_db  # noqa: E402
from app.core.schema_patches import apply_schema_patches  # noqa: E402
from main import app  # noqa: E402


@pytest.fixture
def fitment_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "fitment_test.db"
    url = f"sqlite:///{db_path.as_posix()}"

    monkeypatch.setattr(config.settings, "DATABASE_URL", url)
    monkeypatch.setattr(legacy_db, "DB_PATH", str(db_path))
    legacy_db.init_db()

    engine = create_engine(url, connect_args={"check_same_thread": False})
    apply_schema_patches(engine)

    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO templates (
                    template_key, version, applicability_type, name_pattern
                )
                VALUES (
                    'test_fitment', 'v1', 'fitment',
                    '{part_type} {brand} для {make} {model}'
                )
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO products (
                    ms_product_id, external_code, article, brand, part_type,
                    applicability_type, template_key, template_version,
                    source_hash, generation_status, name_locked
                )
                VALUES (
                    'odoo-fitment-1', 'ext-fitment-1', 'BRK-001', 'BOSCH',
                    'Колодки тормозные', 'fitment', 'test_fitment', 'v1',
                    '', 'new', 0
                )
                """
            )
        )

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    product_id = 1

    yield client, product_id, session_factory

    app.dependency_overrides.clear()


def test_save_fitment_regenerates_preview_name(
    fitment_client: tuple[TestClient, int, sessionmaker],
) -> None:
    client, product_id, session_factory = fitment_client

    response = client.post(
        f"/api/products/{product_id}/fitment",
        json={"make_id": 1, "model_id": 101, "generation_id": 1001},
    )

    assert response.status_code == 200
    data = response.json()
    product = data["product"]

    assert product["id"] == product_id
    assert product["primary_make"] == "BMW"
    assert product["primary_model"] == "3 Series"
    assert product["preview_name"]
    assert "BMW" in product["preview_name"]
    assert "3 Series" in product["preview_name"]
    assert product["naming_status"] in {"no_template", "pending_sync", "synced"}

    with session_factory() as session:
        row = session.execute(
            text(
                "SELECT make_id, model_id, generation_id FROM product_fitments "
                "WHERE product_id = :pid"
            ),
            {"pid": product_id},
        ).one()
        assert row == (1, 101, 1001)

        fitment = session.execute(
            text(
                "SELECT make, model, body, is_primary FROM fitments "
                "WHERE product_id = :pid"
            ),
            {"pid": product_id},
        ).one()
        assert fitment[0] == "BMW"
        assert fitment[1] == "3 Series"
        assert fitment[2] == "E90"
        assert fitment[3] == 1


def test_save_fitment_rejects_invalid_model_for_make(
    fitment_client: tuple[TestClient, int, sessionmaker],
) -> None:
    client, product_id, _ = fitment_client

    response = client.post(
        f"/api/products/{product_id}/fitment",
        json={"make_id": 1, "model_id": 201, "generation_id": 2001},
    )

    assert response.status_code == 422


def test_save_fitment_product_not_found(
    fitment_client: tuple[TestClient, int, sessionmaker],
) -> None:
    client, _, _ = fitment_client

    response = client.post(
        "/api/products/99999/fitment",
        json={"make_id": 1, "model_id": 101, "generation_id": 1001},
    )

    assert response.status_code == 404
