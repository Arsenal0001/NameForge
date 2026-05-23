"""Live preview: sample Odoo products + ad-hoc template string (read-only)."""

from __future__ import annotations

import logging
import re
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.odoo_catalog_cache import OdooCategory, OdooProductTemplate
from app.models.product import Product
from app.schemas.naming import FitmentNamingInput, ProductNamingInput
from app.schemas.template import TemplateLivePreviewItem, TemplateLivePreviewResponse
from app.services.odoo_client import OdooClient, OdooClientError
from app.services.template_service import (
    NamingValidationError,
    build_format_tokens,
    fitments_from_orm,
    generate_naming_result,
    product_from_orm,
    render_name_pattern,
    select_primary_fitment,
    skip_brand,
    split_article,
)

logger = logging.getLogger(__name__)

_BRACKET_TOKEN_RE = re.compile(
    r"\[(?P<token>[a-zA-Z0-9_]+)(?:\s*\|\s*(?P<mod>upper|lower))?\]",
    re.IGNORECASE,
)

_TOKEN_ALIASES: dict[str, str] = {
    "x_brand": "brand",
    "x_model": "model",
    "x_make": "make",
    "x_part_type": "part_type",
}


def normalize_template_string(raw: str) -> str:
    """
    Convert bracket tokens to ``{token}`` placeholders understood by the naming engine.

    Supports ``[brand | upper]`` style hints (modifier applied at token build time).
    """

    def repl(match: re.Match[str]) -> str:
        token = match.group("token").strip()
        token = _TOKEN_ALIASES.get(token, token)
        return "{" + token + "}"

    text = _BRACKET_TOKEN_RE.sub(repl, raw.strip())
    return re.sub(r"\s+", " ", text).strip()


def _token_modifiers(raw: str) -> dict[str, str]:
    mods: dict[str, str] = {}
    for match in _BRACKET_TOKEN_RE.finditer(raw):
        token = match.group("token").strip()
        token = _TOKEN_ALIASES.get(token, token)
        mod = (match.group("mod") or "").strip().lower()
        if mod:
            mods[token] = mod
    return mods


def _apply_token_modifiers(tokens: dict[str, str], mods: dict[str, str]) -> dict[str, str]:
    if not mods:
        return tokens
    out = dict(tokens)
    alias = {
        "x_brand": "brand",
        "x_model": "model",
        "x_make": "make",
    }
    for raw_key, mod in mods.items():
        key = alias.get(raw_key, raw_key)
        if key not in out:
            continue
        val = out[key]
        if mod == "upper":
            out[key] = val.upper()
        elif mod == "lower":
            out[key] = val.lower()
    return out


def _child_category_ids(session: Session, root_id: int) -> set[int]:
    rows = session.scalars(select(OdooCategory)).all()
    by_parent: dict[int | None, list[int]] = {}
    for row in rows:
        by_parent.setdefault(row.parent_id, []).append(row.odoo_id)

    ids: set[int] = {root_id}
    stack = [root_id]
    while stack:
        cid = stack.pop()
        for child in by_parent.get(cid, []):
            if child not in ids:
                ids.add(child)
                stack.append(child)
    return ids


def fetch_sample_products_from_cache(
    session: Session,
    category_id: int,
    *,
    limit: int = 3,
) -> list[dict[str, Any]]:
    categ_ids = _child_category_ids(session, category_id)
    stmt = (
        select(OdooProductTemplate)
        .where(OdooProductTemplate.categ_id.in_(categ_ids))
        .order_by(func.random())
        .limit(limit)
    )
    rows = session.scalars(stmt).all()
    return [
        {
            "id": row.odoo_id,
            "name": row.name,
            "default_code": row.default_code,
            "categ_id": row.categ_id,
        }
        for row in rows
    ]


def fetch_sample_products_from_odoo(
    category_id: int,
    *,
    limit: int = 3,
    client: OdooClient | None = None,
) -> list[dict[str, Any]]:
    odoo = client or OdooClient()
    return odoo.search_product_templates_by_category(
        category_id,
        limit=limit,
        fields=["id", "name", "default_code", "categ_id"],
    )


