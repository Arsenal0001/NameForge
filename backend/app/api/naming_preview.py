"""Stateless naming preview API (no DB / Odoo writes)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import ValidationError

from app.schemas.naming import NamingPreviewRequest, NamingPreviewResponse
from app.services.template_service import NamingValidationError, preview_naming

router = APIRouter(prefix="/naming", tags=["naming"])


def _validation_http_detail(exc: NamingValidationError | ValidationError) -> Any:
    if isinstance(exc, ValidationError):
        return {"message": "Ошибка валидации входных данных", "errors": exc.errors()}
    return {"message": str(exc)}


@router.post("/preview", response_model=NamingPreviewResponse)
def post_naming_preview(body: NamingPreviewRequest) -> NamingPreviewResponse:
    """
    Сгенерировать превью имени по сырым атрибутам товара.

    Не читает и не пишет SQLite/Odoo — только pure function из ``template_service``.
    """
    try:
        result = preview_naming(body)
    except NamingValidationError as exc:
        raise HTTPException(
            status_code=422, detail=_validation_http_detail(exc)
        ) from exc
    except ValidationError as exc:
        raise HTTPException(
            status_code=422, detail=_validation_http_detail(exc)
        ) from exc

    current = (body.current_name or "").strip()
    preview_name = result.name.strip()
    return NamingPreviewResponse(
        current_name=current,
        name=result.name,
        search_keywords=result.search_keywords,
        description=result.description,
        status=result.status,
        warnings=result.warnings,
        missing_fields=result.missing_fields,
        template_pattern_used=result.template_pattern_used,
        truncated=result.truncated,
        changed=bool(current) and current != preview_name,
    )
