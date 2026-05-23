"""Manual name override (edge-case products outside Naming Engine templates)."""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.models.product import Product
from app.schemas.catalog_product import ProductCatalogItem
from app.services.catalog_enrichment import build_catalog_item
from app.services.odoo_catalog_sync import utc_iso_timestamp
from app.services.template_service import compute_sync_content_hash

logger = logging.getLogger(__name__)


class ProductNotFoundError(LookupError):
    def __init__(self, product_id: int) -> None:
        super().__init__(f"Product {product_id} not found")
        self.product_id = product_id


class ManualOverrideValidationError(ValueError):
    """Invalid manual override payload."""


def apply_product_manual_override(
    session: Session,
    product_id: int,
    *,
    manual_name: str | None = None,
    is_locked: bool | None = None,
) -> ProductCatalogItem:
    """
    Apply operator manual name lock / override.

    When locked with ``manual_name``, writes ``generated_name`` and recomputes
    ``source_hash`` so :class:`SyncService` can push the edited name to Odoo.
    """
    if manual_name is None and is_locked is None:
        raise ManualOverrideValidationError("At least one of manual_name or is_locked is required")

    product = session.get(Product, product_id)
    if product is None:
        raise ProductNotFoundError(product_id)

    mutated = False

    if is_locked is not None:
        product.name_locked = is_locked
        mutated = True

    if product.name_locked and manual_name is not None:
        name = manual_name.strip()
        if not name:
            raise ManualOverrideValidationError("manual_name cannot be empty when name is locked")
        keywords = (product.search_keywords or "").strip()
        product.generated_name = name
        product.source_hash = compute_sync_content_hash(name=name, search_keywords=keywords)
        product.generation_status = "review"
        product.last_sync_error = None
        product.error_message = None
        mutated = True
    elif is_locked is True and manual_name is None:
        name = (product.generated_name or "").strip()
        if not name:
            raise ManualOverrideValidationError(
                "Cannot lock without manual_name when generated_name is empty"
            )
        keywords = (product.search_keywords or "").strip()
        product.source_hash = compute_sync_content_hash(name=name, search_keywords=keywords)
        product.generation_status = "review"
        product.last_sync_error = None
        mutated = True

    if not mutated:
        raise ManualOverrideValidationError("No changes to apply")

    product.updated_at = utc_iso_timestamp()
    session.add(product)
    session.commit()
    session.refresh(product)

    logger.info(
        "Manual override product_id=%s name_locked=%s generated_name=%r",
        product_id,
        product.name_locked,
        (product.generated_name or "")[:80],
    )
    return build_catalog_item(session, product, odoo_row=None)
