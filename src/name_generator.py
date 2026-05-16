"""Build product names and descriptions from the finalized naming template.

Template (authoritative — supersedes prior behavior):

    NAME: {part_type} {brand} {article[0]} для {make} {model} {body}
          {years} {engine} {side} {characteristics}
    DESC: Применяемость: {fitments}
          Кросс-номера: {article[1:]}

``generate_name()`` is a pure function (no I/O) per project rule
``04_generation.mdc``. The legacy ``template_pattern`` parameter is kept for
signature compatibility but is advisory only — all assembly is performed by
``_assemble_name`` / ``_assemble_description`` below.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Literal

logger = logging.getLogger(__name__)


SKIP_BRANDS: frozenset[str] = frozenset({"", "non", "?", "н/а", "unknown"})

_VAZ_MODEL_RE = re.compile(r"^\d{4,5}$")


@dataclass
class GeneratedName:
    """Result of assembling name and description for MoySklad."""

    name: str
    description: str
    status: Literal["generated", "review", "error"]
    warnings: list[str] = field(default_factory=list)
    missing_fields: list[str] = field(default_factory=list)
    candidate_hash: str = ""


def format_years(year_from: int | None, year_to: int | None) -> str:
    """
    Display helper for year range (public — consumed by ``fitment_repo``).

    Kept for legacy callers that import this symbol (e.g.
    ``fitment_repo.build_fitment_summary``):

    - both set, ``year_to > 0`` → ``"YYYY-YYYY"``
    - ``year_from`` set, ``year_to == 0`` → ``"YYYY-н.в."``
    - only ``year_from`` → ``"с YYYY"``
    - only ``year_to > 0`` → ``"до YYYY"``
    - both ``None`` → ``""``

    The new name/description assembly (finalized spec) uses
    :func:`_years_for_name` instead, which differs for ``year_to == 0``.
    """
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


def _years_for_name(year_from: int | None, year_to: int | None) -> str:
    """Finalized-spec year range used in product name/description.

    - ``year_from`` falsy → ``""``
    - ``year_to`` falsy (``0`` / ``None``) → ``"с {year_from}"``
    - both truthy → ``"{year_from}-{year_to}"``
    """
    if not year_from:
        return ""
    if not year_to:
        return f"с {year_from}"
    return f"{year_from}-{year_to}"


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


def _skip_brand(brand: str) -> bool:
    """True for empty, NON, ?, н/а, unknown (case-insensitive)."""
    return _str(brand).casefold() in SKIP_BRANDS


def _side_already_in_part_type(part_type: str, side: str) -> bool:
    """
    Проверить что сторона уже есть в part_type.

    Примеры:
    "Передние" в "Колодки тормозные Передние" → True
    "Задний" в "Амортизатор Задний" → True
    "Правая" в "Фара (блок) Правая" → True
    "Левый" в "Колодки тормозные Передние" → False
    """
    if not side or not part_type:
        return False
    return side.strip().lower() in part_type.lower()


def _split_article(raw: Any) -> tuple[str, list[str]]:
    """Split ``article`` on ``;`` → ``(primary, cross_numbers)``."""
    s = _str(raw)
    if not s:
        return "", []
    parts = [p.strip() for p in s.split(";") if p.strip()]
    if not parts:
        return "", []
    return parts[0], parts[1:]


def _apply_vaz_model_rule(make: str, model: str) -> str:
    """Prepend ``ВАЗ`` to a bare numeric model when a make is present."""
    if not make or not model:
        return model
    if _VAZ_MODEL_RE.match(model):
        return f"ВАЗ {model}"
    return model


def _assemble_name(tokens: dict, applicability_type: str) -> str:
    parts: list[str] = []

    if tokens["part_type"]:
        parts.append(tokens["part_type"])
    if tokens["brand"]:
        parts.append(tokens["brand"])
    if tokens["article_primary"]:
        parts.append(tokens["article_primary"])

    if applicability_type == "fitment":
        make = tokens["make"]
        model = tokens["model"]
        body = tokens["body"]
        years = tokens["years"]
        engine = tokens["engine"]

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

    if tokens["side"]:
        parts.append(tokens["side"])
    if tokens["characteristics"]:
        parts.append(tokens["characteristics"])

    name = " ".join(parts)
    name = re.sub(r" {2,}", " ", name).strip()
    return name[:255]


def _assemble_description(
    tokens: dict,
    fitment_rows: list[dict],
    applicability_type: str,
) -> str:
    lines: list[str] = []

    if applicability_type == "fitment" and fitment_rows:
        fitment_strings: list[str] = []
        for row in fitment_rows:
            f_make = _str(row.get("make"))
            f_model = _str(row.get("model"))
            f_body = _str(row.get("body"))
            f_years = _years_for_name(
                _coerce_int(row.get("year_from")) or 0,
                _coerce_int(row.get("year_to")) or 0,
            )
            f_engine = _str(row.get("engine"))
            segment = " ".join(
                p for p in (f_make, f_model, f_body, f_years, f_engine) if p
            )
            if segment:
                fitment_strings.append(segment)
        if fitment_strings:
            lines.append("Применяемость: " + ", ".join(fitment_strings))

    if tokens["article_cross"]:
        lines.append("Кросс-номера: " + " | ".join(tokens["article_cross"]))

    return "\n".join(lines)


def _candidate_hash(name: str, description: str) -> str:
    payload = json.dumps(
        {"name": name, "description": description},
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def generate_name(
    product: dict,
    fitment_rows: list[dict],
    template_pattern: str,
) -> GeneratedName:
    """Pure name + description generator (no I/O).

    Parameters
    ----------
    product
        Product dict with fields ``part_type``, ``brand``, ``article``,
        ``applicability_type``, ``primary_make``, ``primary_model``,
        ``primary_body``, ``year_from``, ``year_to``, ``engine``,
        ``side_axis``, ``characteristics``.
    fitment_rows
        All fitments for the product (used only in the description).
    template_pattern
        Kept for signature compatibility — advisory only. Logged at DEBUG
        when non-empty; real assembly is performed by :func:`_assemble_name`.
    """
    if template_pattern:
        logger.debug("generate_name: advisory template_pattern=%s", template_pattern)

    applicability_type = (_str(product.get("applicability_type")) or "universal").lower()
    if applicability_type not in ("fitment", "universal"):
        applicability_type = "universal"

    part_type = _str(product.get("part_type"))

    brand_raw = _str(product.get("brand"))
    brand_skipped = _skip_brand(brand_raw)
    brand = "" if brand_skipped else brand_raw

    article_primary, article_cross = _split_article(product.get("article"))

    make = _str(product.get("primary_make"))
    model_raw = _str(product.get("primary_model"))
    model = _apply_vaz_model_rule(make, model_raw)
    body = _str(product.get("primary_body"))
    years = _years_for_name(
        _coerce_int(product.get("year_from")) or 0,
        _coerce_int(product.get("year_to")) or 0,
    )
    engine = _str(product.get("engine"))
    side = _str(product.get("side_axis"))
    characteristics = _str(product.get("characteristics"))

    tokens: dict[str, Any] = {
        "part_type": part_type,
        "brand": brand,
        "article_primary": article_primary,
        "article_cross": article_cross,
        "make": make,
        "model": model,
        "body": body,
        "years": years,
        "engine": engine,
        "side": side,
        "characteristics": characteristics,
    }

    if _side_already_in_part_type(part_type, side):
        tokens["side"] = ""

    warnings: list[str] = []
    if brand_skipped:
        warnings.append("brand_skipped")
    if not article_primary:
        warnings.append("missing_article")

    name = _assemble_name(tokens, applicability_type)
    description = _assemble_description(tokens, fitment_rows, applicability_type)
    chash = _candidate_hash(name, description)

    if not part_type:
        return GeneratedName(
            name=name,
            description=description,
            status="error",
            warnings=warnings,
            missing_fields=["part_type"],
            candidate_hash=chash,
        )

    status: Literal["generated", "review", "error"]
    if not article_primary or brand_skipped:
        status = "review"
    else:
        status = "generated"

    return GeneratedName(
        name=name,
        description=description,
        status=status,
        warnings=warnings,
        missing_fields=[],
        candidate_hash=chash,
    )
