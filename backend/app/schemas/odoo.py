from pydantic import BaseModel, Field


class OdooPingResponse(BaseModel):
    ok: bool
    user: str | None = None
    detail: str | None = None


class OdooSyncQueuedResponse(BaseModel):
    status: str = Field(description="Immediate acknowledgement for background sync")


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
