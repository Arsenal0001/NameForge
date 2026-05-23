"""Background job trigger and progress DTOs."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class JobAcceptedResponse(BaseModel):
    job: str = Field(description="Job identifier")
    status: Literal["accepted"] = "accepted"
    message: str = Field(description="Human-readable confirmation for the operator UI")


class JobProgressItem(BaseModel):
    job_type: str = Field(description="Job identifier (matches JobKind)")
    status: Literal["running", "completed", "failed"]
    processed_items: int = Field(ge=0)
    total_items: int = Field(ge=0)
    progress_percent: float = Field(ge=0.0, le=100.0)
    error_message: str | None = None
    started_at: str | None = None
    finished_at: str | None = None


class ActiveJobsResponse(BaseModel):
    jobs: list[JobProgressItem]
