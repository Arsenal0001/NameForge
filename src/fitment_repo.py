"""Repository for fitment rows and primary selection (SQLite)."""

from __future__ import annotations

import sqlite3
from typing import Iterable

from pydantic import BaseModel

from .db import get_conn
from .name_generator import format_years


class FitmentRow(BaseModel):
    """One fitment row as stored or edited in memory."""

    id: int | None = None
    product_id: int
    make: str
    model: str
    body: str | None = None
    year_from: int | None = None
    year_to: int | None = None  # 0 = н.в. (see format_years)
    engine: str | None = None
    is_primary: int = 0
    sort_order: int = 0


def _collapse_spaces(text: str) -> str:
    return " ".join(text.split())


def build_fitment_summary(rows: Iterable[FitmentRow]) -> str:
    """
    Pure formatter: one segment per row, rows joined by '; '.
    Uses ``format_years`` from ``name_generator`` for the years segment.
    """
    rows_list = list(rows)
    rows_list.sort(key=lambda r: (r.sort_order, r.id or 0))

    lines: list[str] = []
    for r in rows_list:
        parts: list[str] = []
        if r.make.strip():
            parts.append(r.make.strip())
        if r.model.strip():
            parts.append(r.model.strip())
        if r.body and r.body.strip():
            parts.append(r.body.strip())
        years = format_years(r.year_from, r.year_to)
        if years:
            parts.append(years)
        if r.engine and r.engine.strip():
            parts.append(r.engine.strip())
        line = _collapse_spaces(" ".join(parts))
        if line:
            lines.append(line)

    return "; ".join(lines)


def get_fitment(product_id: int) -> list[FitmentRow]:
    """Return all fitment rows for a product, sorted by sort_order ASC, id ASC."""
    sql = """
        SELECT id, product_id, make, model, body, year_from, year_to, engine,
               is_primary, sort_order
        FROM fitments
        WHERE product_id = ?
        ORDER BY sort_order ASC, id ASC
    """
    with get_conn() as conn:
        cur = conn.execute(sql, (product_id,))
        db_rows = cur.fetchall()

    result: list[FitmentRow] = []
    for row in db_rows:
        result.append(
            FitmentRow(
                id=row[0],
                product_id=row[1],
                make=row[2] or "",
                model=row[3] or "",
                body=row[4],
                year_from=row[5],
                year_to=row[6],
                engine=row[7],
                is_primary=int(row[8]),
                sort_order=int(row[9]),
            )
        )
    return result


def _normalize_row_input(r: FitmentRow, product_id: int) -> FitmentRow:
    return FitmentRow(
        id=r.id,
        product_id=product_id,
        make=r.make.strip(),
        model=r.model.strip(),
        body=r.body.strip() if r.body and r.body.strip() else None,
        year_from=r.year_from,
        year_to=r.year_to,
        engine=r.engine.strip() if r.engine and r.engine.strip() else None,
        is_primary=0,
        sort_order=r.sort_order,
    )


def _resolve_primary_db_id(
    new_ids: list[int],
    normalized: list[FitmentRow],
    selected_primary_id: int | None,
) -> int | None:
    """
    Choose SQLite row id for the primary fitment row.

    - One row → its id.
    - ``selected_primary_id`` if it matches a newly inserted id.
    - Else match ``selected_primary_id`` to ``normalized[i].id`` (pre-save UI id).
    - Else first row by (sort_order, id).
    """
    if not new_ids:
        return None
    if len(new_ids) == 1:
        return new_ids[0]

    if selected_primary_id is not None:
        if selected_primary_id in new_ids:
            return selected_primary_id
        for i, r in enumerate(normalized):
            if r.id is not None and r.id == selected_primary_id:
                return new_ids[i]

    ordered = sorted(range(len(normalized)), key=lambda i: (normalized[i].sort_order, normalized[i].id or 0))
    return new_ids[ordered[0]]


