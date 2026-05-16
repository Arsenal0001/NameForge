"""Lightweight additive schema fixes (no Alembic)."""

from __future__ import annotations

import logging

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)


def apply_schema_patches(engine: Engine) -> None:
    dialect = engine.dialect.name
    if dialect == "sqlite":
        _patch_sqlite_odoo_categories(engine)
        _patch_sqlite_products_search_keywords(engine)
    elif dialect == "postgresql":
        _patch_postgres_odoo_categories(engine)
        _patch_postgres_products_search_keywords(engine)
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
