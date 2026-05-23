"""Dashboard KPI aggregation from the local products cache (SQL-only)."""

from __future__ import annotations

from sqlalchemy import and_, case, cast, func, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.types import Integer

from app.models.odoo_catalog_cache import OdooProductTemplate
from app.models.product import Product
from app.schemas.metrics import DashboardMetricsDTO


def _trim_generated_name():
    return func.trim(func.coalesce(Product.generated_name, ""))


def fetch_dashboard_metrics(session: Session) -> DashboardMetricsDTO:
    """
    Aggregate dashboard KPIs in a single SQL query.

    Synced/pending heuristics mirror ``compute_naming_status`` using only local
    fields: ``generated_name``, ``synced_at``, and cached ``odoo_product_templates.name``.
    No live Odoo HTTP calls.
    """
    preview_name = _trim_generated_name()
    has_preview = preview_name != ""
    cache_name = func.trim(func.coalesce(OdooProductTemplate.name, ""))
    names_match = and_(cache_name != "", preview_name == cache_name)
    has_synced_at = Product.synced_at.isnot(None)

    is_synced = and_(
        has_preview,
        or_(has_synced_at, names_match),
    )
    is_pending = and_(
        has_preview,
        Product.name_locked.is_(False),
        ~is_synced,
    )

    stmt = (
        select(
            func.count().label("total_products"),
            func.coalesce(
                func.sum(case((is_synced, 1), else_=0)),
                0,
            ).label("synced"),
            func.coalesce(
                func.sum(case((is_pending, 1), else_=0)),
                0,
            ).label("pending"),
            func.coalesce(
                func.sum(case((Product.name_locked.is_(True), 1), else_=0)),
                0,
            ).label("locked"),
        )
        .select_from(Product)
        .outerjoin(
            OdooProductTemplate,
            cast(Product.odoo_product_id, Integer) == OdooProductTemplate.odoo_id,
        )
    )

    row = session.execute(stmt).one()
    return DashboardMetricsDTO(
        total_products=int(row.total_products or 0),
        synced=int(row.synced or 0),
        pending=int(row.pending or 0),
        locked=int(row.locked or 0),
    )
