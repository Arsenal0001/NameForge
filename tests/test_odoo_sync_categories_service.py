"""Unit tests for sync_odoo_categories upsert behaviour."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_BACKEND = Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.models.odoo_catalog_cache import OdooCategory  # noqa: E402
from app.services.odoo_catalog_sync import sync_odoo_categories  # noqa: E402


@pytest.fixture
def mock_session() -> MagicMock:
    session = MagicMock()
    session.get.return_value = None
    return session


def test_sync_categories_maps_parent_id_tuple(mock_session: MagicMock) -> None:
    client = MagicMock()
    client.search_read.side_effect = [
        [
            {
                "id": 10,
                "name": "Коврики",
                "parent_id": [5, "Салон"],
                "complete_name": "Аксессуары / Салон / Коврики",
            },
        ],
        [],
    ]

    with patch("app.services.odoo_catalog_sync.get_template_engine") as mock_engine:
        stats = sync_odoo_categories(mock_session, client, chunk_size=200)

    assert stats == {"inserted": 1, "updated": 0, "total": 1}
    added = mock_session.add.call_args[0][0]
    assert isinstance(added, OdooCategory)
    assert added.odoo_id == 10
    assert added.parent_id == 5
    assert added.name == "Коврики"
    mock_engine.return_value.invalidate_cache.assert_called_once()
    assert client.search_read.call_count == 2
    mock_session.commit.assert_called()


def test_sync_categories_preserves_existing_row_fields(mock_session: MagicMock) -> None:
    existing = OdooCategory(
        odoo_id=10,
        name="Old",
        parent_id=None,
        complete_name="Old path",
        naming_template_key="car_mats",
        name_pattern="{part_type} {brand}",
        synced_at="2020-01-01T00:00:00+00:00",
    )
    mock_session.get.return_value = existing

    client = MagicMock()
    client.search_read.side_effect = [
        [
            {
                "id": 10,
                "name": "Коврики",
                "parent_id": False,
                "complete_name": "Коврики",
            },
        ],
        [],
    ]

    with patch("app.services.odoo_catalog_sync.get_template_engine"):
        stats = sync_odoo_categories(mock_session, client, chunk_size=200)

    assert stats["updated"] == 1
    assert stats["inserted"] == 0
    assert existing.name_pattern == "{part_type} {brand}"
    assert existing.naming_template_key == "car_mats"
    mock_session.add.assert_not_called()
