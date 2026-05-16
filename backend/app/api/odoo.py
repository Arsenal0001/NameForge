from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal, get_db
from app.models.odoo_catalog_cache import (
    OdooCategory,
    OdooProductAttribute,
    OdooProductAttributeValue,
    OdooProductTemplate,
)
from app.schemas.odoo import (
    OdooCacheStatsResponse,
    OdooPingResponse,
    OdooPushRequest,
    OdooPushResponse,
    OdooSyncQueuedResponse,
)
from app.services.odoo_catalog_sync import push_products_to_odoo, sync_odoo_catalog
from app.services.odoo_client import OdooClient, OdooClientError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["odoo"])


def _run_catalog_sync_job(chunk_size: int) -> None:
    try:
        client = OdooClient()
        with SessionLocal() as session:
            stats = sync_odoo_catalog(session, client, chunk_size=chunk_size)
            logger.info("Odoo catalog sync completed: %s", stats)
    except Exception:
        logger.exception("Odoo catalog sync failed")


@router.get("/ping", response_model=OdooPingResponse)
def odoo_ping() -> OdooPingResponse:
    """Verify JSON-RPC credentials against ``res.users.read``."""
    try:
        client = OdooClient()
    except OdooClientError as exc:
        return OdooPingResponse(ok=False, detail=str(exc))
    ok, msg = client.test_connection()
    if ok:
        return OdooPingResponse(ok=True, user=msg)
    return OdooPingResponse(ok=False, detail=msg)


@router.post("/sync/catalog", response_model=OdooSyncQueuedResponse)
def odoo_sync_catalog(
    background_tasks: BackgroundTasks,
    chunk_size: int = 200,
) -> OdooSyncQueuedResponse:
    """Queue a full Odoo → local DB catalog import (runs after the HTTP response)."""
    if chunk_size < 25 or chunk_size > 1000:
        raise HTTPException(
            status_code=400,
            detail="chunk_size must be between 25 and 1000",
        )
    try:
        OdooClient()
    except OdooClientError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    background_tasks.add_task(_run_catalog_sync_job, chunk_size)
    return OdooSyncQueuedResponse(status="queued")


@router.get("/cache/stats", response_model=OdooCacheStatsResponse)
def odoo_cache_stats(db: Session = Depends(get_db)) -> OdooCacheStatsResponse:
    """Row counts for cached Odoo tables."""
    cats = db.scalar(select(func.count()).select_from(OdooCategory)) or 0
    attrs = db.scalar(select(func.count()).select_from(OdooProductAttribute)) or 0
    vals = db.scalar(select(func.count()).select_from(OdooProductAttributeValue)) or 0
    tpls = db.scalar(select(func.count()).select_from(OdooProductTemplate)) or 0
    return OdooCacheStatsResponse(
        odoo_categories=int(cats),
        odoo_product_attributes=int(attrs),
        odoo_product_attribute_values=int(vals),
        odoo_product_templates=int(tpls),
    )


@router.post("/push", response_model=OdooPushResponse)
def odoo_push_products(
    body: OdooPushRequest,
    db: Session = Depends(get_db),
) -> OdooPushResponse:
    """
    Выгрузить сгенерированные имена и ключевые слова в Odoo 19.
    """
    try:
        client = OdooClient()
    except OdooClientError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    stats = push_products_to_odoo(db, client, body.product_ids)
    return OdooPushResponse(**stats)
