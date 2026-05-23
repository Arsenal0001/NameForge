"""
Naming engine: template resolution (SQLAlchemy), pure generation, hashing, persistence.

Golden Catalog cleanup (``NAMING_TEMPLATES_V2.md``) lives in :mod:`app.services.text_utils`
(metrics spacing, conditional removal of «универсальн*», SKU out of ``name``, tautology trim).

Supported ``name_pattern`` placeholders (safe empty if missing):
``part_type``, ``installation``, ``brand``, ``article`` / ``article_primary``,
``fitment_core``, ``characteristics``, ``attributes``, ``make``, ``model``, ``body``, ``years``,
``engine``, ``side``, ``cross_numbers``, ``article_cross``, ``dlya_segment``.

- Follows ``04_generation`` rules: primary fitment in description; ``для`` only with make+model;
  ``year_to == 0`` → «н.в.» in auxiliary helpers; names capped at 255 chars.
- JSON-RPC / Odoo push lives elsewhere; this module only computes names for local SQLite rows.

Legacy references: ``src/name_generator.py``, ``src/hash_utils.py``, ``src/template_engine.py``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.fitment import Fitment
from app.models.odoo_catalog_cache import OdooCategory, OdooProductTemplate
from app.models.product import Product
from app.models.template import Template
from app.services.category_template_binding import (
    iter_categories_for_product,
    physical_keys_for_product_matrix,
)
from app.services.text_utils import (
    apply_golden_name_postprocess,
    assemble_search_keywords_line,
    polish_generated_name,
    sanitize_token_value,
    STUB_VALUES,
)
from app.schemas.naming import (
    FitmentNamingInput,
    GeneratedNamingResult,
    NamingExportManifest,
    NamingPreviewRequest,
    ProductNamingInput,
)

logger = logging.getLogger(__name__)


class NamingValidationError(ValueError):
    """Invalid naming inputs (hierarchy, primary fitment rules, etc.)."""


class ProductNotFoundError(LookupError):
    """No ``products`` row for the given id (HTTP 404 at API boundary)."""

    def __init__(self, product_id: int) -> None:
        self.product_id = product_id
        super().__init__(str(product_id))


SKIP_BRANDS: frozenset[str] = STUB_VALUES
_VAZ_MODEL_RE = re.compile(r"^\d{4,5}$")

_DEFAULT_FITMENT_FALLBACK = (
    "{part_type} {installation} {fitment_core} {attributes} {brand}"
)
_DEFAULT_UNIVERSAL_FALLBACK = (
    "{part_type} {installation} {attributes} {brand}"
)



def format_years(year_from: int | None, year_to: int | None) -> str:
    """Legacy-compatible year display for descriptions / summaries."""
    if year_from is None and year_to is None:
        return ""
    if year_from is not None and year_to is not None:
        if year_to > 0:
            return f"{year_from}-{year_to}"
        if year_to == 0:
            return f"{year_from}-н.в."
        return ""
    if year_from is not None:
        return f"с {year_from}"
    if year_to is not None:
        if year_to > 0:
            return f"до {year_to}"
        return "н.в."
    return ""


def years_for_name(year_from: int | None, year_to: int | None) -> str:
    """Compact range inside product ``name`` (legacy ``_years_for_name`` semantics)."""
    yf = int(year_from or 0)
    if not yf:
        return ""
    yt = year_to if year_to is not None else 0
    if not yt:
        return f"с {yf}"
    return f"{yf}-{yt}"


def _str(v: Any) -> str:
    if v is None:
        return ""
    return str(v).strip()


def _coerce_int(v: Any) -> int | None:
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def skip_brand(brand: str) -> bool:
    raw = _str(brand)
    if not raw:
        return True
    return sanitize_token_value(raw) == ""


def side_already_in_part_type(part_type: str, side: str) -> bool:
    if not side or not part_type:
        return False
    return side.strip().lower() in part_type.lower()


def split_article(raw: Any) -> tuple[str, list[str]]:
    s = _str(raw)
    if not s:
        return "", []
    parts = [p.strip() for p in s.split(";") if p.strip()]
    if not parts:
        return "", []
    return parts[0], parts[1:]


def apply_vaz_model_rule(make: str, model: str) -> str:
    if not make or not model:
        return model
    if _VAZ_MODEL_RE.match(model):
        return f"ВАЗ {model}"
    return model


class _SafeFormatDict(dict[str, Any]):
    def __missing__(self, key: str) -> str:
        logger.debug("Naming template missing placeholder {%s} → empty string", key)
        return ""


def compute_source_hash(
    product: Mapping[str, Any],
    fitment_rows: Sequence[Mapping[str, Any]],
    *,
    characteristic_parts: Sequence[str] = (),
) -> str:
    """
    Canonical SHA-256 hex digest (legacy ``hash_utils.compute_source_hash``).

    Optionally folds ordered ``characteristic_parts`` into the payload so local-only
    attributes participate in idempotency when they affect rendered names.
    """

    def scalar(v: Any) -> str:
        if v is None:
            return ""
        return str(v)

    def encode_fitment_row(row: Mapping[str, Any]) -> str:
        return "|".join(
            (
                scalar(row.get("make")),
                scalar(row.get("model")),
                scalar(row.get("body")),
                scalar(row.get("year_from")),
                scalar(row.get("year_to")),
                scalar(row.get("engine")),
            )
        )

    def fitment_sort_key(row: Mapping[str, Any]) -> tuple[str, str, str, str]:
        return (
            scalar(row.get("make")),
            scalar(row.get("model")),
            scalar(row.get("body")),
            scalar(row.get("year_from")),
        )

    universal_keys = (
        "brand",
        "part_type",
        "article",
        "side_axis",
        "cross_numbers",
        "template_key",
        "template_version",
        "applicability_type",
        "supplier_raw_name",
    )
    primary_keys = (
        "primary_make",
        "primary_model",
        "primary_body",
        "year_from",
        "year_to",
        "engine",
    )

    payload: dict[str, Any] = {k: scalar(product.get(k)) for k in universal_keys}

    applicability = payload["applicability_type"]
    if applicability == "fitment":
        for k in primary_keys:
            payload[k] = scalar(product.get(k))
        rows = list(fitment_rows)
        rows.sort(key=fitment_sort_key)
        payload["fitment_segments"] = [encode_fitment_row(r) for r in rows]

    parts = [p.strip() for p in characteristic_parts if _str(p)]
    if parts:
        payload["characteristic_parts"] = "|".join(parts)
    attr_summary = scalar(product.get("attributes_summary"))
    if attr_summary:
        payload["attributes_summary"] = attr_summary

    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _candidate_hash(name: str, description: str, *, search_keywords: str = "") -> str:
    blob = json.dumps(
        {"name": name, "description": description, "search_keywords": search_keywords},
        ensure_ascii=False,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def compute_sync_content_hash(
    *,
    name: str,
    search_keywords: str = "",
    description: str = "",
) -> str:
    """SHA-256 digest of outbound Odoo ``name`` / keywords payload for sync idempotency."""
    return _candidate_hash(name, description, search_keywords=search_keywords)


def _polish_generated_name(name: str) -> str:
    """Collapse stray whitespace after empty template tokens are removed."""
    return polish_generated_name(name)


def _finalize_visible_name(raw: str) -> tuple[str, bool]:
    cleaned = re.sub(r" {2,}", " ", raw).strip()
    if len(cleaned) <= 255:
        return cleaned, False
    return cleaned[:252].rstrip() + "...", True


def _has_wildcard(pattern: str) -> bool:
    return any(ch in pattern for ch in ("*", "?", "["))


def _trigger_blank_clause():
    return or_(
        Template.part_type_trigger.is_(None),
        func.trim(Template.part_type_trigger) == "",
    )


def resolve_active_template_pattern(
    session: Session,
    *,
    template_key: str | None,
    applicability_type: str,
    part_type: str | None,
) -> str | None:
    """
    Resolve ``templates.name_pattern`` mirroring ``src/template_engine.load_active_template``.
    """
    key = _str(template_key) or None
    appl = _str(applicability_type) or "universal"
    pt = _str(part_type) or None

    if pt:
        stmt_trig = (
            select(Template.name_pattern)
            .where(
                Template.applicability_type == appl,
                Template.is_active.is_(True),
                Template.part_type_trigger == pt,
            )
            .order_by(Template.version.desc())
            .limit(1)
        )
        hit = session.scalar(stmt_trig)
        if hit:
            return str(hit)

    if key:
        stmt_key = (
            select(Template.name_pattern)
            .where(
                Template.template_key == key,
                Template.applicability_type == appl,
                Template.is_active.is_(True),
                _trigger_blank_clause(),
            )
            .order_by(Template.version.desc())
            .limit(1)
        )
        hit = session.scalar(stmt_key)
        if hit:
            return str(hit)

    if pt:
        stmt_pat = select(
            Template.name_pattern, Template.part_type_pattern, Template.version
        ).where(
            Template.applicability_type == appl,
            Template.is_active.is_(True),
            Template.part_type_pattern.is_not(None),
            func.trim(Template.part_type_pattern) != "",
        )
        needle = pt.strip().casefold()
        candidates: list[tuple[int, str, int, str]] = []
        if needle:
            for name_pattern, pt_pattern, version in session.execute(stmt_pat):
                pat = _str(pt_pattern)
                if not pat:
                    continue
                pat_cf = pat.casefold()
                if _has_wildcard(pat):
                    if not fnmatchcase(needle, pat_cf):
                        continue
                    specificity = 0
                else:
                    if pat_cf != needle:
                        continue
                    specificity = 1
                ver = _str(version)
                candidates.append((specificity, ver, len(pat_cf), str(name_pattern or "")))

        if candidates:
            candidates.sort(key=lambda t: (t[0], t[1], t[2]), reverse=True)
            return candidates[0][3] or None

    fallback_key = "fitment_base" if appl == "fitment" else "universal_base"
    if key != fallback_key:
        stmt_fb = (
            select(Template.name_pattern)
            .where(
                Template.template_key == fallback_key,
                Template.applicability_type == appl,
                Template.is_active.is_(True),
                _trigger_blank_clause(),
            )
            .order_by(Template.version.desc())
            .limit(1)
        )
        hit = session.scalar(stmt_fb)
        if hit:
            return str(hit)

    return None


NamingStatus = Literal["no_template", "pending_sync", "synced"]


@dataclass(frozen=True, slots=True)
class CategoryCacheEntry:
    """In-memory snapshot of one ``odoo_categories`` row."""

    odoo_id: int
    name: str
    parent_id: int | None
    complete_name: str | None
    naming_template_key: str | None
    name_pattern: str | None = None


@dataclass(frozen=True, slots=True)
class TemplateResolution:
    """Result of cascade template lookup for one product category chain."""

    logical_matrix_id: str | None
    source_category_id: int | None
    template_key: str | None
    template_version: str | None
    name_pattern: str | None
    has_category_template: bool


class TemplateEngine:
    """
    Cascade resolver for Odoo ``product.category`` → naming matrix → SQL ``templates``.

    Category tree is cached in RAM (loaded from ``odoo_categories``). When a leaf
    category has no ``naming_template_key``, the engine walks ``parent_id`` until a
    binding is found or the chain ends (global pattern fallback may still apply).
    """

    def __init__(self) -> None:
        self._by_id: dict[int, CategoryCacheEntry] = {}
        self._loaded = False

    def load_categories(self, session: Session) -> None:
        rows = session.scalars(select(OdooCategory)).all()
        self._by_id = {
            row.odoo_id: CategoryCacheEntry(
                odoo_id=row.odoo_id,
                name=row.name or "",
                parent_id=row.parent_id,
                complete_name=row.complete_name,
                naming_template_key=(row.naming_template_key or "").strip() or None,
                name_pattern=(row.name_pattern or "").strip() or None,
            )
            for row in rows
        }
        self._loaded = True

    def load_from_entries(self, entries: Sequence[CategoryCacheEntry]) -> None:
        """Test helper — populate cache without DB."""
        self._by_id = {entry.odoo_id: entry for entry in entries}
        self._loaded = True

    def ensure_loaded(self, session: Session) -> None:
        if not self._loaded:
            self.load_categories(session)

    def invalidate_cache(self) -> None:
        self._by_id.clear()
        self._loaded = False

    def walk_category_chain(self, categ_id: int | None) -> list[CategoryCacheEntry]:
        chain: list[CategoryCacheEntry] = []
        if categ_id is None:
            return chain
        seen: set[int] = set()
        cid: int | None = categ_id
        while cid is not None and cid not in seen:
            seen.add(cid)
            entry = self._by_id.get(cid)
            if entry is None:
                break
            chain.append(entry)
            cid = entry.parent_id
        return chain

    def resolve_matrix_from_category(
        self, categ_id: int | None
    ) -> tuple[str | None, int | None]:
        """Walk leaf→root; return first non-empty ``naming_template_key``."""
        for entry in self.walk_category_chain(categ_id):
            if entry.naming_template_key:
                return entry.naming_template_key, entry.odoo_id
        return None, None

    def resolve_custom_pattern_from_category(
        self, categ_id: int | None
    ) -> tuple[str | None, int | None]:
        """Walk leaf→root; return first non-empty operator ``name_pattern``."""
        for entry in self.walk_category_chain(categ_id):
            if entry.name_pattern:
                return entry.name_pattern, entry.odoo_id
        return None, None

    def resolve_categ_id_for_product(
        self, session: Session, product: Product, *, categ_id: int | None = None
    ) -> int | None:
        if categ_id is not None:
            return categ_id
        oid_raw = (product.odoo_product_id or "").strip()
        if oid_raw.isdigit():
            tpl = session.get(OdooProductTemplate, int(oid_raw))
            if tpl is not None and tpl.categ_id is not None:
                return tpl.categ_id
        for cat in iter_categories_for_product(session, product):
            return cat.odoo_id
        return None

    def resolve_for_product(
        self,
        session: Session,
        product: Product,
        *,
        categ_id: int | None = None,
    ) -> TemplateResolution:
        self.ensure_loaded(session)
        resolved_categ = self.resolve_categ_id_for_product(
            session, product, categ_id=categ_id
        )
        custom_pattern, custom_src = self.resolve_custom_pattern_from_category(
            resolved_categ
        )
        matrix_id, src_cat = self.resolve_matrix_from_category(resolved_categ)

        appl_raw = _str(product.applicability_type).lower()
        applicability = "fitment" if appl_raw == "fitment" else "universal"

        template_key: str | None = None
        template_version: str | None = None
        pattern: str | None = None

        if custom_pattern:
            pattern = custom_pattern
            src_cat = custom_src
        else:
            if matrix_id:
                phys = physical_keys_for_product_matrix(
                    session,
                    logical_matrix_id=matrix_id,
                    applicability_type=applicability,
                )
                if phys:
                    template_key, template_version = phys

            pattern = resolve_active_template_pattern(
                session,
                template_key=template_key,
                applicability_type=applicability,
                part_type=_str(product.part_type) or None,
            )

        return TemplateResolution(
            logical_matrix_id=matrix_id,
            source_category_id=src_cat,
            template_key=template_key,
            template_version=template_version,
            name_pattern=pattern,
            has_category_template=bool(custom_pattern or matrix_id),
        )


_template_engine = TemplateEngine()


def get_template_engine() -> TemplateEngine:
    return _template_engine


def compute_naming_status(
    *,
    has_category_template: bool,
    preview_name: str,
    odoo_name: str,
) -> NamingStatus:
    if not has_category_template:
        return "no_template"
    pn = preview_name.strip()
    on = odoo_name.strip()
    if pn and on and pn == on:
        return "synced"
    return "pending_sync"


def generate_preview_for_product(
    session: Session,
    product: Product,
    *,
    engine: TemplateEngine | None = None,
    categ_id: int | None = None,
) -> tuple[GeneratedNamingResult | None, TemplateResolution]:
    """
    Run naming for a loaded product without persistence (spreadsheet preview).

    Returns ``(result, resolution)``. ``result`` is ``None`` on validation errors.
    """
    eng = engine or get_template_engine()
    resolution = eng.resolve_for_product(session, product, categ_id=categ_id)

    fit_orm = sorted(product.fitments, key=lambda f: (f.sort_order, f.id))
    fit_inputs = fitments_from_orm(fit_orm)

    appl = _str(product.applicability_type).lower()
    if appl == "fitment" and not fit_inputs:
        mk = _str(product.primary_make)
        md = _str(product.primary_model)
        if mk or md:
            fit_inputs = [
                FitmentNamingInput(
                    make=mk,
                    model=md,
                    body=product.primary_body,
                    year_from=product.year_from,
                    year_to=product.year_to,
                    engine=product.engine,
                    is_primary=True,
                )
            ]
        else:
            return None, resolution

    try:
        primary = select_primary_fitment(product.applicability_type, fit_inputs)
    except NamingValidationError:
        return None, resolution

    inp = product_from_orm(product)
    if resolution.template_key and resolution.template_version:
        inp = inp.model_copy(
            update={
                "template_key": resolution.template_key,
                "template_version": resolution.template_version,
            }
        )

    result = generate_naming_result(
        pattern=resolution.name_pattern,
        inp=inp,
        fitments=fit_inputs if appl == "fitment" else [],
        primary=primary if appl == "fitment" else None,
    )
    return result, resolution


def fitments_from_orm(rows: Iterable[Fitment]) -> list[FitmentNamingInput]:
    out: list[FitmentNamingInput] = []
    for r in rows:
        out.append(
            FitmentNamingInput(
                make=r.make,
                model=r.model,
                body=r.body,
                year_from=r.year_from,
                year_to=r.year_to,
                engine=r.engine,
                is_primary=bool(r.is_primary),
            )
        )
    return out


def select_primary_fitment(
    applicability: str, fitments: Sequence[FitmentNamingInput]
) -> FitmentNamingInput | None:
    if applicability != "fitment":
        return None
    primaries = [f for f in fitments if f.is_primary]
    if len(primaries) != 1:
        raise NamingValidationError(
            "Для applicability_type=fitment нужен ровно один fitment с is_primary=True "
            f"(сейчас {len(primaries)})"
        )
    return primaries[0]


def product_from_orm(
    p: Product,
    *,
    characteristic_parts: Sequence[str] | None = None,
    installation_location: str | None = None,
) -> ProductNamingInput:
    appl_raw = _str(p.applicability_type).lower()
    appl: Literal["fitment", "universal"]
    if appl_raw == "fitment":
        appl = "fitment"
    else:
        appl = "universal"
    parts = list(characteristic_parts) if characteristic_parts is not None else []
    attr_summary = _str(getattr(p, "attribute_summary", None))
    return ProductNamingInput(
        part_type=p.part_type,
        brand=p.brand,
        article=p.article,
        applicability_type=appl,
        template_key=p.template_key,
        template_version=p.template_version,
        side_axis=p.side_axis,
        cross_numbers=p.cross_numbers,
        primary_make=p.primary_make,
        primary_model=p.primary_model,
        primary_body=p.primary_body,
        year_from=p.year_from,
        year_to=p.year_to,
        engine=p.engine,
        installation_location=installation_location,
        characteristic_parts=parts,
        attributes_summary=attr_summary,
        supplier_raw_name=p.supplier_raw_name,
    )


def product_input_to_hash_dict(inp: ProductNamingInput) -> dict[str, Any]:
    return {
        "brand": inp.brand,
        "part_type": inp.part_type,
        "article": inp.article,
        "side_axis": inp.side_axis,
        "cross_numbers": inp.cross_numbers,
        "template_key": inp.template_key,
        "template_version": inp.template_version,
        "applicability_type": inp.applicability_type,
        "primary_make": inp.primary_make,
        "primary_model": inp.primary_model,
        "primary_body": inp.primary_body,
        "year_from": inp.year_from,
        "year_to": inp.year_to,
        "engine": inp.engine,
        "supplier_raw_name": inp.supplier_raw_name,
        "attributes_summary": inp.attributes_summary,
    }


def fitment_inputs_to_hash_rows(
    rows: Sequence[FitmentNamingInput],
) -> list[dict[str, Any]]:
    return [
        {
            "make": r.make,
            "model": r.model,
            "body": r.body,
            "year_from": r.year_from,
            "year_to": r.year_to,
            "engine": r.engine,
        }
        for r in rows
    ]


def build_fitment_core_phrase(inp: ProductNamingInput, primary: FitmentNamingInput | None) -> str:
    """«для …» segment + body/years/engine when applicability is fitment."""
    if inp.applicability_type != "fitment":
        return ""

    if primary is not None:
        make = sanitize_token_value(_str(primary.make))
        model_raw = sanitize_token_value(_str(primary.model))
        model = apply_vaz_model_rule(make, model_raw)
        body = sanitize_token_value(_str(primary.body))
        years = sanitize_token_value(years_for_name(primary.year_from, primary.year_to))
        engine = sanitize_token_value(_str(primary.engine))
    else:
        make = sanitize_token_value(_str(inp.primary_make))
        model = apply_vaz_model_rule(make, sanitize_token_value(_str(inp.primary_model)))
        body = sanitize_token_value(_str(inp.primary_body))
        years = sanitize_token_value(years_for_name(inp.year_from, inp.year_to))
        engine = sanitize_token_value(_str(inp.engine))

    parts: list[str] = []
    if make and model:
        if model == make or model.startswith(make + " "):
            parts.append(f"для {model}")
        else:
            parts.append(f"для {make} {model}")
    elif model:
        parts.append(model)
    if body:
        parts.append(body)
    if years:
        parts.append(years)
    if engine:
        parts.append(engine)
    return " ".join(parts).strip()


def build_characteristics_segment(inp: ProductNamingInput) -> str:
    chunks: list[str] = []
    attr_summary = sanitize_token_value(_str(inp.attributes_summary))
    if attr_summary:
        chunks.append(attr_summary)

    side = sanitize_token_value(_str(inp.side_axis))
    if side and not side_already_in_part_type(inp.part_type, side):
        chunks.append(side)
    for part in inp.characteristic_parts:
        sanitized = sanitize_token_value(_str(part))
        if sanitized and sanitized not in chunks:
            chunks.append(sanitized)
    return " ".join(chunks).strip()


def build_format_tokens(
    inp: ProductNamingInput,
    primary: FitmentNamingInput | None,
    *,
    brand_skipped: bool,
    article_primary: str,
    article_cross: list[str],
) -> dict[str, str]:
    attr_line = sanitize_token_value(_str(inp.attributes_summary))
    side = sanitize_token_value(_str(inp.side_axis))
    side_chunk = (
        side
        if side and not side_already_in_part_type(inp.part_type, side)
        else ""
    )
    extra_parts = [
        sanitized
        for part in inp.characteristic_parts
        if (sanitized := sanitize_token_value(_str(part)))
        and sanitized != attr_line
    ]
    legacy_chars = " ".join(p for p in (side_chunk, *extra_parts) if p).strip()
    if attr_line and legacy_chars:
        characteristics = _polish_generated_name(f"{legacy_chars} {attr_line}")
    else:
        characteristics = attr_line or legacy_chars

    brand_val = "" if brand_skipped else sanitize_token_value(_str(inp.brand))
    installation = sanitize_token_value(_str(inp.installation_location))
    fit_core = build_fitment_core_phrase(inp, primary)

    make_t = model_t = body_t = years_t = engine_t = ""
    if inp.applicability_type == "fitment":
        if primary is not None:
            make_t = sanitize_token_value(_str(primary.make))
            model_t = sanitize_token_value(
                apply_vaz_model_rule(make_t, _str(primary.model))
            )
            body_t = sanitize_token_value(_str(primary.body))
            years_t = sanitize_token_value(
                years_for_name(primary.year_from, primary.year_to)
            )
            engine_t = sanitize_token_value(_str(primary.engine))
        else:
            make_t = sanitize_token_value(_str(inp.primary_make))
            model_t = sanitize_token_value(
                apply_vaz_model_rule(make_t, _str(inp.primary_model))
            )
            body_t = sanitize_token_value(_str(inp.primary_body))
            years_t = sanitize_token_value(
                years_for_name(inp.year_from, inp.year_to)
            )
            engine_t = sanitize_token_value(_str(inp.engine))

    dlya_phrase = ""
    if make_t and model_t:
        if model_t == make_t or model_t.startswith(make_t + " "):
            dlya_phrase = f"для {model_t}"
        else:
            dlya_phrase = f"для {make_t} {model_t}"
    elif model_t:
        dlya_phrase = model_t

    side_raw = _str(inp.side_axis)
    side_val = (
        ""
        if side_already_in_part_type(inp.part_type, side_raw)
        else sanitize_token_value(side_raw)
    )

    tokens: dict[str, str] = {
        "part_type": sanitize_token_value(_str(inp.part_type)),
        "brand": brand_val,
        "article_primary": sanitize_token_value(article_primary),
        "article": sanitize_token_value(article_primary),
        "installation": installation,
        "characteristics": characteristics,
        "attributes": attr_line,
        "fitment_core": fit_core,
        "make": make_t,
        "model": model_t,
        "body": body_t,
        "years": years_t,
        "engine": engine_t,
        "side": side_val,
        "cross_numbers": sanitize_token_value(_str(inp.cross_numbers)),
        "article_cross": sanitize_token_value(
            " | ".join(article_cross) if article_cross else ""
        ),
        "dlya_segment": dlya_phrase,
    }
    return tokens


def render_name_pattern(pattern: str, tokens: Mapping[str, str]) -> str:
    try:
        rendered = pattern.format_map(_SafeFormatDict(tokens))
    except Exception as exc:
        raise NamingValidationError(f"Шаблон имени некорректен: {exc}") from exc
    return rendered


def render_with_fallback_structure(inp: ProductNamingInput, tokens: Mapping[str, str]) -> str:
    skeleton = (
        _DEFAULT_FITMENT_FALLBACK
        if inp.applicability_type == "fitment"
        else _DEFAULT_UNIVERSAL_FALLBACK
    )
    return render_name_pattern(skeleton, tokens)


def build_description(
    inp: ProductNamingInput,
    fitments: Sequence[FitmentNamingInput],
    article_cross: list[str],
) -> str:
    lines: list[str] = []
    if inp.applicability_type == "fitment" and fitments:
        fit_strings: list[str] = []
        for row in fitments:
            yf = _coerce_int(row.year_from) or 0
            yt_raw = _coerce_int(row.year_to)
            yt = yt_raw if yt_raw is not None else 0
            yr = years_for_name(yf, yt)
            segment = " ".join(
                p
                for p in (
                    _str(row.make),
                    _str(row.model),
                    _str(row.body),
                    yr,
                    _str(row.engine),
                )
                if p
            )
            if segment:
                fit_strings.append(segment)
        if fit_strings:
            lines.append("Применяемость: " + ", ".join(fit_strings))
    if article_cross:
        lines.append("Кросс-номера: " + " | ".join(article_cross))
    return "\n".join(lines)


def generate_naming_result(
    *,
    pattern: str | None,
    inp: ProductNamingInput,
    fitments: Sequence[FitmentNamingInput],
    primary: FitmentNamingInput | None,
) -> GeneratedNamingResult:
    """
    Pure naming pipeline (no DB). Validates via Pydantic on return model.

    ``pattern`` comes from :func:`resolve_active_template_pattern`; when ``None``,
    falls back to structured formula tokens (NAMING_TEMPLATES-style ordering).
    """
    warnings: list[str] = []
    missing: list[str] = []

    brand_raw = _str(inp.brand)
    brand_skip = skip_brand(brand_raw)
    if brand_skip:
        warnings.append("brand_skipped")

    article_primary, article_cross = split_article(inp.article)
    if not article_primary:
        warnings.append("missing_article")

    hash_rows = fitment_inputs_to_hash_rows(fitments)
    source_hash = compute_source_hash(
        product_input_to_hash_dict(inp),
        hash_rows,
        characteristic_parts=tuple(inp.characteristic_parts),
    )

    if not _str(inp.part_type):
        return GeneratedNamingResult(
            name="",
            search_keywords="",
            description="",
            status="error",
            source_hash=source_hash,
            warnings=warnings,
            missing_fields=["part_type"],
            template_pattern_used=pattern,
        )

    tokens = build_format_tokens(
        inp,
        primary,
        brand_skipped=brand_skip,
        article_primary=article_primary,
        article_cross=article_cross,
    )

    chosen_pattern = pattern
    active_pattern = ""
    if chosen_pattern and chosen_pattern.strip():
        active_pattern = chosen_pattern.strip()
        raw_name = render_name_pattern(active_pattern, tokens)
    else:
        chosen_pattern = None
        active_pattern = (
            _DEFAULT_FITMENT_FALLBACK
            if inp.applicability_type == "fitment"
            else _DEFAULT_UNIVERSAL_FALLBACK
        )
        raw_name = render_with_fallback_structure(inp, tokens)

    raw_name = _polish_generated_name(raw_name)
    cleaned_name = apply_golden_name_postprocess(
        raw_name,
        part_type=_str(inp.part_type),
        article_primary=article_primary,
    )
    name, truncated = _finalize_visible_name(cleaned_name)
    description = build_description(inp, fitments, article_cross)

    kw_chunks: list[str] = []
    if article_primary:
        kw_chunks.append(article_primary)
    kw_chunks.extend(article_cross)
    cn = _str(inp.cross_numbers)
    if cn:
        kw_chunks.append(cn)
    kw_chunks.extend(str(p) for p in inp.characteristic_parts if _str(p))
    sr = _str(inp.supplier_raw_name)
    if sr:
        kw_chunks.append(sr)
    search_keywords = assemble_search_keywords_line(kw_chunks)

    if brand_skip or not article_primary:
        status: Literal["generated", "review", "error"] = "review"
    else:
        status = "generated"

    return GeneratedNamingResult(
        name=name,
        search_keywords=search_keywords,
        description=description,
        status=status,
        source_hash=source_hash,
        warnings=warnings,
        missing_fields=missing,
        template_pattern_used=chosen_pattern,
        truncated=truncated,
    )


def preview_naming(request: NamingPreviewRequest) -> GeneratedNamingResult:
    """
    Pure naming preview — no DB or Odoo I/O.

    Builds :class:`ProductNamingInput` from the request DTO and delegates to
    :func:`generate_naming_result`. When ``applicability_type`` is ``fitment`` and
    ``fitments`` is empty, synthesizes a single primary row from ``primary_*`` fields.
    """
    inp = ProductNamingInput(
        part_type=request.part_type,
        brand=request.brand,
        article=request.article,
        applicability_type=request.applicability_type,
        side_axis=request.side_axis,
        cross_numbers=request.cross_numbers,
        primary_make=request.primary_make,
        primary_model=request.primary_model,
        primary_body=request.primary_body,
        year_from=request.year_from,
        year_to=request.year_to,
        engine=request.engine,
        installation_location=request.installation_location,
        characteristic_parts=list(request.characteristic_parts),
        supplier_raw_name=request.supplier_raw_name,
    )

    fitments = list(request.fitments)
    if inp.applicability_type == "fitment":
        if not fitments:
            mk = _str(inp.primary_make)
            md = _str(inp.primary_model)
            if not mk and not md:
                raise NamingValidationError(
                    "Для fitment нужны primary_make/primary_model или fitments[]"
                )
            fitments = [
                FitmentNamingInput(
                    make=mk,
                    model=md,
                    body=inp.primary_body,
                    year_from=inp.year_from,
                    year_to=inp.year_to,
                    engine=inp.engine,
                    is_primary=True,
                )
            ]
        primary = select_primary_fitment(inp.applicability_type, fitments)
    else:
        primary = None
        fitments = []

    return generate_naming_result(
        pattern=request.template_pattern,
        inp=inp,
        fitments=fitments,
        primary=primary,
    )


def export_naming_result(
    result: GeneratedNamingResult,
    *,
    product_id: int,
    directory: Path,
    include_candidate_hash: bool = True,
) -> NamingExportManifest:
    """
    Persist naming output as JSON + txt for cheap downstream LLM / audit pipelines.

    JSON is UTF-8 with Python-compatible keys; txt repeats key facts without JSON overhead.
    """
    directory.mkdir(parents=True, exist_ok=True)
    stem = directory / (
        f"product_{product_id}_naming_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    )
    json_path = stem.with_suffix(".json")
    txt_path = stem.with_suffix(".txt")

    payload = result.model_dump()
    if include_candidate_hash:
        payload["candidate_hash"] = _candidate_hash(
            result.name,
            result.description,
            search_keywords=result.search_keywords,
        )

    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        f"name={result.name}",
        f"search_keywords={result.search_keywords}",
        f"status={result.status}",
        f"source_hash={result.source_hash}",
        f"template_pattern_used={result.template_pattern_used!r}",
        f"truncated={result.truncated}",
        "",
        "[description]",
        result.description or "",
        "",
        "[warnings]",
        "; ".join(result.warnings) if result.warnings else "",
        "",
        "[missing_fields]",
        "; ".join(result.missing_fields) if result.missing_fields else "",
    ]
    if include_candidate_hash:
        lines.extend(
            [
                "",
                f"candidate_hash={_candidate_hash(result.name, result.description, search_keywords=result.search_keywords)}",
            ]
        )

    txt_path.write_text("\n".join(lines), encoding="utf-8")

    return NamingExportManifest(json_path=str(json_path), txt_path=str(txt_path))


def persist_generation_result(session: Session, product: Product, result: GeneratedNamingResult) -> bool:
    """
    Write ``generated_name`` / ``search_keywords`` / ``source_hash`` / status fields when allowed.

    Returns ``True`` if the ORM instance was mutated (caller should ``commit``).

    Returns ``False`` when ``name_locked`` is set (no overwrite) or when stored outcome
    is already identical (idempotent ``source_hash`` + same ``name`` and ``search_keywords``).
    """
    if product.name_locked:
        logger.info("Skip persist: product id=%s name_locked", product.id)
        return False
    sk_new = (result.search_keywords or "").strip()
    sk_old = (product.search_keywords or "").strip()
    if (
        result.source_hash
        and (product.source_hash or "") == result.source_hash
        and (product.generated_name or "") == result.name
        and sk_old == sk_new
        and result.status != "error"
    ):
        return False

    if result.status == "error":
        product.generation_status = "error"
        product.error_message = (
            ", ".join(result.missing_fields) if result.missing_fields else "generation error"
        )[:2048]
        return True

    product.generated_name = result.name
    product.search_keywords = sk_new if sk_new else None
    product.source_hash = result.source_hash or product.source_hash
    product.error_message = None
    product.generation_status = "review"
    return True


def generate_for_loaded_product(
    session: Session,
    product: Product,
    *,
    characteristic_parts: Sequence[str] | None = None,
    installation_location: str | None = None,
    persist: bool = False,
    export_dir: Path | None = None,
) -> GeneratedNamingResult:
    """
    Run naming for an already-loaded ``Product`` (raises :class:`NamingValidationError`).

    Optional persistence respects :func:`persist_generation_result` rules.
    """
    fit_orm = sorted(product.fitments, key=lambda f: (f.sort_order, f.id))
    fit_inputs = fitments_from_orm(fit_orm)

    appl = _str(product.applicability_type).lower()
    if appl == "fitment" and not fit_inputs:
        mk = _str(product.primary_make)
        md = _str(product.primary_model)
        if mk or md:
            fit_inputs = [
                FitmentNamingInput(
                    make=mk,
                    model=md,
                    body=product.primary_body,
                    year_from=product.year_from,
                    year_to=product.year_to,
                    engine=product.engine,
                    is_primary=True,
                )
            ]
        else:
            raise NamingValidationError(
                "Для fitment-товаров нужна хотя бы одна строка применяемости"
            )

    primary = select_primary_fitment(product.applicability_type, fit_inputs)

    inp = product_from_orm(
        product,
        characteristic_parts=characteristic_parts,
        installation_location=installation_location,
    )

    eng = get_template_engine()
    resolution = eng.resolve_for_product(session, product)
    if resolution.template_key and resolution.template_version:
        inp = inp.model_copy(
            update={
                "template_key": resolution.template_key,
                "template_version": resolution.template_version,
            }
        )

    result = generate_naming_result(
        pattern=resolution.name_pattern,
        inp=inp,
        fitments=fit_inputs if appl == "fitment" else [],
        primary=primary if appl == "fitment" else None,
    )
    if export_dir is not None:
        export_naming_result(result, product_id=product.id, directory=export_dir)

    if persist:
        if persist_generation_result(session, product, result):
            session.add(product)

    return result


def generate_for_product(
    session: Session,
    product_id: int,
    *,
    characteristic_parts: Sequence[str] | None = None,
    installation_location: str | None = None,
    persist: bool = False,
    export_dir: Path | None = None,
) -> GeneratedNamingResult:
    """Load product by id then delegate to :func:`generate_for_loaded_product`."""
    product = session.get(Product, product_id)
    if product is None:
        raise ProductNotFoundError(product_id)
    return generate_for_loaded_product(
        session,
        product,
        characteristic_parts=characteristic_parts,
        installation_location=installation_location,
        persist=persist,
        export_dir=export_dir,
    )

