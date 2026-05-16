"""Tests for product_workflow — preview status rules and approve safety."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.db import get_conn, init_db
from src.moysklad_client import MoySkladAPIError, MoySkladClient
from src.name_generator import GeneratedName
from src.product_workflow import (
    approve_and_sync_execute,
    batch_generate_previews,
    is_workflow_frozen,
    load_nf_attr_map,
    load_product_for_workflow,
    next_generation_status_after_preview,
    refresh_product_from_ms,
    unlock_name_next_status,
)


@pytest.fixture
def db(tmp_path: object, monkeypatch: pytest.MonkeyPatch):
    import src.db as db_module

    db_path = str(tmp_path / "wf.db")
    monkeypatch.setattr(db_module, "DB_PATH", db_path)
    load_nf_attr_map.cache_clear()
    init_db()
    yield db_module
    load_nf_attr_map.cache_clear()


def _directory_cache_brand_resolves() -> MagicMock:
    """Minimal resolved brand payload so approve path reaches ``update_product``."""
    dc = MagicMock()
    dc.resolve_brand = MagicMock(
        return_value={
            "meta": {
                "href": "https://api.moysklad.ru/remap/1.2/entity/some/brand-meta",
                "type": "customentity",
                "mediaType": "application/json",
            },
            "name": "BrandX",
        }
    )
    return dc


def _insert_product(conn, **kwargs: object) -> int:
    defaults: dict[str, object] = {
        "ms_product_id": "ms-wf-1",
        "external_code": "ext-wf-1",
        "article": "ART1",
        "brand": "BrandX",
        "part_type": "Фильтр",
        "applicability_type": "universal",
        "template_key": "universal_base",
        "template_version": "v1",
        "generation_status": "review",
        "name_locked": 0,
        "source_hash": "aaa",
    }
    defaults.update(kwargs)
    cur = conn.execute(
        """
        INSERT INTO products (
            ms_product_id, external_code, article, brand, part_type,
            applicability_type, template_key, template_version,
            generation_status, name_locked, source_hash
        ) VALUES (
            :ms_product_id, :external_code, :article, :brand, :part_type,
            :applicability_type, :template_key, :template_version,
            :generation_status, :name_locked, :source_hash
        )
        """,
        defaults,
    )
    return int(cur.lastrowid)


def test_next_generation_status_after_preview() -> None:
    gen_ok = GeneratedName(name="n", description="d", status="generated")
    gen_err = GeneratedName(name="", description="", status="error")
    assert next_generation_status_after_preview(gen_err, "h", "", frozen=False) == "error"
    assert next_generation_status_after_preview(gen_ok, "b", "a", frozen=False) == "review"
    assert next_generation_status_after_preview(gen_ok, "a", "a", frozen=False) is None
    assert next_generation_status_after_preview(gen_ok, "b", "a", frozen=True) is None


def test_unlock_name_next_status() -> None:
    assert unlock_name_next_status("") == "new"
    assert unlock_name_next_status("   ") == "new"
    assert unlock_name_next_status("abc") == "review"


def test_is_workflow_frozen() -> None:
    assert is_workflow_frozen({"name_locked": 1, "generation_status": "new"}) is True
    assert is_workflow_frozen({"name_locked": 0, "generation_status": "locked"}) is True
    assert is_workflow_frozen({"name_locked": 0, "generation_status": "review"}) is False


def test_approve_dry_run_leaves_db_unchanged(db: object) -> None:
    with get_conn() as conn:
        pid = _insert_product(conn)
    product = load_product_for_workflow(pid)
    assert product is not None

    client = MoySkladClient("token", "https://api.moysklad.ru/remap/1.2", dry_run=True)
    patch_mock = MagicMock()
    client.update_product = patch_mock

    code, detail = approve_and_sync_execute(
        client,
        product,
        "New Name",
        "newhash",
        "desc",
        dry_run=False,
    )
    assert code == "skipped"
    assert detail == "dry_run"
    patch_mock.assert_not_called()

    reloaded = load_product_for_workflow(pid)
    assert reloaded is not None
    assert str(reloaded["source_hash"]) == "aaa"
    assert str(reloaded["generation_status"]) == "review"


def test_approve_explicit_dry_run_flag(db: object) -> None:
    with get_conn() as conn:
        pid = _insert_product(conn)
    product = load_product_for_workflow(pid)
    assert product is not None
    client = MoySkladClient("token", "https://api.moysklad.ru/remap/1.2", dry_run=False)
    patch_mock = MagicMock(return_value={})
    client.update_product = patch_mock

    code, detail = approve_and_sync_execute(
        client,
        product,
        "New Name",
        "newhash",
        "",
        dry_run=True,
    )
    assert code == "skipped"
    assert detail == "dry_run"
    patch_mock.assert_not_called()


def test_batch_generate_previews_max_five_guard(db: object) -> None:
    with get_conn() as conn:
        ids = [
            _insert_product(
                conn,
                ms_product_id=f"ms-wf-{i}",
                external_code=f"ext-wf-{i}",
            )
            for i in range(6)
        ]
    with get_conn() as conn:
        with pytest.raises(ValueError, match="at most 5"):
            batch_generate_previews([str(i) for i in ids], conn)


def test_batch_generate_new_to_review_on_hash_change(db: object) -> None:
    with get_conn() as conn:
        pid = _insert_product(
            conn,
            generation_status="new",
            source_hash="",
            applicability_type="universal",
        )
    with get_conn() as conn:
        batch_generate_previews([str(pid)], conn)
    reloaded = load_product_for_workflow(pid)
    assert reloaded is not None
    assert str(reloaded["generation_status"]) == "review"
    assert str(reloaded.get("generated_name") or "") != ""


def test_refresh_skips_name_locked(db: object) -> None:
    with get_conn() as conn:
        _insert_product(
            conn,
            generation_status="new",
            name_locked=1,
            ms_product_id="ms-locked-1",
            source_hash="abc",
        )
    client = MagicMock()
    with get_conn() as conn:
        out = refresh_product_from_ms("ms-locked-1", client, load_nf_attr_map(), conn)
    assert out is not None
    assert int(out["name_locked"]) == 1
    client.get_product.assert_not_called()


def test_approve_no_change_skipped(db: object) -> None:
    with get_conn() as conn:
        pid = _insert_product(conn, source_hash="same")
    product = load_product_for_workflow(pid)
    client = MoySkladClient("t", "https://api.moysklad.ru/remap/1.2", dry_run=False)
    pm = MagicMock()
    client.update_product = pm
    code, detail = approve_and_sync_execute(
        client,
        product,
        "x",
        "same",
        "",
        dry_run=False,
    )
    assert code == "skipped"
    assert detail == "no_change"
    pm.assert_not_called()


def test_approve_moysklad_api_error_preserves_source_hash(db: object) -> None:
    with get_conn() as conn:
        pid = _insert_product(conn, source_hash="stable-hash-1")
    product = load_product_for_workflow(pid)
    client = MoySkladClient("t", "https://api.moysklad.ru/remap/1.2", dry_run=False)
    client.update_product = MagicMock(side_effect=MoySkladAPIError("MS down"))
    client.resolve_productfolder_for_put = MagicMock(return_value=None)

    code, detail = approve_and_sync_execute(
        client,
        product,
        "New Name",
        "new-hash-xyz",
        "",
        dry_run=False,
        directory_cache=_directory_cache_brand_resolves(),
    )
    assert code == "error"
    assert "MS" in (detail or "")

    reloaded = load_product_for_workflow(pid)
    assert reloaded is not None
    assert str(reloaded["source_hash"]) == "stable-hash-1"
    assert str(reloaded["generation_status"]) == "error"


def test_approve_name_locked_skips_update(db: object) -> None:
    with get_conn() as conn:
        pid = _insert_product(conn, name_locked=1, source_hash="old")
    product = load_product_for_workflow(pid)
    client = MoySkladClient("t", "https://api.moysklad.ru/remap/1.2", dry_run=False)
    pm = MagicMock()
    client.update_product = pm

    code, detail = approve_and_sync_execute(
        client,
        product,
        "Locked Name",
        "different-hash",
        "",
        dry_run=False,
    )
    assert code == "locked"
    assert detail == "name_locked"
    pm.assert_not_called()


def test_approve_unresolved_brand_skips_put_keeps_review(db: object) -> None:
    with get_conn() as conn:
        pid = _insert_product(conn, brand="ZebraUnknown", source_hash="aaa")
    product = load_product_for_workflow(pid)
    assert product is not None
    dc = MagicMock()
    dc.resolve_brand = MagicMock(return_value=None)
    client = MoySkladClient("t", "https://api.moysklad.ru/remap/1.2", dry_run=False)
    pm = MagicMock()
    client.update_product = pm
    code, detail = approve_and_sync_execute(
        client,
        product,
        "New Name",
        "newhash",
        "",
        dry_run=False,
        directory_cache=dc,
    )
    assert code == "error"
    assert detail == "brand_not_in_directory"
    pm.assert_not_called()
    reloaded = load_product_for_workflow(pid)
    assert reloaded is not None
    assert str(reloaded["generation_status"]) == "review"
    assert "Brand not found in MS Directory" in str(reloaded.get("error_message") or "")


def test_approve_brand_missing_directory_cache_skips_put(db: object) -> None:
    with get_conn() as conn:
        pid = _insert_product(conn, brand="NeedBrand", source_hash="aaa")
    product = load_product_for_workflow(pid)
    assert product is not None
    client = MoySkladClient("t", "https://api.moysklad.ru/remap/1.2", dry_run=False)
    pm = MagicMock()
    client.update_product = pm
    code, detail = approve_and_sync_execute(
        client,
        product,
        "New Name",
        "newhash",
        "",
        dry_run=False,
        directory_cache=None,
    )
    assert code == "error"
    assert detail == "brand_not_in_directory"
    pm.assert_not_called()


def test_approve_non_brand_skips_directory_guard(db: object) -> None:
    with get_conn() as conn:
        pid = _insert_product(conn, brand="NON", source_hash="aaa")
    product = load_product_for_workflow(pid)
    assert product is not None
    dc = MagicMock()
    client = MoySkladClient("t", "https://api.moysklad.ru/remap/1.2", dry_run=False)
    pm = MagicMock(return_value={})
    client.update_product = pm
    client.resolve_productfolder_for_put = MagicMock(return_value=None)
    code, detail = approve_and_sync_execute(
        client,
        product,
        "New Name",
        "newhash",
        "",
        dry_run=False,
        directory_cache=dc,
    )
    assert code == "ok"
    pm.assert_called_once()


def test_approve_success_persists_generated_name_and_synced_at(db: object) -> None:
    with get_conn() as conn:
        pid = _insert_product(conn, source_hash="oldhash")
    product = load_product_for_workflow(pid)
    assert product is not None

    client = MoySkladClient("token", "https://api.moysklad.ru/remap/1.2", dry_run=False)
    patch_mock = MagicMock(return_value={})
    client.update_product = patch_mock
    client.resolve_productfolder_for_put = MagicMock(return_value=None)

    code, detail = approve_and_sync_execute(
        client,
        product,
        "Approved NF Name",
        "newhashzz",
        "Описание",
        dry_run=False,
        directory_cache=_directory_cache_brand_resolves(),
    )
    assert code == "ok"
    assert detail is None
    patch_mock.assert_called_once()

    reloaded = load_product_for_workflow(pid)
    assert reloaded is not None
    assert str(reloaded["generation_status"]) == "approved"
    assert str(reloaded["source_hash"]) == "newhashzz"
    assert str(reloaded.get("generated_name") or "") == "Approved NF Name"
    assert str(reloaded.get("synced_at") or "")
    assert reloaded.get("error_message") in (None, "")
