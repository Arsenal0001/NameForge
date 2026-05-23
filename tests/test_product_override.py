"""Tests for PATCH /api/products/{product_id}/override."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
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
from app.models.product import Product  # noqa: E402
from main import app  # noqa: E402


@pytest.fixture
def override_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "override_test.db"
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
                VALUES ('test_override', 'v1', 'universal', '{part_type} {brand}')
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO products (
                    ms_product_id, external_code, article, brand, part_type,
                    applicability_type, template_key, template_version,
                    source_hash, generation_status, name_locked, generated_name
                )
                VALUES (
                    '9001', 'ext-9001', 'SKU-9001', 'BOSCH', 'Filter', 'universal',
                    'test_override', 'v1', 'oldhash', 'approved', 0,
                    'Auto Generated Name'
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

    yield client, session_factory

    app.dependency_overrides.clear()


def test_manual_override_locks_and_writes_name(
    override_client: tuple[TestClient, sessionmaker],
) -> None:
    client, session_factory = override_client

    response = client.patch(
        "/api/products/1/override",
        json={"is_locked": True, "manual_name": "Manual Edge Case Name"},
    )

    assert response.status_code == 200
    data = response.json()["product"]
    assert data["name_locked"] is True
    assert data["preview_name"] == "Manual Edge Case Name"
    assert data["last_sync_error"] is None

    with session_factory() as session:
        product = session.scalar(select(Product).where(Product.id == 1))
        assert product is not None
        assert product.name_locked is True
        assert product.generated_name == "Manual Edge Case Name"
        assert product.source_hash != "oldhash"
        assert product.generation_status == "review"
        assert product.last_sync_error is None
