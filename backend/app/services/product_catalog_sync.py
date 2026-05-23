"""Pull Odoo ``product.template`` rows into local ``products`` (PIM cache)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.odoo_catalog_cache import OdooCategory
from app.models.product import Product
from app.models.template import Template
from app.services.odoo_client import OdooClient

logger = logging.getLogger(__name__)

DEFAULT_TEMPLATE_KEY = "universal_base"
DEFAULT_TEMPLATE_VERSION = "v1"
DEFAULT_APPLICABILITY = "universal"
DEFAULT_BRAND = "UNKNOWN"
DEFAULT_PART_TYPE = "Товар"

READ_FIELDS = ["id", "name", "default_code", "categ_id", "active"]


def utc_iso_timestamp() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


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


def _text(value: Any) -> str:
    if value in (None, False):
        return ""
    return str(value).strip()


def _default_code(row: dict[str, Any]) -> str:
    code = _text(row.get("default_code"))
    if code:
        return code
    return f"odoo-{int(row['id'])}"


def ensure_odoo_import_templates(session: Session) -> None:
    """Ensure baseline templates referenced by imported products exist."""
    now = utc_iso_timestamp()
    seeds = (
        (DEFAULT_TEMPLATE_KEY, DEFAULT_APPLICABILITY, "{part_type} {brand}"),
        ("fitment_base", "fitment", "{part_type} {brand} для {make} {model}"),
    )
    for template_key, applicability_type, name_pattern in seeds:
        exists = session.scalar(
            select(Template.id).where(
                Template.template_key == template_key,
                Template.version == DEFAULT_TEMPLATE_VERSION,
            )
        )
        if exists is not None:
            continue
        session.add(
            Template(
                template_key=template_key,
                version=DEFAULT_TEMPLATE_VERSION,
                applicability_type=applicability_type,
                name_pattern=name_pattern,
                is_active=True,
                created_at=now,
                updated_at=now,
                part_type_pattern=None,
                part_type_trigger=None,
            )
        )
    session.commit()


def _load_category_labels(session: Session) -> dict[int, str]:
    rows = session.scalars(select(OdooCategory)).all()
    labels: dict[int, str] = {}
    for row in rows:
        label = (row.complete_name or row.name or "").strip()
        if label:
            labels[row.odoo_id] = label
    return labels


def _resolve_part_type(categ_id: int | None, category_labels: dict[int, str]) -> str:
    if categ_id is None:
        return DEFAULT_PART_TYPE
    label = category_labels.get(categ_id, "")
    if not label:
        return DEFAULT_PART_TYPE
    if " / " in label:
        return label.rsplit(" / ", 1)[-1].strip() or DEFAULT_PART_TYPE
    return label


def count_odoo_product_templates(
    client: OdooClient,
    *,
    include_inactive: bool = False,
) -> int:
    domain: list[Any] = []
    if not include_inactive:
        domain = [("active", "=", True)]
    result = client.call("product.template", "search_count", [domain])
    return int(result or 0)


def sync_products_from_odoo(
    session: Session,
    client: OdooClient,
    *,
    chunk_size: int = 500,
    include_inactive: bool = False,
    on_progress: Callable[[int, int], None] | None = None,
) -> dict[str, int]:
    """
    Upsert Odoo templates into local ``products`` keyed by ``odoo_product_id``.

    Commits after each chunk. Existing operator fields (``generated_name``,
    fitments, ``name_locked``) are preserved on update.
    """
    if chunk_size < 1:
        raise ValueError("chunk_size must be >= 1")

    ensure_odoo_import_templates(session)
    category_labels = _load_category_labels(session)

    domain: list[Any] = []
    if not include_inactive:
        domain = [("active", "=", True)]

    total = count_odoo_product_templates(client, include_inactive=include_inactive)
    offset = 0
    processed = 0
    inserted = 0
    updated = 0
    skipped_inactive = 0

    while True:
        rows = client.search_read(
            "product.template",
            domain,
            READ_FIELDS,
            limit=chunk_size,
            offset=offset,
            order="id",
        )
        if not rows:
            break

        now = utc_iso_timestamp()
        for row in rows:
            if not include_inactive and not row.get("active", True):
                skipped_inactive += 1
                continue

            odoo_id = int(row["id"])
            odoo_key = str(odoo_id)
            code = _default_code(row)
            categ_id = _many2one_id(row.get("categ_id"))
            category_label = category_labels.get(categ_id, "") if categ_id else ""
            odoo_name = _text(row.get("name"))

            product = session.scalar(
                select(Product).where(Product.odoo_product_id == odoo_key)
            )
            if product is None:
                code_owner = session.scalar(
                    select(Product.id).where(
                        Product.external_code == code,
                        Product.odoo_product_id != odoo_key,
                    )
                )
                if code_owner is not None:
                    code = f"{code}-odoo-{odoo_id}"

                product = Product(
                    odoo_product_id=odoo_key,
                    external_code=code,
                    article=code,
                    brand=DEFAULT_BRAND,
                    part_type=_resolve_part_type(categ_id, category_labels),
                    applicability_type=DEFAULT_APPLICABILITY,
                    template_key=DEFAULT_TEMPLATE_KEY,
                    template_version=DEFAULT_TEMPLATE_VERSION,
                    generation_status="new",
                    name_locked=False,
                    source_hash="",
                    created_at=now,
                    updated_at=now,
                )
                session.add(product)
                inserted += 1
            else:
                updated += 1

            product.external_code = code
            product.article = code
            product.supplier_raw_name = odoo_name or product.supplier_raw_name
            product.product_folder = category_label or product.product_folder
            if product.part_type in ("", DEFAULT_PART_TYPE):
                product.part_type = _resolve_part_type(categ_id, category_labels)
            product.updated_at = now

            processed += 1
            if on_progress is not None:
                on_progress(processed, total)

        session.commit()
        logger.info(
            "Synced %s product.template rows (offset=%s, processed=%s)",
            len(rows),
            offset,
            processed,
        )
        offset += len(rows)

    return {
        "total_odoo": total,
        "processed": processed,
        "inserted": inserted,
        "updated": updated,
        "skipped_inactive": skipped_inactive,
    }
