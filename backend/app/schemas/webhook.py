"""Pydantic models for inbound Odoo webhooks."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class OdooProductWebhookPayload(BaseModel):
    """Minimal payload from Odoo automation on product.template create/write."""

    model_config = ConfigDict(str_strip_whitespace=True)

    product_id: int = Field(ge=1, description="Odoo product.template id")
    default_code: str | None = Field(
        default=None,
        description="Optional SKU for cross-check / local lookup fallback",
    )


class WebhookAcceptedResponse(BaseModel):
    status: Literal["accepted"] = "accepted"
