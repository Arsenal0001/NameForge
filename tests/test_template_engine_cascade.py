"""Unit tests for TemplateEngine category cascade."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.services.template_service import (  # noqa: E402
    CategoryCacheEntry,
    TemplateEngine,
    compute_naming_status,
)


@pytest.fixture
def engine() -> TemplateEngine:
    return TemplateEngine()


def test_cascade_inherits_template_from_parent(engine: TemplateEngine) -> None:
    engine.load_from_entries(
        [
            CategoryCacheEntry(
                odoo_id=1,
                name="Автотовары",
                parent_id=None,
                complete_name="Автотовары",
                naming_template_key="car_mats",
            ),
            CategoryCacheEntry(
                odoo_id=2,
                name="Коврики",
                parent_id=1,
                complete_name="Автотовары / Коврики",
                naming_template_key=None,
            ),
        ]
    )

    matrix_id, source_cat = engine.resolve_matrix_from_category(2)

    assert matrix_id == "car_mats"
    assert source_cat == 1


def test_cascade_prefers_nearest_category_with_template(engine: TemplateEngine) -> None:
    engine.load_from_entries(
        [
            CategoryCacheEntry(
                odoo_id=10,
                name="Root",
                parent_id=None,
                complete_name="Root",
                naming_template_key="universal",
            ),
            CategoryCacheEntry(
                odoo_id=11,
                name="Mid",
                parent_id=10,
                complete_name="Root / Mid",
                naming_template_key=None,
            ),
            CategoryCacheEntry(
                odoo_id=12,
                name="Leaf",
                parent_id=11,
                complete_name="Root / Mid / Leaf",
                naming_template_key="bulbs_led",
            ),
        ]
    )

    matrix_id, source_cat = engine.resolve_matrix_from_category(12)

    assert matrix_id == "bulbs_led"
    assert source_cat == 12


def test_cascade_returns_none_when_no_bindings(engine: TemplateEngine) -> None:
    engine.load_from_entries(
        [
            CategoryCacheEntry(
                odoo_id=100,
                name="Empty",
                parent_id=None,
                complete_name="Empty",
                naming_template_key=None,
            ),
        ]
    )

    matrix_id, source_cat = engine.resolve_matrix_from_category(100)

    assert matrix_id is None
    assert source_cat is None


def test_compute_naming_status_matrix() -> None:
    assert (
        compute_naming_status(
            has_category_template=False,
            preview_name="A",
            odoo_name="B",
        )
        == "no_template"
    )
    assert (
        compute_naming_status(
            has_category_template=True,
            preview_name="Same",
            odoo_name="Same",
        )
        == "synced"
    )
    assert (
        compute_naming_status(
            has_category_template=True,
            preview_name="New name",
            odoo_name="Old name",
        )
        == "pending_sync"
    )
