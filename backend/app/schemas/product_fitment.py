"""API DTOs for saving product vehicle fitment."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.catalog_product import ProductCatalogItem


class SaveProductFitmentBody(BaseModel):
    make_id: int = Field(description="Vehicle make directory id.")
    model_id: int = Field(description="Vehicle model directory id.")
    generation_id: int = Field(description="Vehicle generation directory id.")


class SaveProductFitmentResponse(BaseModel):
    product: ProductCatalogItem = Field(
        description="Updated catalog row with fresh preview_name.",
    )
