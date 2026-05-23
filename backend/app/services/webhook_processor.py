"""Background processing for Odoo product webhooks."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.product import Product
from app.schemas.webhook import OdooProductWebhookPayload
from app.services.odoo_client import OdooClient, OdooClientError
from app.services.sync_service import SyncService
from app.services.template_service import (
    generate_preview_for_product,
    get_template_engine,
    persist_generation_result,
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


def _resolve_local_product(
    session: Session, payload: OdooProductWebhookPayload
) -> Product | None:
    product = session.scalar(
        select(Product)
        .where(Product.odoo_product_id == str(payload.product_id))
        .limit(1)
    )
    if product is not None:
        return product

    code = (payload.default_code or "").strip()
    if not code:
        return None
    return session.scalar(
        select(Product).where(Product.article == code).limit(1)
    )


def process_product_webhook_async(payload: OdooProductWebhookPayload) -> None:
    """
    Fetch Odoo row, regenerate naming locally, push via :class:`SyncService`.

    Uses a dedicated SQLAlchemy session (safe for FastAPI ``BackgroundTasks``).
    """
    db = SessionLocal()
    try:
        client = OdooClient()
    except OdooClientError as exc:
        logger.error("Webhook: Odoo client unavailable: %s", exc)
        db.close()
        return

    try:
        get_template_engine().ensure_loaded(db)

        try:
            odoo_rows = client.read_product_templates_by_ids([payload.product_id])
        except OdooClientError as exc:
            logger.error(
                "Webhook: Odoo read failed for product_id=%s: %s",
                payload.product_id,
                exc,
            )
            return

        if not odoo_rows:
            logger.warning(
                "Webhook: Odoo product.template id=%s not found", payload.product_id
            )
            return

        odoo_row = odoo_rows[0]
        expected_code = (payload.default_code or "").strip()
        odoo_code = str(odoo_row.get("default_code") or "").strip()
        if expected_code and odoo_code and expected_code != odoo_code:
            logger.warning(
                "Webhook: default_code mismatch odoo_id=%s payload=%r odoo=%r",
                payload.product_id,
                expected_code,
                odoo_code,
            )

        product = _resolve_local_product(db, payload)
        if product is None:
            logger.warning(
                "Webhook: no local Product for odoo_id=%s default_code=%r",
                payload.product_id,
                payload.default_code,
            )
            return

        if product.name_locked:
            logger.info(
                "Webhook: skip auto-generation for name_locked product id=%s",
                product.id,
            )
        else:
            categ_id = _many2one_id(odoo_row.get("categ_id"))
            preview_result, _resolution = generate_preview_for_product(
                db, product, categ_id=categ_id
            )
            if preview_result is None:
                logger.warning(
                    "Webhook: naming preview unavailable for local product id=%s",
                    product.id,
                )
                return

            if persist_generation_result(db, product, preview_result):
                db.add(product)
                db.commit()

        sync_result = SyncService(db, client).sync_products([product.id])
        logger.info(
            "Webhook sync complete local_id=%s odoo_id=%s dry_run=%s pushed=%s "
            "skipped_locked=%s skipped_idempotent=%s errors=%s",
            product.id,
            payload.product_id,
            sync_result.dry_run,
            sync_result.pushed,
            sync_result.skipped_locked,
            sync_result.skipped_idempotent,
            sync_result.errors,
        )
    except Exception:
        db.rollback()
        logger.exception(
            "Webhook processing failed for odoo product_id=%s", payload.product_id
        )
    finally:
        db.close()
