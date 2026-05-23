"""Pydantic models for Odoo sync pipeline."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

SyncLogAction = Literal[
    "pushed",
    "dry_run_would_push",
    "skipped_locked",
    "skipped_idempotent",
    "skipped_invalid",
    "error",
]


class SyncOdooRequest(BaseModel):
    product_ids: list[int] = Field(
        ...,
        min_length=1,
        max_length=5000,
        description="Local products.id values to sync (deduplicated server-side).",
    )


class SyncLogEntry(BaseModel):
    product_id: int
    action: SyncLogAction
    detail: str = ""


class SyncOdooResponse(BaseModel):
    dry_run: bool
    total: int
    pushed: int
    skipped_locked: int
    skipped_idempotent: int
    skipped_invalid: int
    errors: int
    synced_product_ids: list[int] = Field(default_factory=list)
    log: list[SyncLogEntry] = Field(default_factory=list)
