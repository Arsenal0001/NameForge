"""Enrich catalog rows with live Odoo names and TemplateEngine previews."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.odoo_catalog_cache import OdooProductTemplate
from app.models.product import Product
from app.schemas.catalog_product import ProductCatalogItem
from app.services.odoo_client import OdooClient, OdooClientError
from app.services.template_service import (
    compute_naming_status,
    generate_preview_for_product,
    get_template_engine,
)

logger = logging.getLogger(__name__)


def _many2one_id(value: Any) -> int | None:
    if value in (None, False):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, (list, tuple)) and value:
        try:
            return int(value[0])
        except (TypeError, ValueError):
            return None
    return None


def _odoo_name_from_row(row: dict[str, Any] | None) -> str:
    if not row:
        return ""
    return str(row.get("name") or "").strip()


def fetch_odoo_templates_map(
    session: Session,
    odoo_ids: list[int],
) -> dict[int, dict[str, Any]]:
    """
    Read ``product.template`` batch from Odoo; fall back to local cache on failure.
    """
    ids = sorted({int(i) for i in odoo_ids if i})
    if not ids:
        return {}

    live: dict[int, dict[str, Any]] = {}
    try:
        client = OdooClient()
        rows = client.read_product_templates_by_ids(ids)
        for row in rows:
            try:
                live[int(row["id"])] = row
            except (KeyError, TypeError, ValueError):
                continue
    except OdooClientError as exc:
        logger.warning("Odoo batch read failed, using cache: %s", exc)

    if len(live) >= len(ids):
        return live

    cached = session.scalars(
        select(OdooProductTemplate).where(OdooProductTemplate.odoo_id.in_(ids))
    ).all()
    for tpl in cached:
        if tpl.odoo_id not in live:
            live[tpl.odoo_id] = {
                "id": tpl.odoo_id,
                "name": tpl.name,
                "default_code": tpl.default_code,
                "categ_id": tpl.categ_id,
            }
    return live


def build_catalog_item(
    session: Session,
    product: Product,
    *,
    odoo_row: dict[str, Any] | None = None,
) -> ProductCatalogItem:
    """Map one ``Product`` to an enriched grid DTO."""
    engine = get_template_engine()
    engine.ensure_loaded(session)

    odoo_name = _odoo_name_from_row(odoo_row)
    categ_id = _many2one_id(odoo_row.get("categ_id") if odoo_row else None)

    preview_result, resolution = generate_preview_for_product(
        session,
        product,
        engine=engine,
        categ_id=categ_id,
    )
    preview_name = (preview_result.name if preview_result else "").strip()
    if product.name_locked:
        locked_name = (product.generated_name or "").strip()
        if locked_name:
            preview_name = locked_name
    preview_keywords = (
        (preview_result.search_keywords if preview_result else "") or ""
    ).strip()

    naming_status = compute_naming_status(
        has_category_template=resolution.has_category_template,
        preview_name=preview_name,
        odoo_name=odoo_name,
    )

    stored_name = (product.generated_name or "").strip()
    category = (product.product_folder or "").strip()

    return ProductCatalogItem(
        id=product.id,
        article=product.article or "",
        odoo_name=odoo_name,
        name=stored_name or odoo_name,
        preview_name=preview_name,
        naming_status=naming_status,
        category=category,
        part_type=(product.part_type or "").strip(),
        applicability_type=(product.applicability_type or "universal").strip(),
        brand=product.brand or "",
        primary_make=(product.primary_make or "").strip(),
        primary_model=(product.primary_model or "").strip(),
        fitment_summary=(product.fitment_summary or "").strip(),
        name_locked=bool(product.name_locked),
        category_template_bound=resolution.has_category_template,
        search_keywords=preview_keywords or (product.search_keywords or "").strip(),
        last_sync_error=(product.last_sync_error or "").strip() or None,
    )


def enrich_catalog_items(
    session: Session,
    products: list[Product],
) -> list[ProductCatalogItem]:
    """Build enriched catalog rows for one paginated page."""
    odoo_ids: list[int] = []
    for product in products:
        raw = (product.odoo_product_id or "").strip()
        if raw.isdigit():
            odoo_ids.append(int(raw))

    odoo_map = fetch_odoo_templates_map(session, odoo_ids)

    items: list[ProductCatalogItem] = []
    for product in products:
        odoo_row: dict[str, Any] | None = None
        raw = (product.odoo_product_id or "").strip()
        if raw.isdigit():
            odoo_row = odoo_map.get(int(raw))
        items.append(build_catalog_item(session, product, odoo_row=odoo_row))
    return items
