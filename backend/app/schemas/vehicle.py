"""DTOs for vehicle applicability matrix (Make → Model → Generation)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class VehicleMake(BaseModel):
    """Top-level vehicle manufacturer."""

    id: int = Field(description="Stable make identifier.")
    name: str = Field(description="Display name, e.g. BMW.")


class VehicleModel(BaseModel):
    """Model belonging to a single make."""

    id: int = Field(description="Stable model identifier.")
    make_id: int = Field(description="Parent make id.")
    name: str = Field(description="Display name, e.g. 3 Series.")


class VehicleGeneration(BaseModel):
    """Generation / body style for a model."""

    id: int = Field(description="Stable generation identifier.")
    model_id: int = Field(description="Parent model id.")
    name: str = Field(
        description="Display label, e.g. E90 (2005–2011).",
    )
