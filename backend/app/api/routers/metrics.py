"""Dashboard metrics API (local cache aggregates)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.metrics import DashboardMetricsDTO
from app.services.metrics_service import fetch_dashboard_metrics

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("/dashboard", response_model=DashboardMetricsDTO)
def get_dashboard_metrics(db: Session = Depends(get_db)) -> DashboardMetricsDTO:
    """Return catalog health KPIs from the local SQLite cache (no Odoo calls)."""
    return fetch_dashboard_metrics(db)
