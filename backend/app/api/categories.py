"""Odoo category cache + naming matrix assignment."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, nullslast, or_, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.odoo_catalog_cache import OdooCategory
from app.schemas.category import (
    CategoryListPage,
    CategoryRow,
    NamingMatrixOption,
    PutCategoryTemplateBody,
)
from app.services.naming_matrices import NAMING_MATRIX_DEFINITIONS, is_valid_matrix_id
from app.services.template_service import get_template_engine

router = APIRouter(prefix="/categories", tags=["categories"])


def _category_search_clause(q: str | None):
    if not q or not str(q).strip():
        return None
    pat = f"%{str(q).strip()}%"
    return or_(
        OdooCategory.name.like(pat),
        OdooCategory.complete_name.like(pat),
    )


def _to_row(c: OdooCategory) -> CategoryRow:
    key = (c.naming_template_key or "").strip() or None
    pattern = (c.name_pattern or "").strip() or None
    return CategoryRow(
        odoo_id=c.odoo_id,
        name=c.name or "",
        complete_name=c.complete_name,
        parent_id=c.parent_id,
        naming_template_key=key,
        name_pattern=pattern,
    )


@router.get("/matrices", response_model=list[NamingMatrixOption])
def list_naming_matrices() -> list[NamingMatrixOption]:
    """Matrices documented in ``NAMING_TEMPLATES.md`` (logical ids + labels)."""
    return [
        NamingMatrixOption(matrix_id=k, title=t, formula_hint=h)
        for k, t, h in NAMING_MATRIX_DEFINITIONS
    ]


@router.get("", response_model=CategoryListPage)
def list_categories(
    db: Session = Depends(get_db),
    *,
    q: str | None = Query(
        None,
        description="Подстрока по имени категории или complete_name",
    ),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> CategoryListPage:
    cond = _category_search_clause(q)
    count_stmt = select(func.count()).select_from(OdooCategory)
    if cond is not None:
        count_stmt = count_stmt.where(cond)
    total = db.scalar(count_stmt)
    if total is None:
        total = 0

    stmt = select(OdooCategory).order_by(
        nullslast(OdooCategory.complete_name.asc()),
        OdooCategory.name.asc(),
        OdooCategory.odoo_id.asc(),
    )
    if cond is not None:
        stmt = stmt.where(cond)
    stmt = stmt.offset(offset).limit(limit)
    rows = db.scalars(stmt).all()

    return CategoryListPage(
        items=[_to_row(c) for c in rows],
        total_count=int(total),
        limit=limit,
        offset=offset,
    )


@router.put("/{category_id}/template", response_model=CategoryRow)
def put_category_template(
    category_id: int,
    body: PutCategoryTemplateBody,
    db: Session = Depends(get_db),
) -> CategoryRow:
    cat = db.get(OdooCategory, category_id)
    if cat is None:
        raise HTTPException(status_code=404, detail="Категория не найдена")

    raw = body.naming_template_key
    if raw is None or not str(raw).strip():
        cat.naming_template_key = None
    else:
        key = str(raw).strip()
        if not is_valid_matrix_id(key):
            raise HTTPException(
                status_code=422,
                detail="Неизвестный идентификатор матрицы",
            )
        cat.naming_template_key = key

    db.add(cat)
    db.commit()
    db.refresh(cat)
    get_template_engine().invalidate_cache()
    return _to_row(cat)
