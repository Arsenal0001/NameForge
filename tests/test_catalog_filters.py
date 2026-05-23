"""Tests for GET /api/products server-side filters."""

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
def catalog_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "catalog_filters_test.db"
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
                VALUES ('test_catalog', 'v1', 'universal', '{part_type} {brand}')
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO odoo_categories (
                    odoo_id, name, parent_id, complete_name,
                    naming_template_key, name_pattern, synced_at
                )
                VALUES (
                    10, 'Parts', NULL, 'Parts',
                    'car_mats', NULL, '2026-01-01T00:00:00Z'
                )
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO odoo_product_templates (
                    odoo_id, name, default_code, categ_id,
                    attribute_line_ids_json, synced_at
                )
                VALUES
                    (101, 'Alpha Odoo Name', 'A-101', 10, '[]', '2026-01-01T00:00:00Z'),
                    (102, 'Beta Odoo Name', 'A-102', 10, '[]', '2026-01-01T00:00:00Z')
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO products (
                    ms_product_id, external_code, article, brand, part_type,
                    applicability_type, template_key, template_version,
                    source_hash, generation_status, name_locked,
                    generated_name, last_sync_error
                )
                VALUES
                    ('101', 'ext-101', 'A-101', 'BRAND', 'Part', 'universal',
                     'test_catalog', 'v1', 'hash1', 'approved', 0,
                     'Alpha Odoo Name', NULL),
                    ('102', 'ext-102', 'A-102', 'BRAND', 'Part', 'universal',
                     'test_catalog', 'v1', 'hash2', 'review', 0,
                     'Pending Preview', 'Odoo RPC timeout'),
                    ('103', 'ext-103', 'A-103', 'BRAND', 'Part', 'universal',
                     'test_catalog', 'v1', 'hash3', 'approved', 1,
                     'Locked Preview', NULL)
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

    yield client

    app.dependency_overrides.clear()


def test_catalog_search_matches_article(catalog_client: TestClient) -> None:
    response = catalog_client.get("/api/products", params={"search": "a-102"})
    assert response.status_code == 200
    data = response.json()
    assert data["total_count"] == 1
    assert data["items"][0]["article"] == "A-102"


def test_catalog_filter_has_error(catalog_client: TestClient) -> None:
    response = catalog_client.get("/api/products", params={"has_error": True})
    assert response.status_code == 200
    data = response.json()
    assert data["total_count"] == 1
    assert data["items"][0]["last_sync_error"] == "Odoo RPC timeout"


def test_catalog_filter_is_locked(catalog_client: TestClient) -> None:
    response = catalog_client.get("/api/products", params={"is_locked": True})
    assert response.status_code == 200
    data = response.json()
    assert data["total_count"] == 1
    assert data["items"][0]["name_locked"] is True


def test_catalog_filter_naming_status_synced(catalog_client: TestClient) -> None:
    response = catalog_client.get("/api/products", params={"naming_status": "synced"})
    assert response.status_code == 200
    data = response.json()
    assert data["total_count"] == 1
    assert data["items"][0]["article"] == "A-101"
