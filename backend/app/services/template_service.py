"""
Naming engine: template resolution (SQLAlchemy), pure generation, hashing, persistence.

Golden Catalog cleanup (``NAMING_TEMPLATES_V2.md``) lives in :mod:`app.services.text_utils`
(metrics spacing, conditional removal of «универсальн*», SKU out of ``name``, tautology trim).

Supported ``name_pattern`` placeholders (safe empty if missing):
``part_type``, ``installation``, ``brand``, ``article`` / ``article_primary``,
``fitment_core``, ``characteristics``, ``make``, ``model``, ``body``, ``years``,
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
from datetime import UTC, datetime
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.fitment import Fitment
from app.models.product import Product
from app.models.template import Template
from app.services.category_template_binding import (
    physical_keys_for_product_matrix,
    resolve_logical_matrix_id,
)
from app.services.text_utils import (
    apply_golden_name_postprocess,
    assemble_search_keywords_line,
)
from app.schemas.naming import (
    FitmentNamingInput,
    GeneratedNamingResult,
    NamingExportManifest,
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


SKIP_BRANDS: frozenset[str] = frozenset({"", "non", "?", "н/а", "unknown"})
_VAZ_MODEL_RE = re.compile(r"^\d{4,5}$")

_DEFAULT_FITMENT_FALLBACK = (
    "{part_type} {installation} {fitment_core} {characteristics} {brand}"
)
_DEFAULT_UNIVERSAL_FALLBACK = (
    "{part_type} {installation} {characteristics} {brand}"
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
    return _str(brand).casefold() in SKIP_BRANDS


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

    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _candidate_hash(name: str, description: str, *, search_keywords: str = "") -> str:
    blob = json.dumps(
        {"name": name, "description": description, "search_keywords": search_keywords},
        ensure_ascii=False,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


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
        make = _str(primary.make)
        model_raw = _str(primary.model)
        model = apply_vaz_model_rule(make, model_raw)
        body = _str(primary.body)
        years = years_for_name(primary.year_from, primary.year_to)
        engine = _str(primary.engine)
    else:
        make = _str(inp.primary_make)
        model = apply_vaz_model_rule(make, _str(inp.primary_model))
        body = _str(inp.primary_body)
        years = years_for_name(inp.year_from, inp.year_to)
        engine = _str(inp.engine)

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
    side = _str(inp.side_axis)
    if side and not side_already_in_part_type(inp.part_type, side):
        chunks.append(side)
    chunks.extend(p for p in inp.characteristic_parts if _str(p))
    return " ".join(chunks).strip()


def build_format_tokens(
    inp: ProductNamingInput,
    primary: FitmentNamingInput | None,
    *,
    brand_skipped: bool,
    article_primary: str,
    article_cross: list[str],
) -> dict[str, str]:
    brand_val = "" if brand_skipped else _str(inp.brand)
    installation = _str(inp.installation_location)
    chars = build_characteristics_segment(inp)
    fit_core = build_fitment_core_phrase(inp, primary)

    make_t = model_t = body_t = years_t = engine_t = ""
    if inp.applicability_type == "fitment":
        if primary is not None:
            make_t = _str(primary.make)
            model_t = apply_vaz_model_rule(make_t, _str(primary.model))
            body_t = _str(primary.body)
            years_t = years_for_name(primary.year_from, primary.year_to)
            engine_t = _str(primary.engine)
        else:
            make_t = _str(inp.primary_make)
            model_t = apply_vaz_model_rule(make_t, _str(inp.primary_model))
            body_t = _str(inp.primary_body)
            years_t = years_for_name(inp.year_from, inp.year_to)
            engine_t = _str(inp.engine)

    dlya_phrase = ""
    if make_t and model_t:
        if model_t == make_t or model_t.startswith(make_t + " "):
            dlya_phrase = f"для {model_t}"
        else:
            dlya_phrase = f"для {make_t} {model_t}"
    elif model_t:
        dlya_phrase = model_t

    tokens: dict[str, str] = {
        "part_type": _str(inp.part_type),
        "brand": brand_val,
        "article_primary": article_primary,
        "article": article_primary,
        "installation": installation,
        "characteristics": chars,
        "fitment_core": fit_core,
        "make": make_t,
        "model": model_t,
        "body": body_t,
        "years": years_t,
        "engine": engine_t,
        "side": ""
        if side_already_in_part_type(inp.part_type, _str(inp.side_axis))
        else _str(inp.side_axis),
        "cross_numbers": _str(inp.cross_numbers),
        "article_cross": " | ".join(article_cross) if article_cross else "",
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
    if chosen_pattern and chosen_pattern.strip():
        raw_name = render_name_pattern(chosen_pattern.strip(), tokens)
    else:
        chosen_pattern = None
        raw_name = render_with_fallback_structure(inp, tokens)

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

    if _str(product.applicability_type).lower() == "fitment" and not fit_inputs:
        raise NamingValidationError(
            "Для fitment-товаров нужна хотя бы одна строка применяемости"
        )

    primary = select_primary_fitment(product.applicability_type, fit_inputs)

    inp = product_from_orm(
        product,
        characteristic_parts=characteristic_parts,
        installation_location=installation_location,
    )

    logical_matrix = resolve_logical_matrix_id(session, product)
    if logical_matrix:
        phys = physical_keys_for_product_matrix(
            session,
            logical_matrix_id=logical_matrix,
            applicability_type=inp.applicability_type,
        )
        if phys:
            tk, tv = phys
            inp = inp.model_copy(update={"template_key": tk, "template_version": tv})

    pattern = resolve_active_template_pattern(
        session,
        template_key=inp.template_key or None,
        applicability_type=inp.applicability_type,
        part_type=inp.part_type or None,
    )

    result = generate_naming_result(
        pattern=pattern,
        inp=inp,
        fitments=fit_inputs,
        primary=primary,
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

