"""Tests for sync candidate selection (name_locked rows included)."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

_BACKEND = Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.services.sync_queue import is_sync_candidate  # noqa: E402


def _product(**kwargs: object) -> SimpleNamespace:
    defaults: dict[str, object] = {
        "id": 1,
        "name_locked": False,
        "generated_name": "Some Name",
        "odoo_product_id": "42",
        "synced_at": None,
        "generation_status": "review",
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_locked_product_is_sync_candidate_when_unsynced() -> None:
    product = _product(name_locked=True, synced_at=None)
    assert is_sync_candidate(product) is True


def test_locked_product_skipped_when_idempotent_synced() -> None:
    product = _product(
        name_locked=True,
        synced_at="2026-01-01T00:00:00+00:00",
        generation_status="approved",
    )
    assert is_sync_candidate(product) is False


def test_locked_product_in_review_is_sync_candidate() -> None:
    product = _product(
        name_locked=True,
        synced_at="2026-01-01T00:00:00+00:00",
        generation_status="review",
    )
    assert is_sync_candidate(product) is True
