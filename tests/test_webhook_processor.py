"""Tests for webhook background processor."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

_BACKEND = Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.schemas.naming import GeneratedNamingResult  # noqa: E402
from app.schemas.sync import SyncOdooResponse  # noqa: E402
from app.schemas.webhook import OdooProductWebhookPayload  # noqa: E402
from app.services.webhook_processor import process_product_webhook_async  # noqa: E402


def _preview() -> GeneratedNamingResult:
    return GeneratedNamingResult(
        name="Generated Name",
        search_keywords="kw",
        description="",
        status="generated",
        source_hash="c" * 64,
    )


@patch("app.services.webhook_processor.SyncService")
@patch("app.services.webhook_processor.persist_generation_result", return_value=True)
@patch("app.services.webhook_processor.generate_preview_for_product")
@patch("app.services.webhook_processor.get_template_engine")
@patch("app.services.webhook_processor.OdooClient")
@patch("app.services.webhook_processor.SessionLocal")
def test_webhook_processor_respects_dry_run_via_sync_service(
    mock_session_local: MagicMock,
    mock_odoo_client_cls: MagicMock,
    mock_engine: MagicMock,
    mock_preview: MagicMock,
    mock_persist: MagicMock,
    mock_sync_cls: MagicMock,
) -> None:
    session = MagicMock()
    mock_session_local.return_value = session

    product = SimpleNamespace(
        id=7,
        name_locked=False,
        odoo_product_id="123",
    )
    session.scalar.return_value = product

    odoo = MagicMock()
    odoo.read_product_templates_by_ids.return_value = [
        {"id": 123, "name": "Old", "default_code": "ART-01", "categ_id": [10, "Cat"]}
    ]
    mock_odoo_client_cls.return_value = odoo

    mock_preview.return_value = (_preview(), SimpleNamespace())
    sync_instance = MagicMock()
    sync_instance.sync_products.return_value = SyncOdooResponse(
        dry_run=True,
        total=1,
        pushed=1,
        skipped_locked=0,
        skipped_idempotent=0,
        skipped_invalid=0,
        errors=0,
        synced_product_ids=[7],
        log=[],
    )
    mock_sync_cls.return_value = sync_instance

    process_product_webhook_async(
        OdooProductWebhookPayload(product_id=123, default_code="ART-01")
    )

    mock_sync_cls.assert_called_once()
    assert mock_sync_cls.call_args.kwargs.get("dry_run") is None
    sync_instance.sync_products.assert_called_once_with([7])
    session.commit.assert_called()
    session.close.assert_called_once()


@patch("app.services.webhook_processor.OdooClient")
@patch("app.services.webhook_processor.SessionLocal")
def test_webhook_processor_skips_name_locked(
    mock_session_local: MagicMock,
    mock_odoo_client_cls: MagicMock,
) -> None:
    session = MagicMock()
    mock_session_local.return_value = session
    mock_odoo_client_cls.return_value = MagicMock(
        read_product_templates_by_ids=MagicMock(
            return_value=[{"id": 5, "default_code": "X", "categ_id": False}]
        )
    )

    session.scalar.return_value = SimpleNamespace(id=1, name_locked=True)

    with patch("app.services.webhook_processor.generate_preview_for_product") as mock_preview:
        process_product_webhook_async(OdooProductWebhookPayload(product_id=5))
        mock_preview.assert_not_called()

    session.close.assert_called_once()
