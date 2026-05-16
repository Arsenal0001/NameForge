"""API shapes for Odoo category ↔ naming matrix mapping."""

from __future__ import annotations

from pydantic import BaseModel, Field


class NamingMatrixOption(BaseModel):
    """One selectable matrix from ``NAMING_TEMPLATES.md`` / registry."""

    matrix_id: str = Field(description="Logical id stored on categories / UI value.")
    title: str
    formula_hint: str


class CategoryRow(BaseModel):
    """Cached Odoo ``product.category`` row plus binding."""

    odoo_id: int
    name: str
    complete_name: str | None = None
    parent_id: int | None = None
    naming_template_key: str | None = Field(
        None,
        description="Logical matrix id; null if operator cleared the binding.",
    )


class CategoryListPage(BaseModel):
    items: list[CategoryRow]
    total_count: int
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)


class PutCategoryTemplateBody(BaseModel):
    naming_template_key: str | None = Field(
        None,
        description="Logical matrix id from registry, or null to clear.",
    )
