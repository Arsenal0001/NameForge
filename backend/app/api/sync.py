"""Odoo sync pipeline API (safe writes with dry-run guard)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.sync import SyncOdooRequest, SyncOdooResponse
from app.services.odoo_client import OdooClient, OdooClientError
from app.services.sync_service import SyncService

router = APIRouter(prefix="/sync", tags=["sync"])


@router.post("/odoo", response_model=SyncOdooResponse)
def post_sync_odoo(
    body: SyncOdooRequest,
    db: Session = Depends(get_db),
) -> SyncOdooResponse:
    """
    Push approved names to Odoo ``product.template`` (JSON-RPC ``write`` only).

    Respects ``DRY_RUN``, ``name_locked``, and ``source_hash`` idempotency.
    """
    try:
        client = OdooClient()
    except OdooClientError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    service = SyncService(db, client)
    return service.sync_products(body.product_ids)
