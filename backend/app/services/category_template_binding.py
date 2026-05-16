"""Resolve Odoo category → naming matrix (logical id) and physical ``templates`` keys."""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.odoo_catalog_cache import OdooCategory, OdooProductTemplate
from app.models.product import Product
from app.models.template import Template
from app.services.naming_matrices import physical_template_key


def _categories_from_odoo_template(
    session: Session, product: Product
) -> Iterator[OdooCategory]:
    oid_raw = (product.odoo_product_id or "").strip()
    if not oid_raw.isdigit():
        return
    tpl = session.get(OdooProductTemplate, int(oid_raw))
    if tpl is None or tpl.categ_id is None:
        return
    cid: int | None = tpl.categ_id
    seen: set[int] = set()
    while cid is not None and cid not in seen:
        seen.add(cid)
        cat = session.get(OdooCategory, cid)
        if cat is None:
            break
        yield cat
        cid = cat.parent_id


def _categories_from_folder(
    session: Session, product: Product
) -> Iterator[OdooCategory]:
    folder = (product.product_folder or "").strip()
    if not folder:
        return
    cat = session.scalar(
        select(OdooCategory).where(OdooCategory.complete_name == folder).limit(1)
    )
    if cat is None:
        cat = session.scalar(
            select(OdooCategory).where(OdooCategory.name == folder).limit(1)
        )
    if cat is None:
        return
    cid: int | None = cat.odoo_id
    seen: set[int] = set()
    while cid is not None and cid not in seen:
        seen.add(cid)
        row = session.get(OdooCategory, cid)
        if row is None:
            break
        yield row
        cid = row.parent_id


def iter_categories_for_product(
    session: Session, product: Product
) -> Iterator[OdooCategory]:
    """Yield category chain (leaf → parents), preferring Odoo template categ_id."""
    yielded: set[int] = set()
    for gen in (_categories_from_odoo_template, _categories_from_folder):
        for cat in gen(session, product):
            if cat.odoo_id not in yielded:
                yielded.add(cat.odoo_id)
                yield cat


def resolve_logical_matrix_id(session: Session, product: Product) -> str | None:
    for cat in iter_categories_for_product(session, product):
        key = (cat.naming_template_key or "").strip()
        if key:
            return key
    return None


def latest_template_version(
    session: Session, *, template_key: str, applicability_type: str
) -> str | None:
    ver = session.scalar(
        select(Template.version)
        .where(
            Template.template_key == template_key,
            Template.applicability_type == applicability_type,
            Template.is_active.is_(True),
        )
        .order_by(Template.version.desc())
        .limit(1)
    )
    return str(ver) if ver else None


def physical_keys_for_product_matrix(
    session: Session,
    *,
    logical_matrix_id: str,
    applicability_type: str,
) -> tuple[str, str] | None:
    """Returns ``(template_key, template_version)`` if seeded rows exist."""
    if applicability_type not in ("fitment", "universal"):
        return None
    phys = physical_template_key(logical_matrix_id, applicability_type)  # type: ignore[arg-type]
    ver = latest_template_version(session, template_key=phys, applicability_type=applicability_type)
    if not ver:
        return None
    return phys, ver
