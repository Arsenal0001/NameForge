"""Paginated product catalog for the SPA data grid."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.catalog_product import NamingStatus, ProductCatalogPage
from app.services.catalog_enrichment import enrich_catalog_items
from app.services.catalog_query import CatalogListFilters, query_catalog_products

router = APIRouter(prefix="/products", tags=["catalog"])


@router.get("", response_model=ProductCatalogPage)
def list_products(
    db: Session = Depends(get_db),
    *,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    search: str | None = Query(
        default=None,
        max_length=200,
        description="Case-insensitive match across article, codes, preview and Odoo name",
    ),
    naming_status: NamingStatus | None = Query(
        default=None,
        description="Filter by naming status (SQL approximation aligned with grid badges)",
    ),
    is_locked: bool | None = Query(default=None, description="Filter by name_locked flag"),
    has_error: bool | None = Query(
        default=None,
        description="When true, only rows with last_sync_error set",
    ),
) -> ProductCatalogPage:
    """
    Серверная пагинация каталога с обогащением из Odoo и TemplateEngine.

    Фильтры применяются в SQL до ``limit`` / ``offset``.
    """
    filters = CatalogListFilters(
        search=search,
        naming_status=naming_status,
        is_locked=is_locked,
        has_error=has_error,
    )
    rows, total = query_catalog_products(
        db,
        filters=filters,
        offset=offset,
        limit=limit,
    )
    items = enrich_catalog_items(db, rows)

    return ProductCatalogPage(
        items=items,
        total_count=total,
        limit=limit,
        offset=offset,
    )
