"""API shapes for category-bound naming templates and live preview."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class CategoryTemplateRow(BaseModel):
    """Operator-edited name pattern bound to one Odoo category."""

    model_config = ConfigDict(str_strip_whitespace=True)

    category_id: int
    category_name: str
    complete_name: str | None = None
    name_pattern: str = Field(min_length=1, description="Formula with {token} placeholders.")


class CategoryTemplateUpsertBody(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name_pattern: str = Field(
        min_length=1,
        description="Naming formula, e.g. {part_type} {brand} {make} {model}.",
    )


class CategoryTemplateListPage(BaseModel):
    items: list[CategoryTemplateRow]
    total_count: int


class TemplateLivePreviewRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    category_id: int = Field(ge=1)
    template_string: str = Field(min_length=1)


class TemplateLivePreviewItem(BaseModel):
    odoo_id: int | None = None
    odoo_name: str
    generated_name: str
    status: str = "generated"
    warnings: list[str] = Field(default_factory=list)


class TemplateLivePreviewResponse(BaseModel):
    category_id: int
    template_string: str
    normalized_pattern: str
    items: list[TemplateLivePreviewItem]
    sample_source: str = Field(
        description="cache | odoo | mixed — where sample products were loaded from.",
    )


class TemplateTokenHint(BaseModel):
    token: str
    description: str


class TemplateTokenHintsResponse(BaseModel):
    tokens: list[TemplateTokenHint]
