"""CRUD for category-bound naming templates + live preview."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.odoo_catalog_cache import OdooCategory
from app.schemas.template import (
    CategoryTemplateListPage,
    CategoryTemplateRow,
    CategoryTemplateUpsertBody,
    TemplateLivePreviewRequest,
    TemplateLivePreviewResponse,
    TemplateTokenHint,
    TemplateTokenHintsResponse,
)
from app.services.template_live_preview import run_live_preview
from app.services.template_service import get_template_engine

router = APIRouter(prefix="/templates", tags=["templates"])

AVAILABLE_TOKENS: tuple[tuple[str, str], ...] = (
    ("{part_type}", "Тип товара"),
    ("{brand}", "Бренд"),
    ("{make}", "Марка (fitment)"),
    ("{model}", "Модель (fitment)"),
    ("{body}", "Поколение / кузов"),
    ("{years}", "Годы выпуска"),
    ("{engine}", "Двигатель"),
    ("{fitment_core}", "Блок применяемости"),
    ("{dlya_segment}", "Сегмент «для …»"),
    ("{characteristics}", "Доп. характеристики"),
    ("{installation}", "Место установки"),
    ("{side}", "Сторона / ось"),
    ("{cross_numbers}", "Кросс-номера"),
)


def _to_row(cat: OdooCategory) -> CategoryTemplateRow:
    return CategoryTemplateRow(
        category_id=cat.odoo_id,
        category_name=cat.name or "",
        complete_name=cat.complete_name,
        name_pattern=(cat.name_pattern or "").strip(),
    )


@router.get("/tokens", response_model=TemplateTokenHintsResponse)
def list_template_tokens() -> TemplateTokenHintsResponse:
    """Подсказки доступных плейсхолдеров для редактора формулы."""
    return TemplateTokenHintsResponse(
        tokens=[
            TemplateTokenHint(token=t, description=d) for t, d in AVAILABLE_TOKENS
        ]
    )


@router.post("/preview-live", response_model=TemplateLivePreviewResponse)
def post_template_preview_live(
    body: TemplateLivePreviewRequest,
    db: Session = Depends(get_db),
) -> TemplateLivePreviewResponse:
    """
    Вычислительное превью: 3 товара из категории Odoo + ad-hoc ``template_string``.

    Только ``search_read`` в Odoo (или локальный кэш); без записи в ERP.
    """
    try:
        return run_live_preview(
            db,
            category_id=body.category_id,
            template_string=body.template_string,
        )
    except LookupError as exc:
        if str(exc) == "category_not_found":
            raise HTTPException(status_code=404, detail="Категория не найдена") from exc
        raise


@router.get("", response_model=CategoryTemplateListPage)
def list_category_templates(
    db: Session = Depends(get_db),
) -> CategoryTemplateListPage:
    """Категории с сохранённой формулой ``name_pattern``."""
    stmt = (
        select(OdooCategory)
        .where(
            OdooCategory.name_pattern.is_not(None),
            func.trim(OdooCategory.name_pattern) != "",
        )
        .order_by(OdooCategory.complete_name.asc(), OdooCategory.name.asc())
    )
    rows = db.scalars(stmt).all()
    items = [_to_row(c) for c in rows]
    return CategoryTemplateListPage(items=items, total_count=len(items))


@router.get("/{category_id}", response_model=CategoryTemplateRow)
def get_category_template(
    category_id: int,
    db: Session = Depends(get_db),
) -> CategoryTemplateRow:
    cat = db.get(OdooCategory, category_id)
    if cat is None:
        raise HTTPException(status_code=404, detail="Категория не найдена")
    pattern = (cat.name_pattern or "").strip()
    if not pattern:
        raise HTTPException(status_code=404, detail="Шаблон для категории не задан")
    return _to_row(cat)


@router.put("/{category_id}", response_model=CategoryTemplateRow)
def upsert_category_template(
    category_id: int,
    body: CategoryTemplateUpsertBody,
    db: Session = Depends(get_db),
) -> CategoryTemplateRow:
    cat = db.get(OdooCategory, category_id)
    if cat is None:
        raise HTTPException(status_code=404, detail="Категория не найдена")

    cat.name_pattern = body.name_pattern.strip()
    db.add(cat)
    db.commit()
    db.refresh(cat)
    get_template_engine().invalidate_cache()
    return _to_row(cat)


@router.delete("/{category_id}", status_code=204)
def delete_category_template(
    category_id: int,
    db: Session = Depends(get_db),
) -> None:
    cat = db.get(OdooCategory, category_id)
    if cat is None:
        raise HTTPException(status_code=404, detail="Категория не найдена")
    cat.name_pattern = None
    db.add(cat)
    db.commit()
    get_template_engine().invalidate_cache()