def fetch_sample_products(
    session: Session,
    category_id: int,
    *,
    limit: int = 3,
    client: OdooClient | None = None,
) -> tuple[list[dict[str, Any]], Literal["cache", "odoo", "mixed"]]:
    cached = fetch_sample_products_from_cache(session, category_id, limit=limit)
    if len(cached) >= limit:
        return cached[:limit], "cache"

    seen = {int(r["id"]) for r in cached if r.get("id") is not None}
    try:
        live = fetch_sample_products_from_odoo(
            category_id, limit=limit * 3, client=client
        )
    except OdooClientError as exc:
        logger.warning("Odoo sample read failed for categ=%s: %s", category_id, exc)
        return cached, "cache" if cached else "odoo"

    merged = list(cached)
    for row in live:
        rid = row.get("id")
        if rid is None:
            continue
        try:
            oid = int(rid)
        except (TypeError, ValueError):
            continue
        if oid in seen:
            continue
        seen.add(oid)
        merged.append(row)
        if len(merged) >= limit:
            break

    if not merged:
        return [], "odoo"
    if cached and len(cached) < len(merged):
        return merged[:limit], "mixed"
    if cached:
        return merged[:limit], "cache"
    return merged[:limit], "odoo"


def _naming_inputs_for_odoo_row(
    session: Session,
    row: dict[str, Any],
    *,
    category_name: str,
) -> tuple[ProductNamingInput, list[FitmentNamingInput], FitmentNamingInput | None]:
    odoo_id_raw = row.get("id")
    local: Product | None = None
    if odoo_id_raw is not None:
        local = session.scalar(
            select(Product).where(Product.odoo_product_id == str(odoo_id_raw)).limit(1)
        )

    if local is not None:
        inp = product_from_orm(local)
        fit_orm = sorted(local.fitments, key=lambda f: (f.sort_order, f.id))
        fit_inputs = fitments_from_orm(fit_orm)
        appl = inp.applicability_type
        if appl == "fitment" and not fit_inputs:
            mk = (inp.primary_make or "").strip()
            md = (inp.primary_model or "").strip()
            if mk or md:
                fit_inputs = [
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
        primary = (
            select_primary_fitment(appl, fit_inputs) if appl == "fitment" else None
        )
        return inp, fit_inputs if appl == "fitment" else [], primary

    part_type = category_name.strip() or "Товар"
    inp = ProductNamingInput(
        part_type=part_type,
        brand="",
        article=str(row.get("default_code") or ""),
        applicability_type="universal",
        supplier_raw_name=str(row.get("name") or ""),
    )
    return inp, [], None


def preview_one_product(
    session: Session,
    row: dict[str, Any],
    *,
    pattern: str,
    raw_template: str,
    category_name: str,
) -> TemplateLivePreviewItem:
    odoo_name = str(row.get("name") or "").strip()
    try:
        inp, fitments, primary = _naming_inputs_for_odoo_row(
            session, row, category_name=category_name
        )
        result = generate_naming_result(
            pattern=pattern,
            inp=inp,
            fitments=fitments,
            primary=primary,
        )
        mods = _token_modifiers(raw_template)
        if mods and result.name:
            brand_skip = skip_brand(inp.brand)
            article_primary, article_cross = split_article(inp.article)
            tokens = build_format_tokens(
                inp,
                primary,
                brand_skipped=brand_skip,
                article_primary=article_primary,
                article_cross=article_cross,
            )
            tokens = _apply_token_modifiers(tokens, mods)
            result.name = render_name_pattern(pattern, tokens).strip()
    except NamingValidationError as exc:
        return TemplateLivePreviewItem(
            odoo_id=int(row["id"]) if row.get("id") is not None else None,
            odoo_name=odoo_name,
            generated_name="",
            status="error",
            warnings=[str(exc)],
        )

    return TemplateLivePreviewItem(
        odoo_id=int(row["id"]) if row.get("id") is not None else None,
        odoo_name=odoo_name,
        generated_name=result.name.strip(),
        status=result.status,
        warnings=list(result.warnings),
    )


def run_live_preview(
    session: Session,
    *,
    category_id: int,
    template_string: str,
    client: OdooClient | None = None,
) -> TemplateLivePreviewResponse:
    cat = session.get(OdooCategory, category_id)
    if cat is None:
        raise LookupError("category_not_found")

    normalized = normalize_template_string(template_string)
    category_name = (cat.complete_name or cat.name or "").strip()
    rows, source = fetch_sample_products(session, category_id, limit=3, client=client)

    items = [
        preview_one_product(
            session,
            row,
            pattern=normalized,
            raw_template=template_string,
            category_name=category_name,
        )
        for row in rows
    ]

    return TemplateLivePreviewResponse(
        category_id=category_id,
        template_string=template_string.strip(),
        normalized_pattern=normalized,
        items=items,
        sample_source=source,
    )
