"""DTOs for manual product name override."""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from app.schemas.catalog_product import ProductCatalogItem


class ProductManualOverrideBody(BaseModel):
    manual_name: str | None = Field(
        default=None,
        max_length=255,
        description="Operator-fixed name written to generated_name when locked",
    )
    is_locked: bool | None = Field(
        default=None,
        description="Toggle manual name lock (blocks TemplateEngine auto-regeneration)",
    )

    @model_validator(mode="after")
    def require_at_least_one_field(self) -> ProductManualOverrideBody:
        if self.manual_name is None and self.is_locked is None:
            raise ValueError("At least one of manual_name or is_locked must be provided")
        return self


class ProductManualOverrideResponse(BaseModel):
    product: ProductCatalogItem
