"""Lightweight vehicle directory endpoints (mock data until Base-Auto import)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.schemas.vehicle import VehicleGeneration, VehicleMake, VehicleModel
from app.services.vehicle_directory import (
    GENERATIONS,
    MAKES,
    MODELS,
)

router = APIRouter(prefix="/vehicles", tags=["vehicles"])

_MAKE_IDS = {m.id for m in MAKES}
_MODEL_IDS = {m.id for m in MODELS}


@router.get("/makes", response_model=list[VehicleMake])
def list_makes() -> list[VehicleMake]:
    """Return all vehicle makes sorted by name."""
    return sorted(MAKES, key=lambda m: m.name)


@router.get("/models", response_model=list[VehicleModel])
def list_models(
    make_id: int = Query(..., description="Parent make id."),
) -> list[VehicleModel]:
    """Return models for the given make."""
    if make_id not in _MAKE_IDS:
        raise HTTPException(status_code=404, detail="Марка не найдена")
    rows = [m for m in MODELS if m.make_id == make_id]
    return sorted(rows, key=lambda m: m.name)


@router.get("/generations", response_model=list[VehicleGeneration])
def list_generations(
    model_id: int = Query(..., description="Parent model id."),
) -> list[VehicleGeneration]:
    """Return generations for the given model."""
    if model_id not in _MODEL_IDS:
        raise HTTPException(status_code=404, detail="Модель не найдена")
    rows = [g for g in GENERATIONS if g.model_id == model_id]
    return sorted(rows, key=lambda g: g.name)
