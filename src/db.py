"""
SQLite schema initialization and connection helpers for the AutoName MVP.

Default database: project root / data / autoname.db
Constants match the canonical enums (enforced in application code, not CHECK constraints).
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Optional

# --- Canonical enums (application-level; not enforced by SQLite CHECK) ---

ALIAS_TYPES = (
    "brand",
    "part_type",
    "make",
    "model",
    "body",
    "side",
    "engine",
)

GENERATION_STATUSES = (
    "new",
    "review",
    "approved",
    "error",
    "locked",
)

APPLICABILITY_TYPES = (
    "fitment",
    "universal",
)

# Project root = parent of src/ (e.g. c:\PyProject\NameForge)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_DB_PATH = _PROJECT_ROOT / "data" / "autoname.db"

# Override for tests (see tests/conftest or test modules).
DB_PATH: Optional[str | Path] = None


def _default_db_path() -> Path:
    if DB_PATH is not None:
        return Path(DB_PATH)
    return _DEFAULT_DB_PATH


def run_migrations(conn: sqlite3.Connection) -> None:
    """Idempotent ALTERs for older SQLite files (CREATE IF NOT EXISTS does not add columns)."""
    existing = {r[1] for r in conn.execute("PRAGMA table_info(products)").fetchall()}
    migrations = [
        "ALTER TABLE products ADD COLUMN error_message TEXT",
        "ALTER TABLE products ADD COLUMN generated_name TEXT",
        "ALTER TABLE products ADD COLUMN synced_at TEXT",
        "ALTER TABLE products ADD COLUMN product_folder TEXT",
    ]
    for sql in migrations:
        col = sql.split("COLUMN ")[1].split(" ")[0]
        if col not in existing:
            conn.execute(sql)
            print(f"Migration: added column {col}")

    templates_cols = {r[1] for r in conn.execute("PRAGMA table_info(templates)").fetchall()}
    if templates_cols and "part_type_pattern" not in templates_cols:
        conn.execute("ALTER TABLE templates ADD COLUMN part_type_pattern TEXT")
        print("Migration: added column part_type_pattern on templates")

    if templates_cols and "part_type_trigger" not in templates_cols:
        conn.execute("ALTER TABLE templates ADD COLUMN part_type_trigger TEXT")
        print("Migration: added column part_type_trigger on templates")

    if "created__at" in templates_cols and "created_at" not in templates_cols:
        conn.execute('ALTER TABLE templates RENAME COLUMN "created__at" TO "created_at"')
        print("Migration: renamed column created__at → created_at on templates")

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_templates_part_type
            ON templates (part_type_trigger)
            WHERE part_type_trigger IS NOT NULL
        """
    )

    _ensure_part_type_folder_map(conn)

    _migrate_category_mapping(conn)


