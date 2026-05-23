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
    OdooCategoriesSyncResponse,
    OdooPingResponse,
    OdooProductTemplateLookupResponse,
    OdooProductTemplatePreview,
    OdooPushRequest,
    OdooPushResponse,
    OdooSyncQueuedResponse,
)
from app.services.odoo_catalog_sync import (
    push_products_to_odoo,
    sync_odoo_catalog,
    sync_odoo_categories,
)
from app.services.odoo_client import OdooClient, OdooClientError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["odoo"])


def _optional_text(value: object) -> str | None:
    if value in (None, False):
        return None
    text = str(value).strip()
    return text or None


def _run_catalog_sync_job(chunk_size: int) -> None:
    try:
        client = OdooClient()
        with SessionLocal() as session:
            stats = sync_odoo_catalog(session, client, chunk_size=chunk_size)
            logger.info("Odoo catalog sync completed: %s", stats)
    except Exception:
        logger.exception("Odoo catalog sync failed")


@router.get("/product-template", response_model=OdooProductTemplateLookupResponse)
def odoo_product_template_by_code(
    default_code: str,
) -> OdooProductTemplateLookupResponse:
    """Read one ``product.template`` by ``default_code`` (connectivity smoke test)."""
    code = default_code.strip()
    if not code:
        raise HTTPException(status_code=400, detail="default_code is required")

    try:
        client = OdooClient()
    except OdooClientError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    try:
        row = client.get_product_template_by_default_code(code)
    except OdooClientError as exc:
        return OdooProductTemplateLookupResponse(
            ok=False,
            found=False,
            default_code=code,
            detail=str(exc),
        )

    if not row:
        return OdooProductTemplateLookupResponse(
            ok=True,
            found=False,
            default_code=code,
        )

    raw_code = row.get("default_code")
    template = OdooProductTemplatePreview(
        id=int(row["id"]),
        name=str(row.get("name") or ""),
        default_code=str(raw_code).strip() if raw_code not in (None, False) else None,
        categ_id=row.get("categ_id"),
        description_sale=_optional_text(row.get("description_sale")),
    )
    return OdooProductTemplateLookupResponse(
        ok=True,
        found=True,
        default_code=code,
        template=template,
    )


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


@router.post("/sync/categories", response_model=OdooCategoriesSyncResponse)
def odoo_sync_categories(
    db: Session = Depends(get_db),
    chunk_size: int = 200,
) -> OdooCategoriesSyncResponse:
    """
    Synchronous import of ``product.category`` into local ``odoo_categories`` cache.

    JSON-RPC ``search_read`` only. Existing ``name_pattern`` / ``naming_template_key``
    values are preserved on update.
    """
    if chunk_size < 25 or chunk_size > 1000:
        raise HTTPException(
            status_code=400,
            detail="chunk_size must be between 25 and 1000",
        )
    try:
        client = OdooClient()
    except OdooClientError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    try:
        stats = sync_odoo_categories(db, client, chunk_size=chunk_size)
    except OdooClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return OdooCategoriesSyncResponse(**stats)


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
