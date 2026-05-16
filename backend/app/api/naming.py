"""REST API for the naming engine (sync SQLAlchemy)."""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.product import Product
from app.schemas.naming import (
    BatchGenerateNameRequest,
    BatchGenerateNameResponse,
    BatchNamingErrorItem,
    GeneratedNamingResult,
)
from app.services.template_service import (
    NamingValidationError,
    generate_for_loaded_product,
    persist_generation_result,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/products", tags=["naming"])


def _validation_http_detail(exc: NamingValidationError | ValidationError) -> Any:
    if isinstance(exc, ValidationError):
        return {"message": "Ошибка валидации входных данных", "errors": exc.errors()}
    return {"message": str(exc)}


@router.post("/batch/generate-name", response_model=BatchGenerateNameResponse)
def post_batch_generate_product_names(
    body: BatchGenerateNameRequest,
    db: Session = Depends(get_db),
) -> BatchGenerateNameResponse:
    """
    Пакетная генерация. Каждый ``product_id`` обрабатывается в отдельном коммите,
    чтобы сбой одной строки не откатывал уже сохранённые результаты.
    """
    ordered_unique = list(dict.fromkeys(body.product_ids))

    ok_count = 0
    persisted_count = 0
    skipped_locked_count = 0
    skipped_idempotent_count = 0
    errors: list[BatchNamingErrorItem] = []

    for pid in ordered_unique:
        try:
            product = db.get(Product, pid)
            if product is None:
                errors.append(
                    BatchNamingErrorItem(product_id=pid, reason="Товар не найден")
                )
                continue

            if product.name_locked:
                skipped_locked_count += 1
                continue

            try:
                result = generate_for_loaded_product(db, product, persist=False)
            except NamingValidationError as exc:
                db.rollback()
                errors.append(BatchNamingErrorItem(product_id=pid, reason=str(exc)))
                continue
            except ValidationError as exc:
                db.rollback()
                errors.append(
                    BatchNamingErrorItem(
                        product_id=pid,
                        reason=json.dumps(exc.errors(), ensure_ascii=False),
                    )
                )
                continue

            if result.status == "error":
                msg = (
                    ", ".join(result.missing_fields)
                    if result.missing_fields
                    else "generation_error"
                )
                errors.append(BatchNamingErrorItem(product_id=pid, reason=msg))
                if persist_generation_result(db, product, result):
                    persisted_count += 1
                    db.add(product)
                db.commit()
                continue

            ok_count += 1
            if persist_generation_result(db, product, result):
                persisted_count += 1
                db.add(product)
            else:
                skipped_idempotent_count += 1
            db.commit()

        except Exception as exc:
            logger.exception("Unexpected batch naming failure product_id=%s", pid)
            db.rollback()
            errors.append(
                BatchNamingErrorItem(
                    product_id=pid, reason=f"unexpected:{type(exc).__name__}:{exc}"
                )
            )

    return BatchGenerateNameResponse(
        ok_count=ok_count,
        persisted_count=persisted_count,
        skipped_locked_count=skipped_locked_count,
        skipped_idempotent_count=skipped_idempotent_count,
        errors=errors,
    )


@router.post("/{product_id}/generate-name", response_model=GeneratedNamingResult)
def post_generate_product_name(
    product_id: int,
    db: Session = Depends(get_db),
) -> GeneratedNamingResult:
    """Сгенерировать имя для одного товара и сохранить в БД (если не ``name_locked``)."""
    product = db.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Товар не найден")

    try:
        result = generate_for_loaded_product(db, product, persist=False)
    except NamingValidationError as exc:
        raise HTTPException(
            status_code=422, detail=_validation_http_detail(exc)
        ) from exc
    except ValidationError as exc:
        raise HTTPException(
            status_code=422, detail=_validation_http_detail(exc)
        ) from exc

    if result.status == "error":
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Ошибка генерации имени",
                "missing_fields": result.missing_fields,
                "warnings": result.warnings,
            },
        )

    try:
        persist_generation_result(db, product, result)
        db.add(product)
        db.commit()
    except Exception:
        logger.exception("Commit failed after naming product_id=%s", product_id)
        db.rollback()
        raise

    return result
