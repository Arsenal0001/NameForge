"""Paginated product catalog for the SPA data grid."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.product import Product
from app.schemas.catalog_product import ProductCatalogItem, ProductCatalogPage
from app.services.category_template_binding import resolve_logical_matrix_id

router = APIRouter(prefix="/products", tags=["catalog"])


def _row_from_product(db: Session, p: Product) -> ProductCatalogItem:
    name = (p.generated_name or "").strip()
    category = (p.product_folder or "").strip()
    matrix_id = resolve_logical_matrix_id(db, p)
    return ProductCatalogItem(
        id=p.id,
        article=p.article or "",
        name=name,
        category=category,
        brand=p.brand or "",
        name_locked=bool(p.name_locked),
        category_template_bound=bool(matrix_id),
        search_keywords=(p.search_keywords or "").strip(),
    )


@router.get("", response_model=ProductCatalogPage)
def list_products(
    db: Session = Depends(get_db),
    *,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> ProductCatalogPage:
    """Серверная пагинация списка товаров для таблицы каталога."""
    total = db.scalar(select(func.count()).select_from(Product))
    if total is None:
        total = 0

    stmt = select(Product).order_by(Product.id.asc()).offset(offset).limit(limit)
    rows = db.scalars(stmt).all()

    items = [_row_from_product(db, p) for p in rows]

    return ProductCatalogPage(
        items=items,
        total_count=int(total),
        limit=limit,
        offset=offset,
    )
