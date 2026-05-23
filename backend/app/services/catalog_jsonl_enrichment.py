"""Mass-enrich local products from ``odoo_master_catalog.jsonl`` (no Odoo HTTP)."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal, engine
from app.core.schema_patches import apply_schema_patches
from app.models.product import Product
from app.services.attribute_parser import format_attributes_to_russian
from app.services.text_utils import sanitize_token_value
from app.services.fitment_service import (
    FitmentValidationError,
    TextFitmentInput,
    apply_product_text_fitment,
)
from app.services.template_service import (
    NamingValidationError,
    get_template_engine,
)

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_JSONL = _PROJECT_ROOT / "data" / "odoo_master_catalog.jsonl"

_DEFAULT_CODE_KEYS = (
    "default_code",
    "id",
    "Внешний код (ID)",
    "external_code",
)
_MAKE_KEYS = ("make", "Марка")
_MODEL_KEYS = ("model", "Модель")
_GENERATION_KEYS = ("generation", "Поколение", "body", "Кузов")
_YEARS_KEYS = ("years", "Годы", "year_range")
_ENGINE_KEYS = ("engine", "Двигатель")

_YEARS_RE = re.compile(
    r"(\d{4})\s*[–\-]\s*(\d{4}|н\.в\.|\?)",
    re.IGNORECASE,
)


@dataclass
class EnrichmentStats:
    jsonl_rows: int = 0
    jsonl_with_code: int = 0
    matched_rows: int = 0
    matched_products: int = 0
    ready_fitment: int = 0
    ready_universal: int = 0
    skipped_no_match: int = 0
    skipped_incomplete: int = 0
    skipped_locked: int = 0
    applied: int = 0
    generation_errors: int = 0
    preview_fitment: list[dict[str, str]] = field(default_factory=list)
    preview_universal: list[dict[str, str]] = field(default_factory=list)


def _pick_text(source: dict, *keys: str) -> str:
    for key in keys:
        value = source.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def extract_default_code(row: dict) -> str:
    for key in _DEFAULT_CODE_KEYS:
        code = _pick_text(row, key)
        if code:
            return code
    return ""


def code_variants(code: str) -> set[str]:
    raw = code.strip()
    if not raw:
        return set()
    variants = {raw, raw.lstrip("0") or "0"}
    if raw.isdigit():
        variants.add(raw.zfill(5))
        variants.add(raw.zfill(6))
    return {v for v in variants if v}


def parse_years_value(value: object | None) -> tuple[int | None, int | None]:
    if value is None:
        return None, None
    if isinstance(value, (int, float)):
        year = int(value)
        return year, None
    text = str(value).strip()
    if not text:
        return None, None
    match = _YEARS_RE.search(text)
    if match:
        year_from = int(match.group(1))
        end = match.group(2).lower()
        year_to = 0 if end in {"н.в.", "?"} else int(match.group(2))
        return year_from, year_to
    if text.isdigit() and len(text) == 4:
        return int(text), None
    return None, None


def extract_applicability_entries(row: dict) -> list[dict]:
    raw = row.get("applicability")
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    if isinstance(raw, dict):
        if raw.get("is_universal"):
            return []
        return [raw]
    return []


def build_text_fitments(row: dict) -> tuple[str, list[TextFitmentInput]] | None:
    entries = extract_applicability_entries(row)
    if not entries:
        return "universal", []

    parsed: list[TextFitmentInput] = []
    for idx, entry in enumerate(entries):
        make = _pick_text(entry, *_MAKE_KEYS)
        model = _pick_text(entry, *_MODEL_KEYS)
        if not make or not model:
            continue

        generation = _pick_text(entry, *_GENERATION_KEYS)
        year_from, year_to = parse_years_value(
            entry.get("years") or entry.get("year_range") or entry.get("Годы")
        )
        if year_from is None and year_to is None:
            for key in _YEARS_KEYS:
                year_from, year_to = parse_years_value(entry.get(key))
                if year_from is not None or year_to is not None:
                    break

        parsed.append(
            TextFitmentInput(
                make=make,
                model=model,
                body=generation or None,
                year_from=year_from,
                year_to=year_to,
                engine=_pick_text(entry, *_ENGINE_KEYS) or None,
                is_primary=idx == 0,
                sort_order=idx,
            )
        )

    if not parsed:
        return None

    parsed[0] = TextFitmentInput(
        make=parsed[0].make,
        model=parsed[0].model,
        body=parsed[0].body,
        year_from=parsed[0].year_from,
        year_to=parsed[0].year_to,
        engine=parsed[0].engine,
        is_primary=True,
        sort_order=0,
    )
    return "fitment", parsed


def enrich_product_fields(product: Product, row: dict) -> None:
    golden_type = _pick_text(row, "golden_type", "goldenType")
    if golden_type:
        product.part_type = golden_type

    brand = sanitize_token_value(_pick_text(row, "brand"))
    if brand:
        product.brand = brand

    attrs = row.get("attributes")
    if isinstance(attrs, dict):
        product.attributes_json = json.dumps(attrs, ensure_ascii=False, sort_keys=True)
        formatted_attrs = format_attributes_to_russian(attrs)
        if formatted_attrs:
            product.attribute_summary = formatted_attrs

        side_axis = _pick_text(
            attrs,
            "side",
            "axis",
            "installation_location",
            "Сторона",
            "Ось",
        )
        if side_axis:
            product.side_axis = side_axis

    original_name = _pick_text(row, "original_name")
    if original_name and not (product.supplier_raw_name or "").strip():
        product.supplier_raw_name = original_name


def build_product_index(products: list[Product]) -> dict[str, Product]:
    index: dict[str, Product] = {}
    for product in products:
        for source in (product.external_code, product.article):
            for variant in code_variants(str(source or "")):
                index.setdefault(variant, product)
    return index


def load_jsonl_rows(path: Path) -> list[dict]:
    rows: list[dict] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
        else:
            logger.warning("Skip JSONL line %s: expected JSON object", line_no)
    return rows


def _process_row(
    session: Session,
    product: Product,
    row: dict,
    *,
    dry_run: bool,
    stats: EnrichmentStats,
) -> None:
    parsed = build_text_fitments(row)
    if parsed is None:
        stats.skipped_incomplete += 1
        return

    applicability_type, fitment_rows = parsed
    if applicability_type == "fitment":
        stats.ready_fitment += 1
    else:
        stats.ready_universal += 1

    if product.name_locked:
        stats.skipped_locked += 1
        return

    enrich_product_fields(product, row)

    if dry_run:
        primary = fitment_rows[0] if fitment_rows else None
        target = (
            stats.preview_fitment
            if applicability_type == "fitment"
            else stats.preview_universal
        )
        target_limit = 3 if applicability_type == "fitment" else 2
        if len(target) >= target_limit:
            return

        savepoint = session.begin_nested()
        try:
            result = apply_product_text_fitment(
                session,
                product,
                applicability_type=applicability_type,
                fitment_rows=fitment_rows,
                persist=True,
            )
            target.append(
                {
                    "default_code": extract_default_code(row),
                    "part_type": product.part_type or "",
                    "make": primary.make if primary else "",
                    "model": primary.model if primary else "",
                    "preview_name": result.name or "",
                }
            )
        except (FitmentValidationError, NamingValidationError) as exc:
            target.append(
                {
                    "default_code": extract_default_code(row),
                    "part_type": product.part_type or "",
                    "make": primary.make if primary else "",
                    "model": primary.model if primary else "",
                    "preview_name": f"[generation error: {exc}]",
                }
            )
        finally:
            savepoint.rollback()
        return

    try:
        apply_product_text_fitment(
            session,
            product,
            applicability_type=applicability_type,
            fitment_rows=fitment_rows,
            persist=True,
        )
        stats.applied += 1
    except (FitmentValidationError, NamingValidationError):
        stats.generation_errors += 1


def run_catalog_jsonl_enrichment(
    jsonl_path: Path,
    *,
    dry_run: bool,
    batch_size: int = 100,
    limit: int | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> EnrichmentStats:
    """
    Match JSONL rows to local products and apply fitment + naming enrichment.

    Creates and closes its own SQLAlchemy session.
    """
    if batch_size < 1:
        raise ValueError("batch_size must be >= 1")

    stats = EnrichmentStats()
    rows = load_jsonl_rows(jsonl_path)
    stats.jsonl_rows = len(rows)
    total_rows = stats.jsonl_rows if limit is None else min(stats.jsonl_rows, limit)
    if on_progress is not None:
        on_progress(0, total_rows)

    apply_schema_patches(engine)
    template_session = SessionLocal()
    try:
        get_template_engine().ensure_loaded(template_session)
    finally:
        template_session.close()

    session = SessionLocal()
    try:
        products = session.scalars(select(Product)).all()
        product_index = build_product_index(list(products))
        matched_product_ids: set[int] = set()

        pending_since_commit = 0
        processed = 0
        row_index = 0

        for row in rows:
            row_index += 1
            if limit is not None and processed >= limit:
                break

            default_code = extract_default_code(row)
            if not default_code:
                if on_progress is not None and (
                    row_index == total_rows or row_index % batch_size == 0
                ):
                    on_progress(row_index, total_rows)
                continue
            stats.jsonl_with_code += 1

            product = None
            for variant in code_variants(default_code):
                product = product_index.get(variant)
                if product is not None:
                    break

            if product is None:
                stats.skipped_no_match += 1
                if on_progress is not None and (
                    row_index == total_rows or row_index % batch_size == 0
                ):
                    on_progress(row_index, total_rows)
                continue

            stats.matched_rows += 1
            matched_product_ids.add(product.id)
            _process_row(session, product, row, dry_run=dry_run, stats=stats)
            processed += 1
            pending_since_commit += 1

            if not dry_run and pending_since_commit >= batch_size:
                session.commit()
                pending_since_commit = 0

            if on_progress is not None and (
                row_index == total_rows or row_index % batch_size == 0
            ):
                on_progress(row_index, total_rows)

        if not dry_run and pending_since_commit:
            session.commit()

        stats.matched_products = len(matched_product_ids)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    mode = "dry-run" if dry_run else "apply"
    logger.info(
        "Catalog JSONL enrichment (%s): rows=%s matched=%s applied=%s errors=%s",
        mode,
        stats.jsonl_rows,
        stats.matched_rows,
        stats.applied,
        stats.generation_errors,
    )
    return stats
