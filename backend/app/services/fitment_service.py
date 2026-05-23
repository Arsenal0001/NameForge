"""Persist vehicle matrix selection and regenerate local naming preview."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.fitment import Fitment
from app.models.product import Product
from app.models.product_fitment import ProductVehicleFitment
from app.schemas.catalog_product import ProductCatalogItem
from app.schemas.naming import GeneratedNamingResult
from app.services.catalog_enrichment import build_catalog_item
from app.services.template_service import (
    NamingValidationError,
    generate_for_loaded_product,
    persist_generation_result,
)
from app.services.vehicle_directory import (
    ResolvedVehicleFitment,
    VehicleDirectoryError,
    resolve_vehicle_selection,
)
from src.fitment_repo import FitmentRow, build_fitment_summary

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TextFitmentInput:
    """One fitment row sourced from text (JSONL / operator input)."""

    make: str
    model: str
    body: str | None = None
    year_from: int | None = None
    year_to: int | None = None
    engine: str | None = None
    is_primary: bool = False
    sort_order: int = 0


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds")


def _build_summary_from_rows(rows: list[TextFitmentInput]) -> str:
    fitment_rows = [
        FitmentRow(
            product_id=0,
            make=row.make,
            model=row.model,
            body=row.body,
            year_from=row.year_from,
            year_to=row.year_to,
            engine=row.engine,
            is_primary=1 if row.is_primary else 0,
            sort_order=row.sort_order,
        )
        for row in rows
    ]
    return build_fitment_summary(fitment_rows)


def _build_summary(resolved: ResolvedVehicleFitment) -> str:
    return _build_summary_from_rows(
        [
            TextFitmentInput(
                make=resolved.make,
                model=resolved.model,
                body=resolved.body,
                year_from=resolved.year_from,
                year_to=resolved.year_to,
                is_primary=True,
            )
        ]
    )


def _replace_product_fitments(
    session: Session,
    product: Product,
    rows: list[TextFitmentInput],
    *,
    applicability_type: str,
    now: str,
) -> TextFitmentInput | None:
    """Write fitment rows + denormalized product columns. Returns primary row."""
    for existing in list(product.fitments):
        session.delete(existing)
    session.flush()

    primary: TextFitmentInput | None = None
    if rows:
        working = list(rows)
        if not any(row.is_primary for row in working):
            head = working[0]
            working[0] = TextFitmentInput(
                make=head.make,
                model=head.model,
                body=head.body,
                year_from=head.year_from,
                year_to=head.year_to,
                engine=head.engine,
                is_primary=True,
                sort_order=head.sort_order,
            )

        for idx, spec in enumerate(working):
            session.add(
                Fitment(
                    product_id=product.id,
                    make=spec.make,
                    model=spec.model,
                    body=spec.body,
                    year_from=spec.year_from,
                    year_to=spec.year_to,
                    engine=spec.engine,
                    is_primary=spec.is_primary,
                    sort_order=spec.sort_order if spec.sort_order else idx,
                    created_at=now,
                    updated_at=now,
                )
            )
            if spec.is_primary:
                primary = spec

        if primary is None:
            primary = working[0]

        product.applicability_type = applicability_type
        product.primary_make = primary.make
        product.primary_model = primary.model
        product.primary_body = primary.body
        product.year_from = primary.year_from
        product.year_to = primary.year_to
        product.engine = primary.engine
        product.fitment_summary = _build_summary_from_rows(working)
    else:
        product.applicability_type = applicability_type
        product.primary_make = None
        product.primary_model = None
        product.primary_body = None
        product.year_from = None
        product.year_to = None
        product.engine = None
        product.fitment_summary = None

    product.updated_at = now
    session.flush()
    session.expire(product, ["fitments"])
    return primary


def apply_product_text_fitment(
    session: Session,
    product: Product,
    *,
    applicability_type: str,
    fitment_rows: list[TextFitmentInput],
    persist: bool = True,
) -> GeneratedNamingResult:
    """
    Apply text fitment/universal applicability and regenerate naming locally.

    Does not commit — caller controls transaction boundaries for batching.
    """
    now = _utc_now_iso()
    _replace_product_fitments(
        session,
        product,
        fitment_rows,
        applicability_type=applicability_type,
        now=now,
    )

    try:
        result = generate_for_loaded_product(session, product, persist=False)
    except NamingValidationError:
        raise

    if result.status == "error":
        missing = ", ".join(result.missing_fields) or "generation_error"
        raise FitmentValidationError(missing)

    if persist and not product.name_locked:
        persist_generation_result(session, product, result)
        session.add(product)

    return result


def save_product_vehicle_fitment(
    session: Session,
    product_id: int,
    *,
    make_id: int,
    model_id: int,
    generation_id: int,
) -> ProductCatalogItem:
    """
    Save directory ids + text fitment locally, regenerate naming preview.

    No Odoo writes — only SQLite updates and TemplateEngine persistence.
    """
    product = session.get(Product, product_id)
    if product is None:
        raise ProductNotFoundError(product_id)

    try:
        resolved = resolve_vehicle_selection(
            make_id=make_id,
            model_id=model_id,
            generation_id=generation_id,
        )
    except VehicleDirectoryError as exc:
        raise FitmentValidationError(str(exc)) from exc

    now = _utc_now_iso()

    existing_vehicle = session.scalar(
        select(ProductVehicleFitment).where(
            ProductVehicleFitment.product_id == product_id
        )
    )
    if existing_vehicle is None:
        existing_vehicle = ProductVehicleFitment(
            product_id=product_id,
            make_id=resolved.make_id,
            model_id=resolved.model_id,
            generation_id=resolved.generation_id,
            created_at=now,
            updated_at=now,
        )
        session.add(existing_vehicle)
    else:
        existing_vehicle.make_id = resolved.make_id
        existing_vehicle.model_id = resolved.model_id
        existing_vehicle.generation_id = resolved.generation_id
        existing_vehicle.updated_at = now

    text_row = TextFitmentInput(
        make=resolved.make,
        model=resolved.model,
        body=resolved.body,
        year_from=resolved.year_from,
        year_to=resolved.year_to,
        is_primary=True,
    )
    result = apply_product_text_fitment(
        session,
        product,
        applicability_type="fitment",
        fitment_rows=[text_row],
        persist=not product.name_locked,
    )

    session.commit()
    session.refresh(product)

    logger.info(
        "Saved vehicle fitment product_id=%s make=%s model=%s preview=%s",
        product_id,
        resolved.make,
        resolved.model,
        (result.name or "")[:80],
    )

    return build_catalog_item(session, product, odoo_row=None)


class ProductNotFoundError(LookupError):
    def __init__(self, product_id: int) -> None:
        super().__init__(f"Product {product_id} not found")
        self.product_id = product_id


class FitmentValidationError(ValueError):
    """Invalid vehicle selection or naming inputs."""
