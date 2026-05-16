from pydantic import BaseModel, ConfigDict, Field


class FitmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    make: str
    model: str
    body: str | None = None
    year_from: int | None = None
    year_to: int | None = None
    engine: str | None = None
    is_primary: bool
    sort_order: int


class ProductSummary(BaseModel):
    """Subset of product fields for list/catalog responses."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    odoo_product_id: str
    article: str
    brand: str
    part_type: str
    applicability_type: str
    generation_status: str
    name_locked: bool
    generated_name: str | None = None
    template_key: str
    template_version: str


class ProductRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    odoo_product_id: str
    external_code: str
    article: str
    brand: str
    part_type: str
    applicability_type: str
    side_axis: str | None = None
    cross_numbers: str | None = None
    supplier_raw_name: str | None = None
    primary_make: str | None = None
    primary_model: str | None = None
    primary_body: str | None = None
    year_from: int | None = None
    year_to: int | None = None
    engine: str | None = None
    fitment_summary: str | None = None
    template_key: str
    template_version: str
    generation_status: str
    name_locked: bool
    generated_name: str | None = None
    synced_at: str | None = None
    error_message: str | None = None
    source_hash: str
    created_at: str
    updated_at: str
    product_folder: str | None = None

    fitments: list[FitmentRead] = Field(default_factory=list)


class TemplateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    template_key: str
    version: str
    applicability_type: str
    name_pattern: str
    is_active: bool
    created_at: str
    updated_at: str
    part_type_pattern: str | None = None
    part_type_trigger: str | None = None
