"""Inbound webhooks from Odoo (async, non-blocking)."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks

from app.schemas.webhook import OdooProductWebhookPayload, WebhookAcceptedResponse
from app.services.webhook_processor import process_product_webhook_async

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/odoo/product", response_model=WebhookAcceptedResponse)
def post_odoo_product_webhook(
    body: OdooProductWebhookPayload,
    background_tasks: BackgroundTasks,
) -> WebhookAcceptedResponse:
    """
    Accept a lightweight Odoo ``product.template`` event.

    Returns immediately; naming + sync run in a background task.
    """
    background_tasks.add_task(process_product_webhook_async, body)
    return WebhookAcceptedResponse()
