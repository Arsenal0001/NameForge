"""Catalog list DTOs (Odoo-aligned columns for the SPA grid)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

NamingStatus = Literal["no_template", "pending_sync", "synced"]


class ProductCatalogItem(BaseModel):
    """One catalog grid row — Odoo-aligned fields plus naming preview."""

    model_config = {"from_attributes": False}

    id: int
    article: str = Field(description="Article / default_code equivalent")
    odoo_name: str = Field(default="", description="Current name in Odoo (live read)")
    name: str = Field(description="Stored generated_name or fallback to odoo_name")
    preview_name: str = Field(default="", description="TemplateEngine golden preview")
    naming_status: NamingStatus = Field(
        default="no_template",
        description="no_template | pending_sync | synced",
    )
    category: str = Field(
        default="",
        description="Category label (currently product_folder when set)",
    )
    part_type: str = Field(default="", description="Part type label from products.part_type")
    applicability_type: str = Field(
        default="universal",
        description="fitment | universal",
    )
    brand: str
    primary_make: str = Field(default="", description="Primary vehicle make")
    primary_model: str = Field(default="", description="Primary vehicle model")
    fitment_summary: str = Field(default="", description="Compact fitment / specs line")
    name_locked: bool
    category_template_bound: bool = Field(
        default=False,
        description="Category cascade resolved a naming matrix",
    )
    search_keywords: str = Field(
        default="",
        description="Preview search pool (rule 2)",
    )
    last_sync_error: str | None = Field(
        default=None,
        description="Last Odoo sync failure message for this product",
    )


class ProductCatalogPage(BaseModel):
    """Paginated catalog payload."""

    items: list[ProductCatalogItem]
    total_count: int = Field(description="Total rows matching catalog query (all pages).")
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)
