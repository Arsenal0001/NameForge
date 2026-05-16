"""Load and persist name templates (SQLite via get_conn)."""

from __future__ import annotations

import sqlite3
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any

from .db import get_conn

_DEFAULT_FITMENT_PATTERN = (
    "{brand} {part_type} {article} для {make} {model} {body} {years} {engine} {side}"
)
_DEFAULT_UNIVERSAL_PATTERN = "{brand} {part_type} {article} {side}"

_DEFAULT_TEMPLATE_ROWS = (
    ("fitment_base", "v1", "fitment", _DEFAULT_FITMENT_PATTERN),
    ("universal_base", "v1", "universal", _DEFAULT_UNIVERSAL_PATTERN),
)

_SEED_SQL = """
    INSERT OR IGNORE INTO templates (
        template_key, version, applicability_type, name_pattern
    )
    VALUES (?, ?, ?, ?)
"""


def _seed_default_template_rows(conn: sqlite3.Connection) -> None:
    """Insert default MVP templates if missing (same connection as DDL / tests)."""
    for template_key, version, applicability_type, name_pattern in _DEFAULT_TEMPLATE_ROWS:
        conn.execute(
            _SEED_SQL,
            (template_key, version, applicability_type, name_pattern),
        )


def _has_wildcard(pattern: str) -> bool:
    return any(ch in pattern for ch in ("*", "?", "["))


def _find_pattern_template(
    conn: sqlite3.Connection,
    part_type: str,
    applicability_type: str,
) -> str | None:
    """
    Match ``templates.part_type_pattern`` against ``part_type`` using fnmatch
    (case-insensitive). Exact-literal patterns outrank glob patterns; ties go to
    the highest ``version`` and then the longest pattern.
    """
    cur = conn.execute(
        """
        SELECT name_pattern, part_type_pattern, version
        FROM templates
        WHERE applicability_type = ?
          AND is_active = 1
          AND part_type_pattern IS NOT NULL
          AND TRIM(part_type_pattern) != ''
        """,
        (applicability_type,),
    )
    rows = cur.fetchall()
    needle = (part_type or "").strip().casefold()
    if not needle:
        return None

    candidates: list[tuple[int, int, str, str]] = []
    for name_pattern, pt_pattern, version in rows:
        pat = str(pt_pattern or "").strip()
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
        candidates.append(
            (specificity, len(pat_cf), str(version or ""), str(name_pattern or ""))
        )

    if not candidates:
        return None

    candidates.sort(key=lambda t: (t[0], t[2], t[1]), reverse=True)
    return candidates[0][3] or None


def _load_by_template_key(
    conn: sqlite3.Connection,
    template_key: str,
    applicability_type: str,
) -> str | None:
    cur = conn.execute(
        """
        SELECT name_pattern
        FROM templates
        WHERE template_key = ?
          AND applicability_type = ?
          AND is_active = 1
          AND (part_type_trigger IS NULL OR TRIM(part_type_trigger) = '')
        ORDER BY version DESC
        LIMIT 1
        """,
        (template_key, applicability_type),
    )
    row = cur.fetchone()
    return str(row[0]) if row and row[0] else None


def _load_by_part_type_trigger(
    conn: sqlite3.Connection,
    part_type: str,
    applicability_type: str,
) -> str | None:
    cur = conn.execute(
        """
        SELECT name_pattern
        FROM templates
        WHERE part_type_trigger = ?
          AND applicability_type = ?
          AND is_active = 1
        ORDER BY version DESC
        LIMIT 1
        """,
        (part_type, applicability_type),
    )
    row = cur.fetchone()
    return str(row[0]) if row and row[0] else None


def load_active_template(
    template_key: str | None,
    applicability_type: str,
    part_type: str | None = None,
) -> str | None:
    """
    Resolve an active ``name_pattern`` for a product.

    Lookup order:

    1. Exact ``part_type_trigger`` match (same string as catalog ``part_type``).
    2. ``template_key`` row with empty ``part_type_trigger`` (e.g. fitment_base).
    3. ``part_type_pattern`` (fnmatch, case-insensitive) on remaining rows.
    4. Fallback ``fitment_base`` / ``universal_base`` with empty trigger.
    """
    key = (template_key or "").strip()
    appl = (applicability_type or "").strip()
    pt = (part_type or "").strip() or None

    with get_conn() as conn:
        if pt:
            pattern = _load_by_part_type_trigger(conn, pt, appl)
            if pattern:
                return pattern

        if key:
            pattern = _load_by_template_key(conn, key, appl)
            if pattern:
                return pattern

        if pt:
            pattern = _find_pattern_template(conn, pt, appl)
            if pattern:
                return pattern

        fallback_key = "fitment_base" if appl == "fitment" else "universal_base"
        if key != fallback_key:
            pattern = _load_by_template_key(conn, fallback_key, appl)
            if pattern:
                return pattern

    return None


def list_templates() -> list[dict[str, Any]]:
    """Return all template rows as dicts, ordered by template_key then version."""
    sql = """
        SELECT id, template_key, version, applicability_type, name_pattern,
               part_type_pattern, part_type_trigger, is_active, created_at, updated_at
        FROM templates
        ORDER BY template_key, version
    """
    with get_conn() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(sql)
        rows = cur.fetchall()
    return [dict(r) for r in rows]


def save_template(
    template_key: str,
    version: str,
    applicability_type: str,
    name_pattern: str,
    is_active: bool = True,
    part_type_pattern: str | None = None,
    part_type_trigger: str | None = None,
) -> None:
    """
    Upsert one template row. When saving as active, deactivate other versions
    for the same template_key.
    """
    active_int = 1 if is_active else 0
    pt_pattern = (part_type_pattern or "").strip() or None
    pt_trigger = (part_type_trigger or "").strip() or None
    upsert = """
        INSERT INTO templates (
            template_key, version, applicability_type, name_pattern,
            part_type_pattern, is_active, part_type_trigger
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(template_key, version) DO UPDATE SET
            applicability_type = excluded.applicability_type,
            name_pattern = excluded.name_pattern,
            part_type_pattern = excluded.part_type_pattern,
            is_active = excluded.is_active,
            part_type_trigger = COALESCE(
                excluded.part_type_trigger, templates.part_type_trigger
            )
    """
    with get_conn() as conn:
        conn.execute(
            upsert,
            (
                template_key,
                version,
                applicability_type,
                name_pattern,
                pt_pattern,
                active_int,
                pt_trigger,
            ),
        )
        if is_active:
            conn.execute(
                """
                UPDATE templates
                SET is_active = 0
                WHERE template_key = ? AND version != ?
                """,
                (template_key, version),
            )


def seed_default_templates(db_path: str | Path | None = None) -> None:
    """
    Insert default MVP templates if missing (INSERT OR IGNORE).

    ``db_path`` is optional for callers that use a non-default database path.
    """
    with get_conn(db_path) as conn:
        _seed_default_template_rows(conn)