def _save_fitment_impl(
    conn: sqlite3.Connection,
    product_id: int,
    normalized: list[FitmentRow],
    selected_primary_id: int | None,
) -> None:
    conn.execute("DELETE FROM fitments WHERE product_id = ?", (product_id,))

    new_ids: list[int] = []
    for r in normalized:
        cursor = conn.execute(
            """
            INSERT INTO fitments (
                product_id, make, model, body, year_from, year_to,
                engine, is_primary, sort_order
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)
            """,
            (
                product_id,
                r.make,
                r.model,
                r.body,
                r.year_from,
                r.year_to,
                r.engine,
                r.sort_order,
            ),
        )
        new_ids.append(int(cursor.lastrowid))

    conn.execute(
        "UPDATE fitments SET is_primary = 0 WHERE product_id = ?",
        (product_id,),
    )

    primary_db_id = _resolve_primary_db_id(new_ids, normalized, selected_primary_id)

    if primary_db_id is None:
        conn.execute(
            """
            UPDATE products
            SET primary_make = NULL,
                primary_model = NULL,
                primary_body = NULL,
                year_from = NULL,
                year_to = NULL,
                engine = NULL,
                fitment_summary = NULL
            WHERE id = ?
            """,
            (product_id,),
        )
        return

    conn.execute(
        "UPDATE fitments SET is_primary = 1 WHERE id = ?",
        (primary_db_id,),
    )

    primary_idx = new_ids.index(primary_db_id)
    pr = normalized[primary_idx]

    summary_rows = [
        FitmentRow(
            id=new_ids[i],
            product_id=product_id,
            make=normalized[i].make,
            model=normalized[i].model,
            body=normalized[i].body,
            year_from=normalized[i].year_from,
            year_to=normalized[i].year_to,
            engine=normalized[i].engine,
            is_primary=1 if new_ids[i] == primary_db_id else 0,
            sort_order=normalized[i].sort_order,
        )
        for i in range(len(normalized))
    ]
    summary = build_fitment_summary(summary_rows)

    conn.execute(
        """
        UPDATE products
        SET primary_make = ?,
            primary_model = ?,
            primary_body = ?,
            year_from = ?,
            year_to = ?,
            engine = ?,
            fitment_summary = ?
        WHERE id = ?
        """,
        (
            pr.make,
            pr.model,
            pr.body,
            pr.year_from,
            pr.year_to,
            pr.engine,
            summary,
            product_id,
        ),
    )


def save_fitment(
    product_id: int,
    rows: list[FitmentRow],
    selected_primary_id: int | None = None,
    conn: sqlite3.Connection | None = None,
) -> None:
    """
    Replace fitments for a product and sync ``products`` primary columns.

    Transaction: BEGIN IMMEDIATE → DELETE → INSERT → reset ``is_primary`` →
    pick primary → set ``is_primary=1`` → UPDATE ``products``.

    Pass ``conn`` to join an outer transaction (avoids nested ``get_conn()``).
    """
    normalized = [_normalize_row_input(r, product_id) for r in rows]
    for r in normalized:
        if not r.make or not r.model:
            raise ValueError("make and model are required for each fitment row")

    if conn is None:
        with get_conn() as own:
            own.execute("BEGIN IMMEDIATE")
            _save_fitment_impl(own, product_id, normalized, selected_primary_id)
    else:
        _save_fitment_impl(conn, product_id, normalized, selected_primary_id)


def _delete_all_fitment_impl(conn: sqlite3.Connection, product_id: int) -> None:
    conn.execute("DELETE FROM fitments WHERE product_id = ?", (product_id,))
    conn.execute(
        """
        UPDATE products
        SET primary_make = NULL,
            primary_model = NULL,
            primary_body = NULL,
            year_from = NULL,
            year_to = NULL,
            engine = NULL,
            fitment_summary = NULL
        WHERE id = ?
        """,
        (product_id,),
    )


def delete_all_fitment(product_id: int, conn: sqlite3.Connection | None = None) -> None:
    """Remove all fitment rows and clear denormalized primary fields on products."""
    if conn is None:
        with get_conn() as own:
            own.execute("BEGIN IMMEDIATE")
            _delete_all_fitment_impl(own, product_id)
    else:
        _delete_all_fitment_impl(conn, product_id)


def list_products_brief(conn: sqlite3.Connection, limit: int = 50) -> list[dict]:
    """Returns id, article, brand, part_type, applicability_type for UI selector."""
    old_rf = conn.row_factory
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, article, brand, part_type, applicability_type "
            "FROM products ORDER BY id LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.row_factory = old_rf
