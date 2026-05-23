from pydantic import BaseModel, Field


class OdooPingResponse(BaseModel):
    ok: bool
    user: str | None = None
    detail: str | None = None


class OdooSyncQueuedResponse(BaseModel):
    status: str = Field(description="Immediate acknowledgement for background sync")


class OdooCategoriesSyncResponse(BaseModel):
    inserted: int = Field(description="New rows in odoo_categories")
    updated: int = Field(description="Existing rows refreshed from Odoo")
    total: int = Field(description="inserted + updated")


class OdooCacheStatsResponse(BaseModel):
    odoo_categories: int
    odoo_product_attributes: int
    odoo_product_attribute_values: int
    odoo_product_templates: int


class OdooPushRequest(BaseModel):
    product_ids: list[int]


class OdooPushResponse(BaseModel):
    total: int
    pushed: int
    skipped: int
    errors: int


class OdooProductTemplatePreview(BaseModel):
    id: int
    name: str
    default_code: str | None = None
    categ_id: list | int | None = None
    description_sale: str | None = None


class OdooProductTemplateLookupResponse(BaseModel):
    ok: bool
    found: bool
    default_code: str
    template: OdooProductTemplatePreview | None = None
    detail: str | None = None
