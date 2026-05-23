"""Helpers for selecting local products eligible for Odoo sync."""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.product import Product


def _has_generated_name(product: Product) -> bool:
    return bool((product.generated_name or "").strip())


def _has_numeric_odoo_id(product: Product) -> bool:
    return (product.odoo_product_id or "").strip().isdigit()


def is_sync_candidate(product: Product) -> bool:
    """
    Heuristic pre-filter aligned with :class:`SyncService` guards.

    Includes ``name_locked`` rows when they have a stored name pending push.
    ``SyncService`` still applies idempotent ``source_hash`` checks per product.
    """
    if not _has_generated_name(product):
        return False
    if not _has_numeric_odoo_id(product):
        return False

    status = (product.generation_status or "").strip().lower()
    if product.synced_at is None:
        return True
    if status == "review":
        return True
    return False


def collect_sync_candidate_ids(session: Session) -> list[int]:
    """Return local ``products.id`` values that likely need Odoo sync."""
    stmt = (
        select(Product)
        .where(Product.generated_name.isnot(None))
        .where(Product.generated_name != "")
        .where(
            or_(
                Product.synced_at.is_(None),
                Product.generation_status == "review",
            )
        )
        .order_by(Product.id.asc())
    )
    rows = session.scalars(stmt).all()
    return [p.id for p in rows if is_sync_candidate(p)]
