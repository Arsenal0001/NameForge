"""Safety tests for SyncService (dry-run, name_locked, idempotency)."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

_BACKEND = Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.schemas.naming import GeneratedNamingResult  # noqa: E402
from app.services.sync_service import SyncService  # noqa: E402
from app.services.template_service import TemplateResolution  # noqa: E402


_HASH_OLD = "a" * 64
_HASH_NEW = "b" * 64


def _product(
    *,
    pid: int = 1,
    name_locked: bool = False,
    source_hash: str = _HASH_OLD,
    synced_at: str | None = None,
    generated_name: str = "Test Product Name",
    odoo_product_id: str = "42",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=pid,
        name_locked=name_locked,
        source_hash=source_hash,
        synced_at=synced_at,
        generated_name=generated_name,
        search_keywords="kw1",
        odoo_product_id=odoo_product_id,
    )


def _preview_result(*, source_hash: str = _HASH_NEW) -> GeneratedNamingResult:
    return GeneratedNamingResult(
        name="Preview Name",
        search_keywords="preview kw",
        description="",
        status="generated",
        source_hash=source_hash,
    )


def _resolution() -> TemplateResolution:
    return TemplateResolution(
        logical_matrix_id="car_mats",
        source_category_id=1,
        template_key="car_mats__universal",
        template_version="v1",
        name_pattern=None,
        has_category_template=True,
    )


@pytest.fixture
def mock_client() -> MagicMock:
    client = MagicMock()
    client.batch_write = MagicMock(return_value=[True])
    client.write = MagicMock(return_value=True)
    return client


@pytest.fixture
def mock_session() -> MagicMock:
    session = MagicMock()
    session.commit = MagicMock()
    session.rollback = MagicMock()
    session.add = MagicMock()
    return session


@patch("app.services.sync_service.merge_product_attributes_into_write_values")
@patch("app.services.sync_service.generate_preview_for_product")
def test_sync_dry_run_does_not_call_odoo(
    mock_preview: MagicMock,
    mock_attrs: MagicMock,
    mock_session: MagicMock,
    mock_client: MagicMock,
) -> None:
    product = _product()
    mock_session.query.return_value.filter.return_value.all.return_value = [product]
    mock_preview.return_value = (_preview_result(source_hash=_HASH_NEW), _resolution())

    service = SyncService(mock_session, mock_client, dry_run=True)
    result = service.sync_products([1])

    mock_client.batch_write.assert_not_called()
    mock_client.write.assert_not_called()
    assert result.dry_run is True
    assert result.pushed == 1
    assert result.log[0].action == "dry_run_would_push"


@patch("app.services.sync_service.generate_preview_for_product")
def test_sync_locked_product_uses_stored_name_without_preview(
    mock_preview: MagicMock,
    mock_session: MagicMock,
    mock_client: MagicMock,
) -> None:
    product = _product(
        name_locked=True,
        source_hash=_HASH_NEW,
        synced_at=None,
        generated_name="Manual Locked Name",
    )
    mock_session.query.return_value.filter.return_value.all.return_value = [product]

    service = SyncService(mock_session, mock_client, dry_run=False)
    result = service.sync_products([1])

    mock_preview.assert_not_called()
    mock_client.write.assert_called_once()
    assert result.pushed == 1
    assert result.skipped_locked == 0
    assert 1 in result.synced_product_ids


@patch("app.services.sync_service.generate_preview_for_product")
def test_sync_locked_idempotent_when_hash_unchanged_and_synced(
    mock_preview: MagicMock,
    mock_session: MagicMock,
    mock_client: MagicMock,
) -> None:
    product = _product(
        name_locked=True,
        source_hash=_HASH_OLD,
        synced_at="2026-01-01T00:00:00+00:00",
        generated_name="Manual Locked Name",
    )
    mock_session.query.return_value.filter.return_value.all.return_value = [product]

    service = SyncService(mock_session, mock_client, dry_run=False)
    result = service.sync_products([1])

    mock_preview.assert_not_called()
    mock_client.batch_write.assert_not_called()
    assert result.skipped_idempotent == 1
    assert result.pushed == 0


@patch("app.services.sync_service.generate_preview_for_product")
def test_sync_idempotent_skips_when_hash_unchanged_and_synced(
    mock_preview: MagicMock,
    mock_session: MagicMock,
    mock_client: MagicMock,
) -> None:
    product = _product(source_hash=_HASH_OLD, synced_at="2026-01-01T00:00:00+00:00")
    product.updated_at = "2025-12-31T00:00:00+00:00"
    mock_session.query.return_value.filter.return_value.all.return_value = [product]
    mock_preview.return_value = (
        _preview_result(source_hash=_HASH_OLD),
        _resolution(),
    )

    service = SyncService(mock_session, mock_client, dry_run=False)
    result = service.sync_products([1])

    mock_client.batch_write.assert_not_called()
    assert result.skipped_idempotent == 1
    assert result.pushed == 0


@patch("app.services.sync_service.generate_preview_for_product")
def test_sync_repushes_when_product_updated_after_last_sync(
    mock_preview: MagicMock,
    mock_session: MagicMock,
    mock_client: MagicMock,
) -> None:
    product = _product(source_hash=_HASH_OLD, synced_at="2026-01-01T00:00:00+00:00")
    product.updated_at = "2026-01-02T00:00:00+00:00"
    mock_session.query.return_value.filter.return_value.all.return_value = [product]
    mock_preview.return_value = (
        _preview_result(source_hash=_HASH_OLD),
        _resolution(),
    )

    service = SyncService(mock_session, mock_client, dry_run=False)
    result = service.sync_products([1])

    mock_client.write.assert_called_once()
    assert result.pushed == 1
    assert result.skipped_idempotent == 0


@patch("app.services.sync_service.merge_product_attributes_into_write_values")
@patch("app.services.sync_service.generate_preview_for_product")
def test_sync_live_calls_write_when_hash_changed(
    mock_preview: MagicMock,
    mock_attrs: MagicMock,
    mock_session: MagicMock,
    mock_client: MagicMock,
) -> None:
    product = _product(source_hash=_HASH_OLD, synced_at=None)
    product.last_sync_error = "previous failure"
    mock_session.query.return_value.filter.return_value.all.return_value = [product]
    mock_preview.return_value = (
        _preview_result(source_hash=_HASH_NEW),
        _resolution(),
    )

    service = SyncService(mock_session, mock_client, dry_run=False)
    result = service.sync_products([1])

    mock_client.write.assert_called_once()
    mock_attrs.assert_called_once()
    assert result.pushed == 1
    assert 1 in result.synced_product_ids
    assert product.last_sync_error is None
    mock_session.commit.assert_called()


@patch("app.services.sync_service.generate_preview_for_product")
def test_sync_persists_last_sync_error_on_odoo_failure(
    mock_preview: MagicMock,
    mock_session: MagicMock,
    mock_client: MagicMock,
) -> None:
    from app.services.odoo_client import OdooClientError

    product = _product(source_hash=_HASH_OLD, synced_at=None)
    product.last_sync_error = None
    mock_session.query.return_value.filter.return_value.all.return_value = [product]
    mock_session.get.return_value = product
    mock_preview.return_value = (
        _preview_result(source_hash=_HASH_NEW),
        _resolution(),
    )
    mock_client.batch_write.side_effect = OdooClientError("RPC denied")
    mock_client.write.side_effect = OdooClientError("RPC denied")

    service = SyncService(mock_session, mock_client, dry_run=False)
    result = service.sync_products([1])

    assert result.errors == 1
    assert product.last_sync_error == "RPC denied"
    mock_client.write.assert_called_once()
    mock_session.commit.assert_called()


@patch("app.services.sync_service.generate_preview_for_product")
def test_sync_continues_after_single_write_failure(
    mock_preview: MagicMock,
    mock_session: MagicMock,
    mock_client: MagicMock,
) -> None:
    from app.services.odoo_client import OdooClientError

    first = _product(pid=1, source_hash=_HASH_OLD, synced_at=None, odoo_product_id="10")
    second = _product(pid=2, source_hash=_HASH_OLD, synced_at=None, odoo_product_id="11")
    mock_session.query.return_value.filter.return_value.all.return_value = [first, second]
    mock_session.get.side_effect = lambda _model, pid: first if pid == 1 else second
    mock_preview.return_value = (_preview_result(source_hash=_HASH_NEW), _resolution())

    def write_side_effect(model, ids, values):
        if ids == [10]:
            raise OdooClientError("first failed")
        return True

    mock_client.write.side_effect = write_side_effect

    service = SyncService(mock_session, mock_client, dry_run=False)
    result = service.sync_products([1, 2])

    assert mock_client.write.call_count == 2
    assert result.pushed == 1
    assert result.errors == 1
    assert 2 in result.synced_product_ids
    assert first.last_sync_error == "first failed"
