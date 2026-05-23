"""Manual product name override API."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.product_override import (
    ProductManualOverrideBody,
    ProductManualOverrideResponse,
)
from app.services.product_override_service import (
    ManualOverrideValidationError,
    ProductNotFoundError,
    apply_product_manual_override,
)

router = APIRouter(prefix="/products", tags=["catalog"])


@router.patch("/{product_id}/override", response_model=ProductManualOverrideResponse)
def patch_product_manual_override(
    product_id: int,
    body: ProductManualOverrideBody,
    db: Session = Depends(get_db),
) -> ProductManualOverrideResponse:
    """Apply manual name lock / override for edge-case catalog rows."""
    try:
        item = apply_product_manual_override(
            db,
            product_id,
            manual_name=body.manual_name,
            is_locked=body.is_locked,
        )
    except ProductNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Товар не найден") from exc
    except ManualOverrideValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return ProductManualOverrideResponse(product=item)
