"""Lightweight additive schema fixes (no Alembic)."""

from __future__ import annotations

import logging

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)


def _ensure_odoo_cache_tables(engine: Engine) -> None:
    """Create NameForge 2.0 Odoo cache tables when missing (legacy DB upgrade)."""
    from app.core.database import Base
    from app.models.odoo_catalog_cache import (
        OdooCategory,
        OdooProductAttribute,
        OdooProductAttributeValue,
        OdooProductTemplate,
    )
    from app.models.product_fitment import ProductVehicleFitment

    tables = [
        OdooCategory.__table__,
        OdooProductAttribute.__table__,
        OdooProductAttributeValue.__table__,
        OdooProductTemplate.__table__,
        ProductVehicleFitment.__table__,
    ]
    Base.metadata.create_all(engine, tables=tables)
    logger.info("Ensured Odoo cache tables exist")


def apply_schema_patches(engine: Engine) -> None:
    _ensure_odoo_cache_tables(engine)
    dialect = engine.dialect.name
    if dialect == "sqlite":
        _patch_sqlite_odoo_categories(engine)
        _patch_sqlite_products_search_keywords(engine)
        _patch_sqlite_products_last_sync_error(engine)
    elif dialect == "postgresql":
        _patch_postgres_odoo_categories(engine)
        _patch_postgres_products_search_keywords(engine)
        _patch_postgres_products_last_sync_error(engine)
    else:
        logger.warning("Schema patches: unsupported dialect %s", dialect)


def _patch_sqlite_odoo_categories(engine: Engine) -> None:
    with engine.begin() as conn:
        exists = conn.execute(
            text(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='odoo_categories'"
            )
        ).scalar()
        if not exists:
            return
        rows = conn.execute(text("PRAGMA table_info(odoo_categories)")).fetchall()
        cols = {r[1] for r in rows}
        if "naming_template_key" not in cols:
            conn.execute(
                text(
                    "ALTER TABLE odoo_categories "
                    "ADD COLUMN naming_template_key TEXT"
                )
            )
            logger.info("Migration: odoo_categories.naming_template_key added")
        rows = conn.execute(text("PRAGMA table_info(odoo_categories)")).fetchall()
        cols = {r[1] for r in rows}
        if "name_pattern" not in cols:
            conn.execute(
                text("ALTER TABLE odoo_categories ADD COLUMN name_pattern TEXT")
            )
            logger.info("Migration: odoo_categories.name_pattern added")


def _patch_postgres_odoo_categories(engine: Engine) -> None:
    try:
        insp = inspect(engine)
        if not insp.has_table("odoo_categories"):
            return
        cols = {c["name"] for c in insp.get_columns("odoo_categories")}
        if "naming_template_key" not in cols:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "ALTER TABLE odoo_categories "
                        "ADD COLUMN naming_template_key TEXT"
                    )
                )
            logger.info("Migration: odoo_categories.naming_template_key added")
        cols = {c["name"] for c in insp.get_columns("odoo_categories")}
        if "name_pattern" not in cols:
            with engine.begin() as conn:
                conn.execute(
                    text("ALTER TABLE odoo_categories ADD COLUMN name_pattern TEXT")
                )
            logger.info("Migration: odoo_categories.name_pattern added")
    except Exception as exc:
        logger.warning("Postgres schema patch skipped: %s", exc)


def _patch_sqlite_products_search_keywords(engine: Engine) -> None:
    with engine.begin() as conn:
        exists = conn.execute(
            text(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='products'"
            )
        ).scalar()
        if not exists:
            return
        rows = conn.execute(text("PRAGMA table_info(products)")).fetchall()
        cols = {r[1] for r in rows}
        if "search_keywords" not in cols:
            conn.execute(
                text("ALTER TABLE products ADD COLUMN search_keywords TEXT")
            )
            logger.info("Migration: products.search_keywords added")


def _patch_sqlite_products_last_sync_error(engine: Engine) -> None:
    with engine.begin() as conn:
        exists = conn.execute(
            text(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='products'"
            )
        ).scalar()
        if not exists:
            return
        rows = conn.execute(text("PRAGMA table_info(products)")).fetchall()
        cols = {r[1] for r in rows}
        if "last_sync_error" not in cols:
            conn.execute(
                text("ALTER TABLE products ADD COLUMN last_sync_error TEXT")
            )
            logger.info("Migration: products.last_sync_error added")


def _patch_postgres_products_search_keywords(engine: Engine) -> None:
    try:
        insp = inspect(engine)
        if not insp.has_table("products"):
            return
        cols = {c["name"] for c in insp.get_columns("products")}
        if "search_keywords" not in cols:
            with engine.begin() as conn:
                conn.execute(
                    text("ALTER TABLE products ADD COLUMN search_keywords TEXT")
                )
            logger.info("Migration: products.search_keywords added")
    except Exception as exc:
        logger.warning("Postgres products.search_keywords patch skipped: %s", exc)


def _patch_postgres_products_last_sync_error(engine: Engine) -> None:
    try:
        insp = inspect(engine)
        if not insp.has_table("products"):
            return
        cols = {c["name"] for c in insp.get_columns("products")}
        if "last_sync_error" not in cols:
            with engine.begin() as conn:
                conn.execute(
                    text("ALTER TABLE products ADD COLUMN last_sync_error TEXT")
                )
            logger.info("Migration: products.last_sync_error added")
    except Exception as exc:
        logger.warning("Postgres products.last_sync_error patch skipped: %s", exc)
