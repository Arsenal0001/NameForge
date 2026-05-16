"""Catalog list DTOs (Odoo-aligned columns for the SPA grid)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ProductCatalogItem(BaseModel):
    """One catalog grid row — Odoo-aligned fields plus ``name_locked``."""

    model_config = {"from_attributes": False}

    id: int
    article: str = Field(description="Article / default_code equivalent")
    name: str = Field(description="Display name (stored generated_name)")
    category: str = Field(
        default="",
        description="Category label (currently product_folder when set)",
    )
    brand: str
    name_locked: bool
    category_template_bound: bool = Field(
        default=False,
        description="Reserved for category↔template binding badge",
    )
    search_keywords: str = Field(
        default="",
        description="Поисковый пул (правило 2); сохраняется после генерации.",
    )


class ProductCatalogPage(BaseModel):
    """Paginated catalog payload."""

    items: list[ProductCatalogItem]
    total_count: int = Field(description="Total rows matching catalog query (all pages).")
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)
