"""Server-side catalog list filters (SQL-only, applied before pagination)."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Select, and_, cast, func, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql import ColumnElement
from sqlalchemy.types import Integer

from app.models.odoo_catalog_cache import OdooCategory, OdooProductTemplate
from app.models.product import Product
from app.schemas.catalog_product import NamingStatus

_MAX_SEARCH_LEN = 200


@dataclass(frozen=True)
class CatalogListFilters:
    search: str | None = None
    naming_status: NamingStatus | None = None
    is_locked: bool | None = None
    has_error: bool | None = None


def _catalog_base_select() -> Select[tuple[Product]]:
    return (
        select(Product)
        .outerjoin(
            OdooProductTemplate,
            cast(Product.odoo_product_id, Integer) == OdooProductTemplate.odoo_id,
        )
        .outerjoin(
            OdooCategory,
            OdooCategory.odoo_id == OdooProductTemplate.categ_id,
        )
    )


def _preview_name_expr():
    return func.trim(func.coalesce(Product.generated_name, ""))


def _cache_name_expr():
    return func.trim(func.coalesce(OdooProductTemplate.name, ""))


def _has_template_expr() -> ColumnElement[bool]:
    return or_(
        func.trim(func.coalesce(OdooCategory.name_pattern, "")) != "",
        func.trim(func.coalesce(OdooCategory.naming_template_key, "")) != "",
    )


def _naming_status_predicates() -> tuple[ColumnElement[bool], ColumnElement[bool]]:
    preview = _preview_name_expr()
    cache_name = _cache_name_expr()
    has_template = _has_template_expr()
    names_match = and_(preview != "", cache_name != "", preview == cache_name)
    is_synced = and_(has_template, names_match)
    is_pending = and_(has_template, ~names_match)
    is_no_template = ~has_template
    return is_synced, is_pending, is_no_template


def _search_predicate(term: str) -> ColumnElement[bool]:
    q = term.strip().lower()[:_MAX_SEARCH_LEN]
    pattern = f"%{q}%"
    return or_(
        func.lower(Product.article).like(pattern),
        func.lower(Product.external_code).like(pattern),
        func.lower(func.coalesce(Product.generated_name, "")).like(pattern),
        func.lower(func.coalesce(OdooProductTemplate.name, "")).like(pattern),
    )


def apply_catalog_filters(
    stmt: Select[tuple[Product]],
    filters: CatalogListFilters,
) -> Select[tuple[Product]]:
    conditions: list[ColumnElement[bool]] = []

    if filters.search and filters.search.strip():
        conditions.append(_search_predicate(filters.search))

    if filters.is_locked is not None:
        conditions.append(Product.name_locked.is_(filters.is_locked))

    if filters.has_error is True:
        conditions.append(func.trim(func.coalesce(Product.last_sync_error, "")) != "")
    elif filters.has_error is False:
        conditions.append(func.trim(func.coalesce(Product.last_sync_error, "")) == "")

    if filters.naming_status is not None:
        is_synced, is_pending, is_no_template = _naming_status_predicates()
        if filters.naming_status == "synced":
            conditions.append(is_synced)
        elif filters.naming_status == "pending_sync":
            conditions.append(is_pending)
        elif filters.naming_status == "no_template":
            conditions.append(is_no_template)

    if conditions:
        stmt = stmt.where(and_(*conditions))
    return stmt


def query_catalog_products(
    session: Session,
    *,
    filters: CatalogListFilters,
    offset: int,
    limit: int,
) -> tuple[list[Product], int]:
    """Return one paginated page and the total count for the same filter set."""
    base = _catalog_base_select()
    filtered = apply_catalog_filters(base, filters)

    total = session.scalar(
        select(func.count()).select_from(filtered.subquery())
    )
    if total is None:
        total = 0

    rows = session.scalars(
        filtered.order_by(Product.id.asc()).offset(offset).limit(limit)
    ).all()
    return list(rows), int(total)