def _ensure_part_type_folder_map(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS part_type_folder_map (
            part_type TEXT PRIMARY KEY,
            ms_folder_path TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def _migrate_category_mapping(conn: sqlite3.Connection) -> None:
    """
    Ensure ``category_mapping`` matches the current (pattern-based) schema.

    Old schema (deprecated): ``part_type TEXT UNIQUE``, ``folder_path TEXT``.
    New schema: ``part_type_pattern``, ``ms_folder_path``, ``priority``,
    ``is_active``, ``created_at``. Preserves existing rows on migration.
    """
    existing_row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='category_mapping'"
    ).fetchone()

    if existing_row:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(category_mapping)").fetchall()}
        if "part_type_pattern" not in cols:
            legacy_rows: list[tuple[str, str]] = []
            if "part_type" in cols and "folder_path" in cols:
                legacy_rows = [
                    (str(r[0] or "").strip(), str(r[1] or "").strip())
                    for r in conn.execute(
                        "SELECT part_type, folder_path FROM category_mapping"
                    ).fetchall()
                ]
            conn.execute("DROP TABLE category_mapping")
            _create_category_mapping(conn)
            for pattern, folder in legacy_rows:
                if not pattern or not folder:
                    continue
                conn.execute(
                    """
                    INSERT OR IGNORE INTO category_mapping
                        (part_type_pattern, ms_folder_path, priority, is_active)
                    VALUES (?, ?, 0, 1)
                    """,
                    (pattern, folder),
                )
            if legacy_rows:
                print(
                    f"Migration: category_mapping migrated "
                    f"({len(legacy_rows)} legacy rows)"
                )
            return

    _create_category_mapping(conn)


def _create_category_mapping(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS category_mapping (
            id                INTEGER PRIMARY KEY,
            part_type_pattern TEXT    NOT NULL,
            ms_folder_path    TEXT    NOT NULL,
            priority          INTEGER NOT NULL DEFAULT 0,
            is_active         INTEGER NOT NULL DEFAULT 1,
            created_at        TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS ux_catmap_pattern
            ON category_mapping (part_type_pattern)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_catmap_priority
            ON category_mapping (is_active, priority DESC)
        """
    )


def get_effective_db_path() -> Path:
    """Path used by ``get_conn()`` when no override is passed (for UI / diagnostics)."""
    p = _default_db_path()
    if str(p) == ":memory:":
        return p
    try:
        return p.resolve(strict=False)
    except OSError:
        return p


def init_db(db_path: Optional[str | Path] = None) -> None:
    """
    Create schema if missing: tables, indexes, and updated_at triggers.

    Uses WAL journal and enables foreign keys for every connection via get_conn().
    """
    path = Path(db_path) if db_path else _default_db_path()
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)

    ddl = """
    PRAGMA foreign_keys = ON;

    -- =========================
    -- templates (must exist before products FK)
    -- =========================
    CREATE TABLE IF NOT EXISTS templates (
        id                 INTEGER PRIMARY KEY,
        template_key       TEXT    NOT NULL,
        version            TEXT    NOT NULL,
        applicability_type TEXT    NOT NULL,
        name_pattern       TEXT    NOT NULL,
        is_active          INTEGER NOT NULL DEFAULT 1,
        created_at         TEXT    NOT NULL DEFAULT (CURRENT_TIMESTAMP),
        updated_at         TEXT    NOT NULL DEFAULT (CURRENT_TIMESTAMP),
        UNIQUE (template_key, version)
    );

    CREATE INDEX IF NOT EXISTS idx_templates_key_active
        ON templates (template_key, is_active);

    -- =========================
    -- products
    -- =========================
    CREATE TABLE IF NOT EXISTS products (
        id                 INTEGER PRIMARY KEY,
        ms_product_id      TEXT    NOT NULL,
        external_code      TEXT    NOT NULL,
        article            TEXT    NOT NULL,
        brand              TEXT    NOT NULL,
        part_type          TEXT    NOT NULL,
        applicability_type TEXT    NOT NULL,
        side_axis          TEXT    NULL,
        cross_numbers      TEXT    NULL,
        supplier_raw_name  TEXT    NULL,
        primary_make       TEXT    NULL,
        primary_model      TEXT    NULL,
        primary_body       TEXT    NULL,
        year_from          INTEGER NULL,
        year_to            INTEGER NULL,
        engine             TEXT    NULL,
        fitment_summary    TEXT    NULL,
        template_key       TEXT    NOT NULL,
        template_version   TEXT    NOT NULL,
        generation_status  TEXT    NOT NULL DEFAULT 'new',
        name_locked        INTEGER NOT NULL DEFAULT 0,
        generated_name     TEXT    NULL,
        synced_at          TEXT    NULL,
        error_message      TEXT    NULL,
        source_hash        TEXT    NOT NULL DEFAULT '',
        created_at         TEXT    NOT NULL DEFAULT (CURRENT_TIMESTAMP),
        updated_at         TEXT    NOT NULL DEFAULT (CURRENT_TIMESTAMP),
        UNIQUE (ms_product_id),
        UNIQUE (external_code),
        FOREIGN KEY (template_key, template_version)
            REFERENCES templates (template_key, version)
            ON UPDATE CASCADE
            ON DELETE RESTRICT
    );

    CREATE INDEX IF NOT EXISTS idx_products_article
        ON products (article);

    CREATE INDEX IF NOT EXISTS idx_products_brand
        ON products (brand);

    CREATE INDEX IF NOT EXISTS idx_products_brand_article
        ON products (brand, article);

    CREATE INDEX IF NOT EXISTS idx_products_generation_status
        ON products (generation_status);

    CREATE INDEX IF NOT EXISTS idx_products_applicability_type
        ON products (applicability_type);

    CREATE INDEX IF NOT EXISTS idx_products_template
        ON products (template_key, template_version);

    -- =========================
    -- fitments
    -- =========================
    CREATE TABLE IF NOT EXISTS fitments (
        id         INTEGER PRIMARY KEY,
        product_id INTEGER NOT NULL,
        make       TEXT    NOT NULL,
        model      TEXT    NOT NULL,
        body       TEXT    NULL,
        year_from  INTEGER NULL,
        year_to    INTEGER NULL,
        engine     TEXT    NULL,
        is_primary INTEGER NOT NULL DEFAULT 0,
        sort_order INTEGER NOT NULL DEFAULT 0,
        created_at TEXT    NOT NULL DEFAULT (CURRENT_TIMESTAMP),
        updated_at TEXT    NOT NULL DEFAULT (CURRENT_TIMESTAMP),
        FOREIGN KEY (product_id)
            REFERENCES products (id)
            ON UPDATE CASCADE
            ON DELETE CASCADE
    );

    CREATE INDEX IF NOT EXISTS idx_fitments_product
        ON fitments (product_id);

    CREATE INDEX IF NOT EXISTS idx_fitments_product_sort
        ON fitments (product_id, sort_order, id);

    CREATE INDEX IF NOT EXISTS idx_fitments_make_model
        ON fitments (make, model);

    CREATE UNIQUE INDEX IF NOT EXISTS ux_fitments_one_primary_per_product
        ON fitments (product_id)
        WHERE is_primary = 1;

    -- =========================
    -- aliases
    -- =========================
    CREATE TABLE IF NOT EXISTS aliases (
        id              INTEGER PRIMARY KEY,
        alias_type      TEXT    NOT NULL,
        scope_value     TEXT    NOT NULL DEFAULT '',
        alias           TEXT    NOT NULL,
        alias_norm      TEXT    NOT NULL,
        canonical_value TEXT    NOT NULL,
        is_active       INTEGER NOT NULL DEFAULT 1,
        created_at      TEXT    NOT NULL DEFAULT (CURRENT_TIMESTAMP),
        updated_at      TEXT    NOT NULL DEFAULT (CURRENT_TIMESTAMP)
    );

    CREATE UNIQUE INDEX IF NOT EXISTS ux_aliases_lookup
        ON aliases (alias_type, scope_value, alias_norm);

    CREATE INDEX IF NOT EXISTS idx_aliases_canonical
        ON aliases (alias_type, canonical_value);

    CREATE INDEX IF NOT EXISTS idx_aliases_active
        ON aliases (alias_type, is_active);

    -- =========================
    -- updated_at triggers (recursive_triggers default OFF: safe self-UPDATE)
    -- =========================
    CREATE TRIGGER IF NOT EXISTS trg_products_updated_at
    AFTER UPDATE ON products
    FOR EACH ROW
    WHEN NEW.updated_at = OLD.updated_at
    BEGIN
        UPDATE products
        SET updated_at = CURRENT_TIMESTAMP
        WHERE id = NEW.id;
    END;

    CREATE TRIGGER IF NOT EXISTS trg_fitments_updated_at
    AFTER UPDATE ON fitments
    FOR EACH ROW
    WHEN NEW.updated_at = OLD.updated_at
    BEGIN
        UPDATE fitments
        SET updated_at = CURRENT_TIMESTAMP
        WHERE id = NEW.id;
    END;

    CREATE TRIGGER IF NOT EXISTS trg_templates_updated_at
    AFTER UPDATE ON templates
    FOR EACH ROW
    WHEN NEW.updated_at = OLD.updated_at
    BEGIN
        UPDATE templates
        SET updated_at = CURRENT_TIMESTAMP
        WHERE id = NEW.id;
    END;

    CREATE TRIGGER IF NOT EXISTS trg_aliases_updated_at
    AFTER UPDATE ON aliases
    FOR EACH ROW
    WHEN NEW.updated_at = OLD.updated_at
    BEGIN
        UPDATE aliases
        SET updated_at = CURRENT_TIMESTAMP
        WHERE id = NEW.id;
    END;
    """

    conn = sqlite3.connect(str(path))
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(ddl)
        run_migrations(conn)
        conn.commit()
    finally:
        conn.close()

    from src.template_engine import seed_default_templates

    seed_default_templates()


@contextmanager
def get_conn(db_path: Optional[str | Path] = None) -> Generator[sqlite3.Connection, None, None]:
    """
    Yield a SQLite connection with foreign keys and WAL enabled.

    Commits on success, rolls back on exception, always closes.
    """
    path = Path(db_path) if db_path else _default_db_path()
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
