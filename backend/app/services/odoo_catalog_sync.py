"""
Pull Odoo catalog into SQLite/Postgres cache tables (see ``models/odoo_catalog_cache.py``).

Uses chunked ``search_read`` to stay within proxy timeouts (see ``odoo_api_knowledge.md``).
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.odoo_catalog_cache import (
    OdooCategory,
    OdooProductAttribute,
    OdooProductAttributeValue,
    OdooProductTemplate,
)
from app.models.product import Product
from app.services.odoo_client import OdooClient, OdooClientError

logger = logging.getLogger(__name__)


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


def _text_or_none(value: Any) -> str | None:
    if value in (None, False):
        return None
    s = str(value).strip()
    return s or None


def _int_list(value: Any) -> list[int]:
    if not value or not isinstance(value, (list, tuple)):
        return []
    out: list[int] = []
    for item in value:
        try:
            out.append(int(item))
        except (TypeError, ValueError):
            continue
    return out


def write_product_template_name(
    client: OdooClient, odoo_template_id: int, name: str
) -> Any:
    """
    Push ``product.template`` name to Odoo.

    Caller must enforce local business rules (e.g. ``Product.name_locked`` in SQLite).
    """
    name = name.strip()
    if not name:
        raise OdooClientError("Refusing to write empty product.template name")
    return client.write("product.template", [odoo_template_id], {"name": name})


def push_products_to_odoo(
    session: Session,
    client: OdooClient,
    product_ids: list[int],
    *,
    chunk_size: int = 50,
) -> dict[str, int]:
    """
    Push generated names and search keywords for selected products to Odoo 19.
    
    Uses batch JSON-RPC calls to minimize HTTP overhead.
    """
    stats = {"total": len(product_ids), "pushed": 0, "skipped": 0, "errors": 0}
    
    # Load products from local DB
    products = session.query(Product).filter(Product.id.in_(product_ids)).all()
    
    updates_to_send = []
    for p in products:
        # Basic validation: must have a generated name and Odoo ID
        name = (p.generated_name or "").strip()
        if not name or not p.odoo_product_id:
            logger.warning("Skip Odoo push for product id=%s: missing name or Odoo ID", p.id)
            stats["skipped"] += 1
            continue
            
        try:
            odoo_id = int(p.odoo_product_id)
        except (ValueError, TypeError):
            logger.warning("Skip Odoo push for product id=%s: invalid Odoo ID %r", p.id, p.odoo_product_id)
            stats["skipped"] += 1
            continue

        values = {
            "name": name,
            "x_search_keywords": (p.search_keywords or "").strip(),
        }
        updates_to_send.append(([odoo_id], values))

    # Process in chunks using batch_write
    for i in range(0, len(updates_to_send), chunk_size):
        chunk = updates_to_send[i : i + chunk_size]
        try:
            client.batch_write("product.template", chunk)
            stats["pushed"] += len(chunk)
            
            # Update synced_at in local DB
            now = utc_iso_timestamp()
            chunk_product_ids = [p.id for p in products if any(int(p.odoo_product_id) == u[0][0] for u in chunk if p.odoo_product_id)]
            session.query(Product).filter(Product.id.in_(chunk_product_ids)).update({"synced_at": now}, synchronize_session=False)
            session.commit()
        except Exception as exc:
            logger.error("Failed to push chunk to Odoo: %s", exc)
            stats["errors"] += len(chunk)
            session.rollback()

    return stats


def sync_odoo_catalog(
    session: Session,
    client: OdooClient,
    *,
    chunk_size: int = 200,
) -> dict[str, int]:
    """
    Full catalog refresh: categories → attributes → attribute values → templates.

    Commits after each chunk to limit transaction size.
    """
    if chunk_size < 1:
        raise ValueError("chunk_size must be >= 1")

    stats: dict[str, int] = {}
    stats["odoo_categories"] = _sync_categories(session, client, chunk_size=chunk_size)
    stats["odoo_product_attributes"] = _sync_product_attributes(
        session, client, chunk_size=chunk_size
    )
    stats["odoo_product_attribute_values"] = _sync_attribute_values(
        session, client, chunk_size=chunk_size
    )
    stats["odoo_product_templates"] = _sync_product_templates(
        session, client, chunk_size=chunk_size
    )
    return stats


def _sync_categories(
    session: Session, client: OdooClient, *, chunk_size: int
) -> int:
    fields = ["id", "name", "parent_id", "complete_name"]
    total = 0
    offset = 0
    synced_at = utc_iso_timestamp()
    while True:
        rows = client.search_read(
            "product.category",
            [],
            fields,
            limit=chunk_size,
            offset=offset,
            order="id",
        )
        if not rows:
            break
        for row in rows:
            oid = int(row["id"])
            obj = session.get(OdooCategory, oid)
            if obj is None:
                obj = OdooCategory(odoo_id=oid)
                session.add(obj)
            obj.name = str(row.get("name") or "")
            obj.parent_id = _many2one_id(row.get("parent_id"))
            obj.complete_name = _text_or_none(row.get("complete_name"))
            obj.synced_at = synced_at
            total += 1
        session.commit()
        logger.info("Synced %s product.category rows (offset=%s)", len(rows), offset)
        offset += len(rows)
    return total


def _sync_product_attributes(
    session: Session, client: OdooClient, *, chunk_size: int
) -> int:
    fields = ["id", "name", "display_type", "create_variant"]
    total = 0
    offset = 0
    synced_at = utc_iso_timestamp()
    while True:
        rows = client.search_read(
            "product.attribute",
            [],
            fields,
            limit=chunk_size,
            offset=offset,
            order="id",
        )
        if not rows:
            break
        for row in rows:
            oid = int(row["id"])
            obj = session.get(OdooProductAttribute, oid)
            if obj is None:
                obj = OdooProductAttribute(odoo_id=oid)
                session.add(obj)
            obj.name = str(row.get("name") or "")
            dt = row.get("display_type")
            obj.display_type = _text_or_none(dt)
            cv = row.get("create_variant")
            obj.create_variant = _text_or_none(cv)
            obj.synced_at = synced_at
            total += 1
        session.commit()
        logger.info("Synced %s product.attribute rows (offset=%s)", len(rows), offset)
        offset += len(rows)
    return total


def _sync_attribute_values(
    session: Session, client: OdooClient, *, chunk_size: int
) -> int:
    fields = ["id", "name", "attribute_id"]
    total = 0
    offset = 0
    synced_at = utc_iso_timestamp()
    while True:
        rows = client.search_read(
            "product.attribute.value",
            [],
            fields,
            limit=chunk_size,
            offset=offset,
            order="id",
        )
        if not rows:
            break
        for row in rows:
            aid = _many2one_id(row.get("attribute_id"))
            if aid is None:
                logger.warning(
                    "Skipping product.attribute.value id=%s without attribute_id",
                    row.get("id"),
                )
                continue
            oid = int(row["id"])
            obj = session.get(OdooProductAttributeValue, oid)
            if obj is None:
                obj = OdooProductAttributeValue(odoo_id=oid)
                session.add(obj)
            obj.attribute_id = aid
            obj.name = str(row.get("name") or "")
            obj.synced_at = synced_at
            total += 1
        session.commit()
        logger.info(
            "Synced %s product.attribute.value rows (offset=%s)", len(rows), offset
        )
        offset += len(rows)
    return total


def _sync_product_templates(
    session: Session, client: OdooClient, *, chunk_size: int
) -> int:
    fields = ["id", "name", "default_code", "categ_id", "attribute_line_ids"]
    total = 0
    offset = 0
    synced_at = utc_iso_timestamp()
    while True:
        rows = client.search_read(
            "product.template",
            [],
            fields,
            limit=chunk_size,
            offset=offset,
            order="id",
        )
        if not rows:
            break
        for row in rows:
            oid = int(row["id"])
            obj = session.get(OdooProductTemplate, oid)
            if obj is None:
                obj = OdooProductTemplate(odoo_id=oid)
                session.add(obj)
            obj.name = str(row.get("name") or "")
            obj.default_code = _text_or_none(row.get("default_code"))
            obj.categ_id = _many2one_id(row.get("categ_id"))
            lines = _int_list(row.get("attribute_line_ids"))
            obj.attribute_line_ids_json = json.dumps(lines)
            obj.synced_at = synced_at
            total += 1
        session.commit()
        logger.info("Synced %s product.template rows (offset=%s)", len(rows), offset)
        offset += len(rows)
    return total
