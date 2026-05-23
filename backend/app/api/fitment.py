"""Product fitment save API (local DB + naming regeneration)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.product_fitment import (
    SaveProductFitmentBody,
    SaveProductFitmentResponse,
)
from app.services.fitment_service import (
    FitmentValidationError,
    ProductNotFoundError,
    save_product_vehicle_fitment,
)

router = APIRouter(prefix="/products", tags=["fitment"])


@router.post("/{product_id}/fitment", response_model=SaveProductFitmentResponse)
def post_product_fitment(
    product_id: int,
    body: SaveProductFitmentBody,
    db: Session = Depends(get_db),
) -> SaveProductFitmentResponse:
    """
    Save vehicle matrix selection for a product (local SQLite only).

    Updates ``product_fitments``, ``fitments``, denormalized ``products`` fields,
    then regenerates ``generated_name`` / ``search_keywords`` via TemplateEngine.
    """
    try:
        item = save_product_vehicle_fitment(
            db,
            product_id,
            make_id=body.make_id,
            model_id=body.model_id,
            generation_id=body.generation_id,
        )
    except ProductNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Товар не найден") from exc
    except FitmentValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return SaveProductFitmentResponse(product=item)
