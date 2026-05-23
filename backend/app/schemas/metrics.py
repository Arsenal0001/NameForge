"""Dashboard KPI DTOs (local catalog cache aggregates)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class DashboardMetricsDTO(BaseModel):
    """Aggregate product counts for the main dashboard."""

    total_products: int = Field(ge=0, description="Total rows in local products cache")
    synced: int = Field(
        ge=0,
        description="Products with generated preview aligned with Odoo cache or synced_at set",
    )
    pending: int = Field(
        ge=0,
        description="Products with generated preview awaiting Odoo push",
    )
    locked: int = Field(ge=0, description="Products with name_locked enabled")
